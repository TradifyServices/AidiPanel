# Testing

This page describes how to verify AidiPanel on a throwaway server before relying on a change.

## Linting (no server required)

The installer and CLI are Bash; the panel is PHP. Static checks:

```bash
# Bash syntax
bash -n install.sh
bash -n aidipanel
bash -n panel-app/deploy-panel.sh

# Installer unit tests
bash tests/unit/installer_archive_test.sh

# Docker helper contracts (no Docker daemon or host provisioning)
python3 -m unittest discover -s tests/unit -p '*_test.py'

# Bash lint (optional)
shellcheck -S warning install.sh aidipanel

# PHP syntax (requires php-cli)
find panel-app -name '*.php' -print0 | xargs -0 -n1 php -l
```

The same checks run in CI on every push and pull request.

## Manual verification on a fresh VPS

Use a disposable Ubuntu 24.04 (or Debian 12) server — never one holding important data.

```bash
# 1. Run the installer
sudo bash install.sh --port 8443 --db-engine mariadb123

# 2. Open the panel and log in with the password printed at the end
#    https://<server-ip>:8443
```

### Smoke checklist

- Services active: `nginx`, the default `php8.5-fpm`, `aidipanel-fpm`, `mariadb`/`mysql`, `redis-server`.
- Add a plain PHP site; confirm it serves over HTTPS.
- Add a WordPress site; confirm it serves.
- Enable FastCGI cache; confirm `X-FastCGI-Cache: HIT` on the second request.
- Purge cache for the domain.
- Install SSL for a domain whose DNS points at the server.
- Edit a vhost with a valid config (reload succeeds) and an invalid one (automatic rollback).
- Create a database, back it up, delete it.
- Confirm a site's PHP runs as its own user and cannot read another site's files.
- Exercise Redis, Valkey, and no-cache selections on separate fresh machines.
- Install with `--no-docker` and confirm no Docker repository/package/service is created.
- Install with `--with-docker`; enable a site's rootless runtime, create a test
  container, verify CPU/memory/PID limits and localhost-only published ports.
- Confirm an assigned client cannot access rootful Docker or another site's IDs.
- Confirm the runtime UID differs from the PHP/SFTP UID, and site processes
  cannot connect to the runtime socket or traverse its private home.
- Create/reuse a named site volume and confirm host bind sources and unverified
  volume labels/driver options are refused. Declare named volumes for image
  `VOLUME` paths; unscoped implicit anonymous volumes are not accepted.
- Disable without purge, verify lingering and the runtime manager stop, then
  reenable and confirm persisted volume data remains. Check legacy same-UID
  records are refused without modifying the old daemon or data.
- Reboot and verify rootless user services restart without enabling SSH login.
- Delete/purge a test site and confirm its runtime stops while unrelated rootful
  containers and ordinary keep-home data survive.

## Notes

- For SSL tests without a real domain, a wildcard DNS service that maps a hostname to the server IP is convenient, together with Let's Encrypt **staging** to avoid rate limits.
- `install.sh` is a one-shot installer by design: re-running it on an already-installed server is refused safely (non-zero exit), and the system keeps working.
