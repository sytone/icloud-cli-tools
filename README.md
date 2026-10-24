# ☁️ icloud-cli-tools

> Access your iCloud **Calendar**, **Reminders**, **Notes**, and **Find My** devices from the Linux terminal.

[![CI](https://github.com/alan13367/icloud-cli-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/alan13367/icloud-cli-tools/actions)
[![PyPI](https://img.shields.io/pypi/v/icloud-cli-tools.svg)](https://pypi.org/project/icloud-cli-tools/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-green.svg)](https://python.org)

## Features

- 📅 **Calendar** — List, create, and delete events with natural date parsing
- ✅ **Reminders** — Manage reminders across lists, mark complete, set priorities
- 📝 **Notes** — Read, create, and search your iCloud Notes
- 📍 **Find My** — Locate devices, play sounds, activate Lost Mode
- 🔄 **Background Sync** — Daemon with systemd integration for periodic caching
- 🔐 **Secure Auth** — 2FA support, OS keyring for credentials, session caching
- 🎨 **Beautiful Output** — Rich tables, JSON, and plain text formats

## Installation

```bash
# From PyPI (recommended)
pip install icloud-cli-tools
```

Or install from source:

```bash
# Clone the repo
git clone https://github.com/alan13367/icloud-cli-tools.git
cd icloud-cli-tools

# Set up a virtual environment (recommended, required on modern Debian/Ubuntu)
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

> **Tip:** To use `icloud-cli` without activating the venv every time, add an alias:
> ```bash
> echo 'alias icloud-cli="~/icloud-cli-tools/.venv/bin/icloud-cli"' >> ~/.bashrc
> source ~/.bashrc
> ```

## Quick Start

```bash
# 1. Login to your iCloud account
icloud-cli login

# 2. Set up Notes access (requires app-specific password)
icloud-cli notes setup-imap

# 3. Start using it!
icloud-cli calendar list
icloud-cli reminders list
icloud-cli notes list
icloud-cli findmy list
```

## Usage

### Authentication

```bash
icloud-cli login          # Interactive login with 2FA
icloud-cli logout         # Clear all stored credentials
icloud-cli status         # Check auth status
```

### Calendar

```bash
icloud-cli calendar list                    # Events for next 7 days
icloud-cli calendar list --from today --to tomorrow
icloud-cli calendar show <event-id>
icloud-cli calendar add -t "Meeting" -s "2025-06-15 10:00" -e "2025-06-15 11:00"
icloud-cli calendar delete <event-id>
```

### Reminders

```bash
icloud-cli reminders list                   # All active reminders
icloud-cli reminders list --list "Shopping" --completed
icloud-cli reminders add -t "Buy milk" -d "2025-06-15" -l "Shopping"   # bare date -> all-day reminder
icloud-cli reminders add -t "Standup" -d "2025-06-15 09:30"            # date + time -> timed reminder
icloud-cli reminders complete <reminder-id>
icloud-cli reminders delete <reminder-id>
```

### Notes

```bash
icloud-cli notes list
icloud-cli notes show <note-id>
icloud-cli notes add -t "My Note" -b "Note content here"
icloud-cli notes search "keyword"
```

> **Note:** Notes access requires an app-specific password. Generate one at
> [appleid.apple.com](https://appleid.apple.com/account/manage) →
> *Sign In & Security* → *App-Specific Passwords*.

### Find My

```bash
icloud-cli findmy list                      # All devices with status
icloud-cli findmy locate "iPhone"           # GPS coordinates + Maps link
icloud-cli findmy play-sound "iPhone"       # Ring your device
icloud-cli findmy lost-mode "iPhone" -p "+1234567890" -m "Please return"
```

### Sync & Daemon

```bash
icloud-cli sync                # One-shot sync to local cache
icloud-cli daemon start        # Start background sync (every 15 min)
icloud-cli daemon stop         # Stop daemon
icloud-cli daemon status       # Check daemon status
```

#### Systemd Integration (Linux)

```bash
# Install the service
cp systemd/icloud-cli-sync.service ~/.config/systemd/user/
systemctl --user enable icloud-cli-sync
systemctl --user start icloud-cli-sync
```

### Output Formats

```bash
icloud-cli calendar list -f table   # Rich formatted table (default)
icloud-cli calendar list -f json    # Machine-readable JSON
icloud-cli calendar list -f plain   # Tab-separated for scripting
```

## Configuration

Config file: `~/.config/icloud-cli/config.toml`

```toml
[general]
default_format = "table"
verbose = false

[auth]
apple_id = "your@icloud.com"

[sync]
sync_interval_minutes = 15

[calendar]
default_calendar = "Personal"

[reminders]
default_reminder_list = "Reminders"
```

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/
```

## ⚠️ Disclaimer

This project uses **unofficial/private iCloud web APIs** via the
[pyicloud](https://github.com/picklepete/pyicloud) library. Apple may change
these APIs at any time without notice, which could break functionality. This
tool is not affiliated with or endorsed by Apple Inc.

## License

[MIT](LICENSE)

## Security and local state

- **Web API login uses your real Apple ID password and Apple's 2FA**, not an
  app-specific password. Notes IMAP uses a separate app-specific password.
  Notes connections verify the server certificate chain and hostname using the
  platform's default TLS trust store; there is no insecure TLS fallback.
- At application startup, credential storage is explicitly restricted to the
  built-in `keyring` Secret Service backend on Linux, macOS Keychain, or Windows
  Credential Manager. Backend discovery, `PYTHON_KEYRING_BACKEND`, keyring config
  overrides, third-party plugins (including `keyrings.alt`), and chained fallback
  stores are deliberately not used. Selection checks availability only; it does
  not read passwords. Credential commands can subsequently access the selected
  system store and may trigger its unlock prompt.
- **Headless operation fails closed** if the secure store is missing, unavailable,
  or locked: it never silently switches to plaintext storage. On Linux, install
  SecretStorage and run/unlock a Secret Service such as GNOME Keyring in the
  same user's D-Bus session. Services and cron jobs need access to that unlocked
  user store too. On macOS unlock Keychain; on Windows ensure Credential Manager
  is available. Commands that do not need credentials can still run without a
  working store. No plaintext workaround is supported.
- On POSIX systems the CLI sets a process-wide `umask 077`, including for
  dependency-created session/cookie files. Dedicated app configuration, session,
  and cache directories are restricted to `0700`; existing config, session, and
  cache files are tightened to `0600`, and app-written files are created with
  `0600`. Custom session/cache directories must be dedicated to this app: their
  contents are recursively hardened. A custom `--config` file is hardened but
  its existing parent directory is not, because it may hold unrelated files.
  Existing XDG/home ancestors are not chmod'ed. Sensitive paths containing
  symlinks, hard-linked files, or special files are rejected. Use real directories
  instead of symlinks for these paths.
- These modes are not encryption. On Windows, POSIX modes do not provide the
  same protection: use private user-profile directories with appropriate Windows
  ACLs. Protect backups and local disks. Path checks reduce link hazards but do
  not guarantee safety against concurrent path replacement by another process
  running as your user or against a hostile/shared parent directory.
- **Logout is not a cache wipe.** It removes stored passwords and session cookies
  when the keyring is accessible, but retains configuration and synced data
  (including reminder state, calendar/Notes metadata and device locations).
  Stop any running sync process and remove the configured cache directory
  separately if you need to remove those residual records. Logout cannot revoke
  copies in backups, securely erase disk blocks, or remotely revoke Apple's
  sessions/app-specific passwords.
- These hardening changes are maintained in the
  [sytone fork](https://github.com/sytone/icloud-cli-tools). A PyPI or upstream
  reinstall may not include local patches. Keep your patched checkout/virtualenv,
  review diffs when updating, and rerun the regression suite after dependency or
  upstream upgrades; do not assume local changes survive replacement installs.
