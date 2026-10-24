"""Explicit system-keyring selection; never use plugin discovery or a chainer."""

from __future__ import annotations

import sys
from importlib import import_module

import click
from keyring.backend import KeyringBackend

SECURE_BACKENDS = {
    "linux": ("keyring.backends.SecretService", "Keyring"),
    "darwin": ("keyring.backends.macOS", "Keyring"),
    "win32": ("keyring.backends.Windows", "WinVaultKeyring"),
}
KEYRING_HELP = (
    "Secure system keyring unavailable or locked. On Linux, install SecretStorage "
    "and start/unlock a Secret Service (such as GNOME Keyring) on your user D-Bus "
    "session; on macOS unlock Keychain; on Windows enable Credential Manager. "
    "Headless jobs need access to that same unlocked user store. "
    "Plaintext, keyrings.alt, and chained fallback stores are not supported."
)


class SecureKeyringError(click.ClickException):
    """Actionable credential operation failure without exposing secrets."""


class UnavailableKeyring(KeyringBackend):
    """Fail closed while allowing commands which don't need credentials."""

    priority = 1

    def get_password(self, service, username):
        raise SecureKeyringError(KEYRING_HELP)

    def set_password(self, service, username, password):
        raise SecureKeyringError(KEYRING_HELP)

    def delete_password(self, service, username):
        raise SecureKeyringError(KEYRING_HELP)


def select_secure_backend() -> KeyringBackend:
    """Check only built-in platform support, without reading any credentials.

    Deliberately ignore PYTHON_KEYRING_BACKEND, keyringrc.cfg, entry points,
    previously selected backends, and priority-based plugin/chainer selection.
    """
    spec = SECURE_BACKENDS.get(sys.platform)
    if spec is not None:
        try:
            module, name = spec
            backend = getattr(import_module(module), name)()
            if backend.priority > 0:
                return backend
        except Exception:
            # Missing native dependencies or unavailable user D-Bus, for example.
            pass
    return UnavailableKeyring()


def configure_secure_keyring(keyring_api) -> None:
    """Install exactly one approved store (or the fail-closed sentinel)."""
    keyring_api.set_keyring(select_secure_backend())
