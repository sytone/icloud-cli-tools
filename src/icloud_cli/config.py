"""Configuration management for icloud-cli.

Config file: ~/.config/icloud-cli/config.toml
Cache dir:   ~/.local/share/icloud-cli/cache/
Session dir: ~/.config/icloud-cli/session/
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import toml

from icloud_cli.security import ensure_parent, private_dir, private_file, private_open

# XDG-compliant default paths
DEFAULT_CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "icloud-cli"
DEFAULT_DATA_DIR = (
    Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "icloud-cli"
)
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.toml"
DEFAULT_SESSION_DIR = DEFAULT_CONFIG_DIR / "session"
DEFAULT_CACHE_DIR = DEFAULT_DATA_DIR / "cache"


@dataclass
class Config:
    """Application configuration."""

    # General
    default_format: str = "table"
    verbose: bool = False

    # Auth
    apple_id: str = ""
    session_dir: str = str(DEFAULT_SESSION_DIR)

    # Notes (IMAP)
    imap_password_in_keyring: bool = False

    # Sync
    sync_interval_minutes: int = 15
    cache_dir: str = str(DEFAULT_CACHE_DIR)

    # Calendar
    default_calendar: str = ""

    # Reminders
    default_reminder_list: str = ""

    # Paths (not serialized)
    config_file: Path = field(default=DEFAULT_CONFIG_FILE, repr=False)

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load config from TOML file, falling back to defaults."""
        path = config_path or DEFAULT_CONFIG_FILE
        config = cls(config_file=path)

        private_file(path)
        if path.exists():
            data = toml.load(path)
            general = data.get("general", {})
            auth = data.get("auth", {})
            notes = data.get("notes", {})
            sync = data.get("sync", {})
            calendar = data.get("calendar", {})
            reminders = data.get("reminders", {})

            config.default_format = general.get("default_format", config.default_format)
            config.verbose = general.get("verbose", config.verbose)
            config.apple_id = auth.get("apple_id", config.apple_id)
            config.session_dir = auth.get("session_dir", config.session_dir)
            config.imap_password_in_keyring = notes.get(
                "imap_password_in_keyring", config.imap_password_in_keyring
            )
            config.sync_interval_minutes = sync.get(
                "sync_interval_minutes", config.sync_interval_minutes
            )
            config.cache_dir = sync.get("cache_dir", config.cache_dir)
            config.default_calendar = calendar.get("default_calendar", config.default_calendar)
            config.default_reminder_list = reminders.get(
                "default_reminder_list", config.default_reminder_list
            )

        return config

    def save(self) -> None:
        """Save config to TOML file."""
        self._ensure_config_dir()

        data = {
            "general": {
                "default_format": self.default_format,
                "verbose": self.verbose,
            },
            "auth": {
                "apple_id": self.apple_id,
                "session_dir": self.session_dir,
            },
            "notes": {
                "imap_password_in_keyring": self.imap_password_in_keyring,
            },
            "sync": {
                "sync_interval_minutes": self.sync_interval_minutes,
                "cache_dir": self.cache_dir,
            },
            "calendar": {
                "default_calendar": self.default_calendar,
            },
            "reminders": {
                "default_reminder_list": self.default_reminder_list,
            },
        }

        with private_open(self.config_file) as f:
            toml.dump(data, f)

    def ensure_dirs(self) -> None:
        """Create required directories."""
        private_dir(Path(self.session_dir))
        private_dir(Path(self.cache_dir))
        private_file(self.config_file)
        self._ensure_config_dir()
        if Path(self.cache_dir) == DEFAULT_CACHE_DIR:
            private_dir(DEFAULT_DATA_DIR)

    def _ensure_config_dir(self) -> None:
        # A custom --config may live in a shared directory; never chmod that
        # directory or its unrelated contents. Only the default app dir is ours.
        if self.config_file.parent == DEFAULT_CONFIG_DIR:
            private_dir(DEFAULT_CONFIG_DIR)
        else:
            ensure_parent(self.config_file.parent)
