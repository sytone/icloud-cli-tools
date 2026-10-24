"""Security policy tests: no real credentials or network access."""

from __future__ import annotations

import os
import ssl
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from icloud_cli.auth import AuthManager
from icloud_cli.config import Config
from icloud_cli.credentials import (
    SECURE_BACKENDS,
    SecureKeyringError,
    UnavailableKeyring,
    configure_secure_keyring,
    select_secure_backend,
)
from icloud_cli.daemon import _save_cache
from icloud_cli.main import cli
from icloud_cli.security import StorageSecurityError, private_dir, private_open
from icloud_cli.services.notes import IMAP_HOST, IMAP_PORT, NotesService
from icloud_cli.services.reminders import RemindersService


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_selects_only_builtin_platform_store(platform, monkeypatch):
    backend = MagicMock(priority=5)
    factory = MagicMock(return_value=backend)
    module, name = SECURE_BACKENDS[platform]
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyrings.alt.file.PlaintextKeyring")
    with patch("icloud_cli.credentials.sys.platform", platform), patch(
        "icloud_cli.credentials.import_module", return_value=SimpleNamespace(**{name: factory})
    ) as importer:
        assert select_secure_backend() is backend
    importer.assert_called_once_with(module)
    factory.assert_called_once_with()
    backend.get_password.assert_not_called()
    backend.set_password.assert_not_called()
    backend.delete_password.assert_not_called()


@pytest.mark.parametrize("failure", [ImportError("missing"), RuntimeError("no bus")])
def test_missing_system_store_fails_closed(failure):
    with patch("icloud_cli.credentials.import_module", side_effect=failure):
        backend = select_secure_backend()
    assert isinstance(backend, UnavailableKeyring)
    for method, args in [
        ("get_password", ("service", "user")),
        ("set_password", ("service", "user", "secret")),
        ("delete_password", ("service", "user")),
    ]:
        with pytest.raises(SecureKeyringError, match="Headless jobs"):
            getattr(backend, method)(*args)


def test_priority_failure_and_unsupported_platform():
    class Broken:
        @property
        def priority(self):
            raise RuntimeError("not available")

    with patch("icloud_cli.credentials.sys.platform", "linux"), patch(
        "icloud_cli.credentials.import_module", return_value=SimpleNamespace(Keyring=Broken)
    ):
        assert isinstance(select_secure_backend(), UnavailableKeyring)
    with patch("icloud_cli.credentials.sys.platform", "unsupported"):
        assert isinstance(select_secure_backend(), UnavailableKeyring)


def test_replaces_existing_plaintext_or_chainer_without_consulting_it():
    keyring_api = MagicMock()
    selected = UnavailableKeyring()
    with patch("icloud_cli.credentials.select_secure_backend", return_value=selected):
        configure_secure_keyring(keyring_api)
    keyring_api.set_keyring.assert_called_once_with(selected)
    keyring_api.get_keyring.assert_not_called()
    keyring_api.get_password.assert_not_called()


def test_runtime_locked_store_has_actionable_error(tmp_path):
    backend = UnavailableKeyring()
    backend.get_password = MagicMock(side_effect=RuntimeError("sensitive backend details"))
    # Use real keyring delegation, but never a real backend or credential.
    import keyring

    previous = keyring.core._keyring_backend
    try:
        with patch("icloud_cli.credentials.select_secure_backend", return_value=backend):
            auth = AuthManager(Config(apple_id="fake@example.test"))
        with pytest.raises(SecureKeyringError, match="unlock") as exc:
            auth.get_imap_credentials()
        assert "sensitive backend details" not in str(exc.value)
        backend.get_password.assert_called_once()
    finally:
        keyring.core._keyring_backend = previous


def test_notes_uses_verified_context_and_expected_host():
    with patch("icloud_cli.services.notes.imaplib.IMAP4_SSL") as imap:
        NotesService("fake@example.test", "fake-password")._connect()
    assert imap.call_args.args == (IMAP_HOST, IMAP_PORT)
    context = imap.call_args.kwargs["ssl_context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    imap.return_value.login.assert_called_once_with("fake@example.test", "fake-password")


def test_notes_certificate_failure_does_not_login_or_retry():
    with patch("icloud_cli.services.notes.imaplib.IMAP4_SSL") as imap:
        imap.side_effect = ssl.SSLCertVerificationError("untrusted certificate")
        with pytest.raises(ssl.SSLCertVerificationError):
            NotesService("fake@example.test", "fake-password")._connect()
    imap.assert_called_once()
    imap.return_value.login.assert_not_called()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_existing_config_session_and_recursive_cache_hardened(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text('[auth]\napple_id = "fake@example.test"\n')
    config_file.chmod(0o644)
    session = tmp_path / "session"
    cache = tmp_path / "cache"
    for directory in [session, cache / "reminders"]:
        directory.mkdir(parents=True)
        directory.chmod(0o755)
        (directory / "data").write_text("private")
        (directory / "data").chmod(0o644)
    tmp_path.chmod(0o755)
    config = Config.load(config_file)
    config.session_dir, config.cache_dir = str(session), str(cache)
    config.ensure_dirs()
    config.save()
    assert tmp_path.stat().st_mode & 0o777 == 0o755  # custom config parent isn't ours
    for directory in [session, cache, cache / "reminders"]:
        assert directory.stat().st_mode & 0o777 == 0o700
    for file in [config_file, session / "data", cache / "reminders" / "data"]:
        assert file.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_writes_private_even_with_permissive_umask(tmp_path):
    previous = os.umask(0)
    try:
        config = Config(config_file=tmp_path / "config.toml", cache_dir=str(tmp_path / "cache"))
        config.save()
        _save_cache(tmp_path / "cache" / "calendar.json", [{"private": "data"}])
        service = RemindersService(MagicMock(), config)
        service._write_sync_state("cursor", [])
        for file in [config.config_file, tmp_path / "cache/calendar.json", service._state_file]:
            assert file.stat().st_mode & 0o777 == 0o600
        assert list(service._cache_dir.glob("*.tmp")) == []
    finally:
        os.umask(previous)


@pytest.mark.parametrize("kind", ["config", "directory", "ancestor", "cache", "broken"])
def test_rejects_symlink_sensitive_paths(tmp_path, kind):
    target = tmp_path / "target"
    target.mkdir()
    outside = target / "file"
    outside.write_text("unchanged")
    link = tmp_path / "link"
    if kind == "config":
        link.symlink_to(outside)
        def operation():
            return Config.load(link)
    elif kind == "directory":
        link.symlink_to(target, target_is_directory=True)
        def operation():
            return private_dir(link)
    elif kind == "ancestor":
        link.symlink_to(target, target_is_directory=True)
        def operation():
            return private_open(link / "file")
    elif kind == "broken":
        link.symlink_to(tmp_path / "missing")
        def operation():
            return private_open(link)
    else:
        (target / "cached").symlink_to(outside)
        def operation():
            return private_dir(target)
    with pytest.raises(StorageSecurityError, match="symlink"):
        operation()
    assert outside.read_text() == "unchanged"


def test_rejects_hardlinked_file(tmp_path):
    original = tmp_path / "original"
    original.write_text("unchanged")
    link = tmp_path / "link"
    os.link(original, link)
    with pytest.raises(StorageSecurityError, match="hard-linked"):
        private_open(link)
    assert original.read_text() == "unchanged"


@pytest.mark.skipif(os.name != "posix", reason="POSIX umask")
def test_cli_startup_installs_policy_and_umask_for_dependency_writes(tmp_path):
    config = Config(config_file=tmp_path / "config.toml", session_dir=str(tmp_path / "session"),
                    cache_dir=str(tmp_path / "cache"))
    selected = UnavailableKeyring()
    import keyring

    previous_backend = keyring.core._keyring_backend
    previous_mask = os.umask(0)
    try:
        with patch("icloud_cli.main.Config.load", return_value=config), patch(
            "icloud_cli.credentials.select_secure_backend", return_value=selected
        ) as selector:
            result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code == 0, result.output
        selector.assert_called_once_with()
        assert keyring.core._keyring_backend is selected
        # Simulate dependency writes: CLI deliberately leaves the process mask set.
        dependency_file = Path(config.session_dir) / "dependency.session"
        dependency_file.write_text("fake cookie")
        assert dependency_file.stat().st_mode & 0o777 == 0o600
    finally:
        os.umask(previous_mask)
        keyring.core._keyring_backend = previous_backend


def test_cli_credential_operation_without_secure_backend(tmp_path):
    config = Config(apple_id="fake@example.test", config_file=tmp_path / "config.toml",
                    session_dir=str(tmp_path / "session"), cache_dir=str(tmp_path / "cache"))
    import keyring

    previous = keyring.core._keyring_backend
    previous_mask = os.umask(0o077)
    try:
        with patch("icloud_cli.main.Config.load", return_value=config), patch(
            "icloud_cli.credentials.select_secure_backend", return_value=UnavailableKeyring()
        ):
            result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code != 0
        assert "Secure system keyring unavailable" in result.output
        assert "Plaintext" in result.output
    finally:
        os.umask(previous_mask)
        keyring.core._keyring_backend = previous


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_default_app_roots_hardened_but_not_xdg_parents(tmp_path):
    xdg_config, xdg_data = tmp_path / "xdg-config", tmp_path / "xdg-data"
    for directory in [xdg_config, xdg_data]:
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)
    app_config, app_data = xdg_config / "icloud-cli", xdg_data / "icloud-cli"
    for directory in [app_config, app_data]:
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)
    config = Config(config_file=app_config / "config.toml",
                    session_dir=str(app_config / "session"), cache_dir=str(app_data / "cache"))
    with patch("icloud_cli.config.DEFAULT_CONFIG_DIR", app_config), patch(
        "icloud_cli.config.DEFAULT_DATA_DIR", app_data
    ), patch("icloud_cli.config.DEFAULT_CACHE_DIR", app_data / "cache"):
        config.ensure_dirs()
        config.save()
    for directory in [app_config, app_data]:
        assert directory.stat().st_mode & 0o777 == 0o700
    for directory in [xdg_config, xdg_data]:
        assert directory.stat().st_mode & 0o777 == 0o755


def test_logout_retains_sync_cache(tmp_path):
    config = Config(apple_id="fake@example.test", config_file=tmp_path / "config.toml",
                    session_dir=str(tmp_path / "session"), cache_dir=str(tmp_path / "cache"))
    config.ensure_dirs()
    cookie = Path(config.session_dir) / "cookie"
    cookie.write_text("fake cookie")
    cached = Path(config.cache_dir) / "calendar.json"
    _save_cache(cached, [{"title": "fake event"}])
    with patch("icloud_cli.auth.keyring") as keyring_api:
        AuthManager(config).logout()
    assert not cookie.exists()
    assert cached.exists()
    assert keyring_api.delete_password.call_count == 2


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_restore_session_hardens_existing_files_before_dependency_use(tmp_path):
    config = Config(apple_id="fake@example.test", config_file=tmp_path / "config.toml",
                    session_dir=str(tmp_path / "session"), cache_dir=str(tmp_path / "cache"))
    session_dir = Path(config.session_dir)
    session_dir.mkdir(mode=0o755)
    cookie = session_dir / "cookie"
    cookie.write_text("fake cookie")
    cookie.chmod(0o644)

    def make_api(**kwargs):
        assert kwargs["cookie_directory"] == str(session_dir)
        assert cookie.stat().st_mode & 0o777 == 0o600
        assert session_dir.stat().st_mode & 0o777 == 0o700
        return MagicMock(requires_2fa=False, requires_2sa=False)

    with patch("icloud_cli.auth.keyring") as keyring_api, patch(
        "icloud_cli.auth.PyiCloudService", side_effect=make_api
    ) as service:
        keyring_api.get_password.return_value = "fake password"
        AuthManager(config)._get_session()
    service.assert_called_once()
