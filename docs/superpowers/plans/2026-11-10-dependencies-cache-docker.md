# Dependencies, Cache, and Docker Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or superpowers:executing-plans. Track completed steps here; do not commit or create branches.

**Goal:** Implement the approved dependency updates, selectable Redis/Valkey, and opt-in Docker management.

**Architecture:** Retain the Bash installer/CLI and PHP route authorization. Add one root-owned Python stdlib Docker helper in the signed panel archive; Docker operations execute against fixed rootful or site-user sockets. Independent frontend, cache/installer, and Docker-helper tasks can run concurrently; integrate PHP routes and CLI plumbing afterward.

**Tech Stack:** Bash, PHP, Python 3 standard library, npm, Docker Engine, systemd.

**Spec:** `docs/superpowers/specs/2026-11-09-dependencies-cache-docker-design.md` (approved).

## Global Constraints

- Work in the supplied checkout; no new branches, commits, releases, or deployments.
- Docker opt-in default is false; legacy cache default remains Redis.
- Flags: `--cache-engine redis|valkey|none`, `--with-docker`, `--no-docker`; preserve `--no-redis`.
- No development-host provisioning, downloaded root convenience scripts, or public Docker sockets.
- Never expose rootful management to non-admins or through the generic CLI API.
- Preserve existing backups; new backup backends are outside this change.

## Review Focus

- Piped scripts must prompt via a controlling terminal without consuming script stdin.
- Rootless startup after reboot and deletion must preserve no-login/SFTP restrictions.
- Invalid JSON, unknown Docker flags, socket mounts, symlinks, and cross-site IDs fail closed.
- Environment secrets must stay out of argv, errors, status responses, and operation logs.
- Mocked installer tests do not certify real OS/package/rootless runtime integration.

### Task 1: Dependency migrations

**Files:** `panel-app/package*.json`, `panel-app/build/*`, `panel-app/resources/css/tailwind.css`, `panel-app/tailwind.config.js`, affected editor/chart views, generated `panel-app/public/assets/*`, `.github/workflows/*`, `tests/unit/frontend_dependencies_test.mjs`.

- [ ] Verify npm latest stable tags and upstream licensing/API changes.
- [ ] Write/run a failing build/editor contract, migrate Tailwind and CodeMirror, update compatible dependencies, rebuild assets.
- [ ] Audit dependencies, check self-hosted editor features, and verify reproducible builds.
- [ ] Verify pinned workflow action SHAs and choose supported Node LTS. Report blockers instead of silently accepting licensing changes.

### Task 2: Cache selection and installer options

**Files:** `install.sh`, cache-related sections of `aidipanel`, existing service/status PHP files, new shell contract tests.

- [ ] Add failing executable tests for flags/conflicts, unattended defaults, dry-run, legacy config, engine paths, and fail-closed ACL behavior.
- [ ] Implement interactive optional-component selection and signed-source Docker/cache provisioning; persist selections.
- [ ] Resolve cache service/config/account/CLI centrally and update all Redis paths/callers without duplicating engine implementations.
- [ ] Update service PHP status to use the persisted engine; verify related existing tests.

**Interfaces:** Persist `CACHE_ENGINE=redis|valkey|none`, `INSTALL_DOCKER=true|false`, preserve `INSTALL_REDIS` compatibility. Docker helper installation is automatic through the existing signed panel archive; no separate unsigned script.

### Task 3: Restricted Docker backend

**Files:** create `panel-app/bin/docker-manager.py`, `tests/unit/docker_manager_test.py`.

**Interfaces:** `python3 /opt/aidipanel/bin/docker-manager.py ACTION --scope root|site [--domain DOMAIN --user USER --home HOME] [--purge]`. Actions: `status,list,create,start,stop,restart,remove,logs,enable,disable`. Site identity arguments are supplied only by the root CLI's authoritative resolver. Root enable/disable is not exposed. Structured JSON stdin carries create specifications or `{"id":"CONTAINER_ID"}`. Output is sanitized JSON; failures exit nonzero with a safe error.

Create fields: `name`, `image`, `environment` object, `ports` array of `{host,container}`, `volumes` array of `{source,target,readonly}`, `cpus`, `memory_mb`, `pids_limit`. Defaults: 1 CPU, 512 MiB, 128 PIDs. Listing returns `{available,enabled,containers}`; each container has `id,name,image,state,status,ports`; logs returns `{logs}`. Mutation responses include `success`.

- [ ] Write/run failing validation, command/daemon-scope, redaction, lifecycle, mount, port, and resource tests with external effects mocked.
- [ ] Implement fixed Docker sockets, managed-container identity checks, bounded commands/logs, finite limits, loopback ports, and safe local mounts.
- [ ] Implement site-user systemd provisioning/teardown without changing login shells; verify subordinate-ID overlaps and fail clearly on missing cgroup/AppArmor/userns prerequisites.
- [ ] Verify Python tests without Docker installation or a live daemon.

### Task 4: CLI and web integration

**Files:** Docker-only sections of `aidipanel`, wrapper allowlist in `install.sh`, `panel-app/public/index.php`, `panel-app/app/Core/RoutePolicy.php`, `panel-app/app/Controllers/DockerController.php`, site controller/detail, shared Docker view, layout navigation, generic CLI API policy, PHP/shell regression tests.

- [ ] Add failing route/role/CLI tests for root admin, site assignment, administrator-only provisioning, invalid payloads, and generic API denial.
- [ ] Add fixed `docker:*` CLI dispatchers; derive user/home from a validated domain rather than trusting web-supplied identity.
- [ ] Authorize server-side routes and expose admin rootful and site rootless controls using shared forms; redact submitted environment values and unlock sessions for long operations.
- [ ] Stop site Docker before site deletion/purge, preserving ordinary keep-home data and unrelated containers.
- [ ] Add Python checks to CI and update installation, CLI, security, backup limitations, troubleshooting, and uninstall documentation.

### Task 5: Integrated verification and review

- [ ] Run Bash syntax/ShellCheck, PHP lint, all shell/PHP/Python contracts, npm audit, and frontend builds.
- [ ] Review the integrated diff for authorization, secret leakage, dependency licensing, release packaging, and opt-out behavior; repair findings with regression checks.
- [ ] Report exact verified checks and outstanding real-VM integration gaps; leave changes uncommitted.

## Execution Notes

- User approved the design and requested execution in the supplied checkout.
- Dependencies migrated to Tailwind 4 and CodeMirror 6. ApexCharts remains pinned
  to MIT 4.7.0 because current 8.8.1 requires OEM redistribution licensing.
- Docker helper and parent integration checks reached 46 passing Python tests.
- Full shell/PHP verification found the expected stale CI action-pin contract;
  its immutable SHAs must be updated along with the workflow.
- Prior security review found two remaining lifecycle defects: jailed homes need
  a writable user-service configuration hierarchy, and confirmed purge must stop
  the lingering user manager and propagate account-deletion failures.
- User requested 6.1 Terra at medium effort for remaining implementation and
  6 Luna at xhigh for an independent full-change review. Earlier workers are
  terminal; do not restart them or redo completed migrations.
- Temporary verification tools: `/tmp/aidipanel-tools.u2GPkN/extracted/usr/bin/shellcheck`
  and `/tmp/aidipanel-tools.u2GPkN/extracted/usr/lib/php/20230831/pdo_sqlite.so`.
- Disposable-VM fresh-install, reboot, actual daemon/image, and cgroup enforcement
  tests remain unverified. No host services were installed or started.
- Terra completed lifecycle and CI fixes; independent checks passed 60 shell/PHP
  contracts, seven frontend tests on Node 24 and 26, zero npm audit advisories,
  and identical 133-file asset builds. Only ApexCharts remains outdated by design.
- Luna's full-change review identified same-UID Docker API control, mutable bind
  mount races, same-user service restart after normal disable, and fail-open
  teardown of an unrecorded runtime. The teardown defect is fixed and Python
  verification now passes 52 tests, including new socket/service-file regressions.
- The approved daemon and PHP worker share the site's Linux identity. Direct
  daemon access and same-user service restart cannot be turned into a hard
  security boundary merely by adding panel validation or disabling lingering.
  Strong enforcement would require a separate runtime identity and a safer
  storage interface, such as Docker-managed volumes rather than mutable bind
  sources. This would change the approved design and needs a user decision.
- November 10, 2026: user approved the separate per-site runtime identity and
  Docker-managed site volumes. The preceding decision is resolved; do not retain
  same-UID daemons or mutable site bind mounts as an implicit fallback.
- Security revision tasks: isolate daemon home/socket under a dedicated no-login
  identity; validate root-owned ownership records; scope and verify named volumes;
  stop the runtime manager and lingering on ordinary disable; preserve data until
  confirmed purge; reject unverified legacy runtimes. Update UI/docs and add
  regressions, then independently review and rerun integration contracts.
- Revised backend now isolates the daemon account/home/socket and verifies scoped
  named volumes. Terra adapted lifecycle tests; the unrecorded subordinate-ID
  allocation adoption regression was reproduced and fixed before user creation.
- Luna's revised review found enable-versus-site-deletion serialization, failed
  create anonymous-volume leakage, and offline unit enablement persistence.
  Reproduced each finding before fixes: CLI Docker site actions now acquire the
  existing per-site deletion lock before identity resolution; create rollback
  removes anonymous volumes with the new container; offline disable uses
  `SYSTEMD_OFFLINE=1` and `--no-reload` to remove enablement without starting a bus.
- Python verification reached 73 passing tests, including an actual systemctl
  offline-client check confined to temporary config/unit paths (no services run).
  Luna's scoped independent re-review found no remaining concrete P1/P2 issues
  in the deletion lock, anonymous-volume cleanup, or offline disable fixes.
- Final parent verification passed 73 Python tests, all 60 shell/PHP contract
  files, 65 PHP syntax checks, Bash syntax, ShellCheck, and `git diff --check`.
  PHP contracts used the temporary PDO SQLite extension; the review environment's
  missing driver is not a failing application regression. Frontend build and
  seven tests passed on Node 26.13.0, with zero npm audit vulnerabilities.
  All work remains uncommitted. Disposable-VM installation/reboot, actual Docker
  image execution and cgroup enforcement, and Windows signing remain unverified.
- Subsequent authorized local QEMU/KVM integration used one vCPU, 1024 MiB RAM
  and a 30 GiB disk. Ubuntu 24.04 Valkey/Docker and Redis/no-Docker installs
  passed, including real rootless isolation, CPU/memory/PID enforcement, reboot,
  volume persistence, offline disable and site deletion/purge on the Docker run.
  See `docs/development/2026-11-10-vm-integration.md` for exact coverage and the
  local-source staging difference from public signed release downloads.
- VM testing exposed and fixed package-candidate SIGPIPE, recognition of Ubuntu's
  packaged rootlesskit AppArmor profile, and separate-UID Docker stdin ownership.
  Parent verification ran 75 Python tests (one root-only check skipped locally,
  separately passed in the guest) and ShellCheck. The public signed download
  path, cache-none profile, other operating systems and Windows signing remain
  unverified; no production deployment or commits occurred.
