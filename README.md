# AidiPanel

> Nginx server control panel with built-in FastCGI Cache — lightweight by design.

AidiPanel is a server control panel for Ubuntu/Debian VPS, built on Nginx + FastCGI Cache + PHP-FPM + MariaDB/MySQL, with optional Redis or Valkey object caching and Docker container management. It installs the stack and a web panel in one command, and focuses on a small, fast footprint: page caching lives inside Nginx itself, and each site runs under its own isolated Linux user.

**Live demo (read-only):** <https://demo.aidipanel.com> — explore the panel before installing.

## v1.4.0 Highlights

- Choose **Redis**, **Valkey**, or no object cache during initial setup.
- Optionally install Docker and manage administrator rootful or site-scoped
  rootless containers from the panel and CLI.
- Site Docker daemons use dedicated runtime users, private sockets, managed named
  volumes, loopback-only published ports, and finite CPU/memory/PID limits.
- Updated frontend dependencies, Tailwind 4 and CodeMirror 6, with self-hosted
  assets and bundled license notices. ApexCharts stays on MIT-licensed 4.7.0;
  newer releases require additional redistribution licensing.

Fresh-install and Docker lifecycle checks passed on an Ubuntu 24.04 VM with
1 vCPU, 1 GiB RAM and a 30 GiB disk. See the [integration report](docs/development/2026-11-10-vm-integration.md)
for tested profiles and remaining coverage, and the [changelog](CHANGELOG.md)
for upgrade notes. This test configuration is not a production sizing guarantee.

## Install

Start with a fresh Ubuntu/Debian VPS and fully update the base system first:

```bash
sudo apt update
sudo apt upgrade -y
```

If the upgrade creates `/var/run/reboot-required`, run `sudo reboot`, reconnect,
and only then start the AidiPanel installer. The public download currently
installs **v1.3.3**, not the v1.4.0 code described on this branch. The v1.4.0
cache and Docker setup options require a signed v1.4.0 release; pushing this
branch does not publish one.

For the latest published release:

```bash
curl -fsSL https://get.aidipanel.com | sudo bash
```

The installer deploys the full stack and web panel. A random admin password is printed at the end and saved to `/opt/aidipanel/credentials.conf`.

### Verify before running (recommended)

`get.aidipanel.com` redirects to the latest release installer. The quick command
uses HTTPS to bootstrap the installer; once running, the installer verifies the
signed CLI and panel release before deploying them. For release authentication
before any script runs as root, download and verify all release metadata:

```bash
curl -fLO https://github.com/rezzaidr/AidiPanel/releases/latest/download/install-aidipanel.sh
curl -fLO https://github.com/rezzaidr/AidiPanel/releases/latest/download/SHA256SUMS
curl -fLO https://github.com/rezzaidr/AidiPanel/releases/latest/download/SHA256SUMS.sig
curl -fLO https://github.com/rezzaidr/AidiPanel/releases/latest/download/release-signing-public.pub

openssl pkey -pubin -in release-signing-public.pub -outform DER | sha256sum
openssl dgst -sha256 -verify release-signing-public.pub \
  -signature SHA256SUMS.sig SHA256SUMS
grep ' install-aidipanel.sh$' SHA256SUMS | sha256sum -c -
```

The public-key fingerprint must be
`63cd4bf5ed9f184c9042977cec91e25d0928cc361c4e54bfb496d31f74f4d901`. Confirm it
with the maintainers through an independently authenticated channel; the copy
downloaded from the same release is not an independent trust anchor.
Continue only when OpenSSL prints `Verified OK` and the checksum prints
`install-aidipanel.sh: OK`.

After verifying the fingerprint, signature, and checksum, run:

```bash
sudo bash install-aidipanel.sh
```

Use a fresh, dedicated VPS: the installer provisions the system web/database stack and is not intended to adopt an existing production server.

## Stack

- **Nginx** (official stable repository, with distro fallback) with FastCGI Cache
- **PHP-FPM** — 8.5 installed by default; 8.2, 8.3, 8.4 available on-demand, switchable per site
- **MariaDB** 12.3 LTS by default (MariaDB 11.8 / 11.4 / 10.11 or MySQL 9.7 / 8.4 / 8.0 selectable at install)
- **Redis or Valkey** for Redis-compatible object caching; selectable during setup
- **Docker** (optional) with administrator rootful and per-site rootless container management
- **Certbot** (Let's Encrypt) with automatic renewal
- **UFW** firewall + **Fail2ban**

## Features

- Site management for WordPress, PHP, Laravel, static sites, and reverse proxies
- File manager, per-site databases and phpMyAdmin, cron jobs, and PHP tuning
- Full site backups plus scheduled uploads to supported S3 providers
- Optional Docker containers with loopback ports, resource limits, and site-scoped rootless runtimes
- Opt-in jailed SFTP with password or SSH-key authentication
- Per-site Basic Auth, IP blocking, Cloudflare-only origin access, SSL controls, and cache controls
- Admin, manager, and client panel accounts with site assignment and optional two-factor authentication
- Service status, traffic metrics, cloud metadata, and read-only web-delivery diagnostics

## Site Isolation

Each site gets a **dedicated, no-login Linux user** and its **own PHP-FPM pool** running as that user:

```
/home/<site-user>/htdocs/<domain>
```

If one site's PHP is compromised, the process runs only as that site's user and cannot read other sites' files. This is per-user process/file isolation — not container-level sandboxing. Login is disabled by default; jailed SFTP-only access can be enabled per site without enabling an interactive SSH shell.

Optional site containers run under a **different no-login runtime user**, not the
PHP/SFTP account. Site code cannot access that daemon's private home or socket;
management is mediated by the panel's authorized CLI. Site containers use managed
named volumes rather than host bind paths. Administrator rootful containers are
a separate privileged scope. See the [Docker guide](docs/docker.md).

## Backups

Site backups are full `.tar.gz` archives containing the webroot, database dumps,
and a manifest, with daily/weekly scheduling and rclone uploads to the supported
AWS S3, Wasabi, and DigitalOcean Spaces providers. They are **not incremental or
deduplicated**. Arbitrary S3-compatible endpoints, SFTP/SSH storage boxes,
configurable folder destinations, and an integrated restore workflow are not
implemented. Docker volumes and running-container consistency are not covered by
site backups; back up container application data separately.

## Supported OS

| OS | Versions |
|----|----------|
| Ubuntu | 22.04 LTS (jammy), 24.04 LTS (noble), 26.04 LTS (resolute) |
| Debian | 11 (bullseye), 12 (bookworm) |

Architecture: x86_64 and aarch64.

> On Ubuntu 26.04 only MariaDB 11.8 / 12.3 can install (MySQL and MariaDB 10.11 / 11.4 are upstream-blocked). Recommended: Ubuntu 24.04 LTS.

## Install Options

```
--port PORT           Panel HTTPS port (default: 8443)
--db-engine ENGINE    mariadb123 | mariadb118 | mariadb114 | mariadb1011 | mysql97 | mysql84 | mysql80
--db-root-pass PASS   Set DB root password non-interactively
--cache-engine ENGINE redis | valkey | none (default: redis without a terminal)
--no-redis            Alias for --cache-engine none
--with-docker         Install Docker Engine and rootless prerequisites
--no-docker           Skip Docker (default without a terminal)
--dry-run             Simulate without making changes
```

In v1.4.0, interactive setup asks about the cache engine and Docker unless their
flags were supplied. Once the signed v1.4.0 release is published, for an
unattended Valkey/Docker installation, download and verify its installer as
above, then run:

```bash
sudo bash install-aidipanel.sh --cache-engine valkey --with-docker
```

Existing installations should use `sudo aidipanel self:update` after the signed
v1.4.0 release is published. Do not rerun the one-shot installer to upgrade.
Updating the panel does not migrate Redis data to Valkey or install Docker on an
existing host automatically.

## CLI

```bash
aidipanel site:add    --domain example.com --user example --type php
aidipanel ssl:install --domain example.com --email admin@example.com
aidipanel cache:purge --domain example.com
aidipanel db:add      --name mydb --user myuser
aidipanel service:status
aidipanel docker:enable --domain example.com
aidipanel docker:list   --domain example.com
```

Docker commands require Docker to have been selected during setup. Rootless
enable/disable is administrator-only; site management follows panel assignments.

WordPress creation installs WordPress, its database, and its admin account in one transaction, so it requires the WordPress setup fields documented in [Sites](docs/sites.md). The default PHP version (8.5) is used when `--php` is omitted. See [docs/cli.md](docs/cli.md) for the full reference.

## Documentation

- [Installation](docs/installation.md)
- [Sites](docs/sites.md)
- [CLI reference](docs/cli.md)
- [Docker containers](docs/docker.md)
- [FastCGI Cache](docs/fastcgi-cache.md)
- [SSL / TLS](docs/ssl.md)
- [Security model](docs/security.md)
- [Security policy](SECURITY.md)
- [Architecture](docs/architecture.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Roadmap](docs/roadmap.md)
- [Uninstall](docs/uninstall.md)
- [Changelog](CHANGELOG.md)

## Support AidiPanel

AidiPanel is built and maintained independently.

If this project helps you manage servers more easily, save time, or learn server management with less confusion, consider supporting the development.

Your sponsorship helps fund VPS testing, documentation, security improvements, backup workflows, installer testing, and continued development.

[Become a Sponsor](https://github.com/sponsors/rezzaidr)

## License

Licensed under the MIT License — see [LICENSE](LICENSE).
