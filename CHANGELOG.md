# Changelog

## [1.4.0] - 2026-11-10

### Added

- Initial-setup selection of Redis, Valkey, or no object cache, with consistent
  service status, Redis-compatible PHP support, and per-site ACL isolation.
- Optional Docker installation from the official signed package repository,
  including rootless prerequisites. Headless setup defaults to Redis and no
  Docker; explicit flags override interactive questions.
- Administrator rootful container management and assigned-site rootless
  management through the panel and CLI: create, list, start, stop, restart,
  remove, and bounded logs.
- Separate no-login runtime identities and private daemon sockets for site
  containers, scoped managed named volumes, finite resource limits, loopback
  ports, and safe enable/disable/site-deletion lifecycle handling.
- Automated security and dependency regressions, plus a documented real VM run
  for Ubuntu 24.04 Valkey/Docker and Redis/no-Docker profiles.

### Changed

- Upgraded eligible frontend packages, migrated to Tailwind 4 and CodeMirror 6,
  rebuilt self-hosted assets, and bundled third-party license notices.
- Updated immutable CI action pins and the Node build runtime; pinned WP-CLI to
  a verified stable release. ApexCharts remains at MIT-licensed 4.7.0 because
  later releases introduce additional redistribution licensing requirements.
- Clarified setup options, container permissions, backup exclusions, and
  supported signed host-package sources in the README and documentation.

### Fixed

- Avoided package-candidate parser SIGPIPE failures under Bash `pipefail`.
- Recognized Ubuntu's packaged rootlesskit AppArmor profile and fixed
  cross-UID Docker environment-input pipe ownership.
- Serialized site deletion and Docker management; removed anonymous volumes
  when rolling back rejected creates; and disabled offline user-service
  enablement without starting a user manager.

### Upgrade Notes

- Publish the matching signed installer, CLI, and panel assets together using
  the maintainer procedure in `SECURITY.md`. Existing installations upgrade via
  `sudo aidipanel self:update` after publication; do not rerun `install.sh`.
- The upgrade does not automatically install Docker, migrate a live cache engine,
  or adopt legacy same-user Docker runtimes. Preserve existing data and resolve
  unverified runtime records administratively before enabling revised support.
- Site Docker mounts accept `{name,target,readonly}` managed-volume entries;
  site host bind mounts are not supported. Administrator rootful bind mounts
  remain restricted to the managed Docker data directory.
- Backups remain full archives, not incremental backups. Arbitrary S3 endpoints,
  SFTP/SSH destinations, and automatic Docker-volume backups are not added.
- Public signed-release download verification for this version, the cache-none
  install profile, other operating systems, and Windows release-signing execution
  were not covered by the local VM run. See the integration report for details.
