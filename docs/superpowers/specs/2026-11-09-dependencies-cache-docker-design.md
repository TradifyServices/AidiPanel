# Dependencies, selectable cache engine, and optional Docker

Date: 2026-11-09
Status: approved by the user; implementation in progress.

## Intent and agreed scope

Update AidiPanel's dependencies to current stable releases, offer Redis or Valkey
during installation, and add optional Docker installation and container management.
Keep the existing Bash CLI, PHP application, signed-release verification, local
frontend assets, and fail-closed permissions model.

The user approved administrator-only rootful Docker and site-scoped rootless
Docker. They explicitly require Docker to be an option during initial setup.
Backup capabilities were investigated and explained; replacing the backup engine
has not been requested or approved.

## Installation experience

- Offer an object-cache choice: Redis, Valkey, or neither.
- Offer `Install Docker?` during initial setup, defaulting to no.
- Add `--cache-engine redis|valkey|none`, `--with-docker`, and `--no-docker`.
- Preserve `--no-redis` as a compatibility alias for no object-cache engine.
  Reject conflicting selections instead of silently using argument order.
- Explicit flags bypass their corresponding questions. Prompt through the
  controlling terminal when available, including `curl | sudo bash` execution;
  never consume the piped installer script or block headless automation.
- Without a usable controlling terminal, retain Redis and skip Docker unless
  explicitly selected. Do not create an additional full-screen installer.
- Persist choices in root-owned panel configuration. Older installations without
  the new keys retain their existing Redis behavior and have Docker disabled.
- Show selected/installed components in help, progress, health checks, and the
  final summary. Existing `--dry-run` must not install packages or start daemons.
- Installation of Docker enables administrator rootful management and makes
  rootless provisioning available. Rootless daemons are created on demand per
  site, not eagerly for every Linux user.

Defaults above are implementation recommendations, not additional user decisions.

## Dependency updates

Inventory direct/transitive npm packages, frontend integrations, CI actions and
runtimes, pinned downloads such as phpMyAdmin/WP-CLI, and installer repositories.
Verify current stable releases against upstream primary sources at implementation
time rather than relying on the earlier conversation's version table.

Upgrade direct packages and regenerate the lockfile. Migrate the Tailwind build
and CodeMirror editor integration as necessary; preserve the existing editor
features and self-hosted assets. Check chart and QR-code API compatibility and
changed licensing before upgrading. Do not adopt prereleases or silently ship a
new license requirement that the project cannot satisfy.

Keep GitHub Actions pinned by verified immutable commit SHA, use a supported Node
LTS for CI, and rebuild all committed assets reproducibly. Fix actual discovered
vulnerabilities without running blind `npm audit fix --force`.

For host packages, use supported signed repositories and their current stable
releases. Do not run the installer against this development machine. Do not
silently migrate existing databases, remove selectable supported DB/PHP branches,
or interpret a dependency update as approval for production data migrations.
Report any unavailable latest release, compatibility blocker, or licensing blocker
explicitly instead of claiming all dependencies are current.

## Redis / Valkey integration

Persist a cache-engine identifier and resolve its package, service, CLI, config,
service account, and ACL file centrally. Keep existing public Redis-compatible
cache commands and WordPress settings working rather than duplicating the whole
cache implementation.

Apply engine selection consistently to installation, PHP extension requirements,
memory policy, loopback binding, persistence settings, health checks, service
controls, metrics, per-site ACL provisioning/removal, and uninstall documentation.
Retain fail-closed ACL initialization: a failed isolation setup must not leave an
unauthenticated cache service running. Never fall back to an unselected engine.

Check package/repository availability for the detected OS and architecture before
modifying the host. If a selected engine is not available from a supported signed
package source, reject the selection with actionable guidance. Do not introduce
unverified binaries or a source-build toolchain just to satisfy old distributions.
Fresh-install selection is in scope; automatic migration between live Redis and
Valkey instances or conversion of existing data is not.

## Docker installation and lifecycle

Install Docker Engine, CLI, and rootless prerequisites from verified signed
package sources when opted in. Do not execute downloaded convenience scripts as
root. Validate OS/architecture, user namespaces, subordinate UID/GID allocations,
user services, and required AppArmor/cgroup support. Unsupported selections fail
clearly rather than leaving a misleading successful installation.

Rootful Docker is system-managed and available only to panel administrators.
Rootless Docker runs a separate user daemon for each opted-in site under a
dedicated no-login runtime identity, distinct from the site's PHP/SFTP user.
Keep its private home outside the site home and its socket inaccessible to site
processes. Preserve the original site user's login/SFTP restrictions.
Use explicit user-daemon sockets and user-service lifecycle management; never let
request data select `DOCKER_HOST`, a remote daemon, another user's socket, or root.
Never add the panel or site users to the rootful `docker` group, expose a Docker
TCP API, or pass the rootful socket into a site container.

Provision a site's rootless runtime through an explicit administrator action.
Site creation is unchanged when Docker is absent. On site deletion, stop its
managed containers and rootless daemon before removing the site's identity.
Keep container data on ordinary keep-home deletion; explicit confirmed purge
removes managed site-owned runtime/data only. Preserve unrelated administrator
containers, unrelated users, and any pre-existing subordinate-ID allocations.

## Management and authorization

Add CLI commands through the existing privilege wrapper and add PHP controllers,
routes, and views using existing UI patterns:

- An administrator Docker page manages panel-created rootful containers.
- A site's Containers tab manages panel-created containers in that site's
  rootless daemon; access follows existing site assignments.
- Operations: list/create/start/stop/restart/remove containers and read bounded
  logs/status; creation accepts image, name, environment, ports, volumes, and
  resource limits. Pull an image when creating a container if needed.
- Administrators provision/disable rootless support for a site. Managers/clients
  cannot provision system prerequisites or select rootful execution.
- When Docker is absent, show an unavailable state; do not install packages as a
  side effect of visiting the page. Later administrator installation can use
  documented Docker installation instructions; a second installer UI is not
  required for this release.

Authorize every operation server-side using the route policy and trusted site
identity resolution. Recheck managed labels and daemon scope for object IDs;
labels alone do not substitute for daemon/user isolation. Restrict the web rootful
surface to managed containers, leaving unrelated containers untouched.

Pass structured create specifications through stdin, invoke Docker with argument
arrays, and validate image/name/IDs and all options. No shell commands, arbitrary
Docker flags, Compose files, interactive exec, privileged mode, host namespaces,
host devices, or host socket mounts. Do not offer an administrator flag escape
hatch through the generic web CLI endpoint. Secret environment values must not
appear in command arguments, logs, status, or container-detail responses.

Site containers use panel-scoped Docker-managed named volumes only, never host
bind paths. Create and verify volume ownership labels, local driver, and absence
of driver options before reuse; reject unverified existing volumes. This removes
mutable site-path resolution from Docker mounts. Rootful web-created containers use a
dedicated panel-managed data directory, not arbitrary host mounts. Publish ports
to loopback only and do not automatically open UFW or provider firewalls. The
existing reverse-proxy site feature provides deliberate public exposure.

Security revision approved November 10, 2026: a separate runtime identity and
managed site volumes replace the original same-UID daemon and site bind mounts.
Ordinary disable also stops the runtime user manager and disables lingering;
reenable restores them. Preserve the dedicated identity and data for reenable
unless explicitly purged. Legacy same-UID records and preexisting unverified
runtime identities fail closed, without automatic adoption or data migration.

Require finite CPU, memory, and PID limits on web-created containers. If rootless
cgroup delegation cannot enforce them, refuse creation with a clear prerequisite
error rather than claiming limits are applied. Defaults and upper bounds may be
chosen by the implementer and must be documented. Reads and log output must be
bounded, and remote image pulls must have timeouts and report failures cleanly.

## Backup findings and boundary

The current implementation creates full per-site file/SQL/manifest archives and
uses rclone for scheduled uploads. Its provider validation permits AWS, Wasabi,
and DigitalOcean only; arbitrary S3 endpoints are not currently supported.
Incremental/deduplicated backups, SFTP/SSH storage-box targets, configurable
local-folder targets, client-side archive encryption, and an integrated restore
workflow are not implemented.

This work must preserve existing backup behavior. It does not claim to back up
Docker images, volumes outside the site's current backup selection, or running
application state consistently. Document that limitation. A Restic-backed backup
and restore project can be designed separately if requested.

## Verification and delivery

Add regression tests using existing shell/PHP test conventions, with a failing
check before each behavior change. Cover flag parsing/conflicts, unattended and
piped installs, dry-run, legacy configuration, engine-specific ACL failures,
Docker opt-out, invalid input, role/site/daemon boundaries, mount traversal and
symlinks, port/resource enforcement, secret redaction, and site teardown.

Run shell syntax/ShellCheck, PHP lint and relevant unit/contract suites, npm
security checks, and the reproducible frontend build. Use stubbed commands for
host-mutating installer/CLI checks. Do not install Docker, alter firewall rules,
or provision databases on the development host as a test.

Real fresh-install, reboot, rootless service, and cache-engine integration checks
require disposable supported VMs. If those are unavailable, explicitly identify
them as unverified; passing mocked contracts is not an end-to-end certification.
Update installation, CLI, security, site, troubleshooting, and uninstall docs to
match shipped behavior. Do not commit, push, release, or deploy without a request.
