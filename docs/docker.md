# Docker containers

Docker is optional. During initial setup, choose **Install Docker**, or install
unattended with:

```bash
sudo bash install.sh --with-docker
sudo bash install.sh --cache-engine valkey --with-docker
```

`--no-docker` explicitly skips Docker. Without a controlling terminal, Docker is
skipped unless `--with-docker` is supplied. Explicit flags suppress the matching
question; the installer never reads choices from a piped script's stdin.

## Permission model

- **Admin Area → Docker:** administrators manage panel-created rootful containers.
- **Site → Containers:** users manage panel-created rootless containers for sites
  they may already manage. Administrators explicitly enable a site's rootless
  runtime before it can be used.
- Clients and managers cannot provision rootless runtimes or use rootful Docker.
- The panel never adds site users to the `docker` group or exposes a Docker TCP
  API. Site users retain their no-login shells and existing jailed-SFTP policy.
- Each site's daemon uses a dedicated no-login runtime account, not its PHP/SFTP
  account. The private runtime home and socket are not accessible to site code;
  authorized panel requests mediate management.
- Existing unrelated containers are not adopted or removed by the panel.

Enable a rootless site runtime from its Containers tab or as root:

```bash
sudo aidipanel docker:enable --domain example.com
sudo aidipanel docker:list --domain example.com
sudo aidipanel docker:status
```

Omitting `--domain` selects rootful management. A domain is resolved to its managed
site identity by the privileged CLI; a submitted username or Docker socket is
never accepted. Docker commands are not available through the generic `/api/cli`.

## Creating and managing containers

Use the panel form for image/name, CPU, memory, PID limits, environment variables,
port mappings, and managed volumes. Structured fields accept JSON. Only use images
you trust: containers sharing one site's runtime and volumes are not isolated
from each other's application data.

The same operation is available through structured stdin:

```bash
printf '%s\n' '{"name":"web","image":"nginx:alpine","cpus":1,"memory_mb":512,"pids_limit":128,"environment":{},"ports":[{"host":8080,"container":80}],"volumes":[]}' \
  | sudo aidipanel docker:create --domain example.com
```

Use a private input stream rather than putting real environment secrets into
shell command history. The helper does not place their values into Docker command
arguments or panel activity logs; status responses do not return environment
values. Docker itself stores a container's environment as part of its runtime
configuration, so the dedicated runtime account and server root remain trusted.

All published ports bind to `127.0.0.1`. To expose an application deliberately,
create a reverse-proxy site targeting `http://127.0.0.1:8080`; the panel does not
automatically open container ports in UFW or provider firewalls. Site containers
accept named volumes, not host bind paths. Rootful bind sources must already
exist in the administrator-managed `/var/lib/aidipanel/docker-data` directory. System paths,
symlink escapes, devices, host namespaces, privileged mode, and Docker sockets
are not accepted.

For a site volume, use `[{"name":"app-data","target":"/data","readonly":false}]`.
The helper generates a site-scoped Docker volume name and verifies its ownership,
local driver, and lack of driver options before reuse. Volume data is separate
from the site's file manager and webroot. Removing a container does not delete
its named volumes. Host bind sources are rejected even if inside the site home;
this avoids races with paths that site code can replace.
Images declaring `VOLUME` paths require explicit managed named-volume entries
for those paths; implicit unscoped anonymous volumes are refused.

For a rootful bind mount, an administrator can prepare a private directory with
`sudo install -d -m 0700 /var/lib/aidipanel/docker-data/app` before using it as the
source, using `[{"source":"/var/lib/aidipanel/docker-data/app","target":"/data","readonly":false}]`.
Rootful mount trees are checked for sockets, special files, symlinks, and nested
mounts; large or deeply nested trees may be refused. Keep these directories
administrator-controlled, never writable by site processes.

Defaults are 1 CPU, 512 MiB memory and 128 PIDs. Supported per-container bounds
are 0.1–32 CPUs, 16–65536 MiB and 16–4096 PIDs; these are not aggregate site quotas.

The panel supports start, stop, restart, remove, and bounded logs. Lifecycle
commands accept the managed container ID on stdin:

```bash
printf '%s\n' '{"id":"<container-id-from-list>"}' \
  | sudo aidipanel docker:stop --domain example.com
```

Interactive exec, arbitrary Docker options, Compose uploads, registry credential
management, and automatic public exposure are not part of this interface.

## Host requirements and lifecycle

Installation uses the official signed Docker package repository and rootless
prerequisites. Rootless operation also requires usable user namespaces,
non-overlapping subordinate UID/GID ranges, a systemd user manager and lingering,
and working cgroup v2 resource delegation. Ubuntu's AppArmor policy must permit
the packaged rootless runtime. Creation fails if required CPU, memory, and PID
limits cannot be enforced; the panel does not pretend unenforced limits work.

Unsupported package/OS combinations fail with guidance rather than downloading
unsigned binaries. Verify fresh installs and reboots on a disposable supported
VPS before using Docker for production workloads.

Disabling a site's rootless runtime stops its managed containers and daemon but
keeps data and its dedicated account, disables lingering, and stops the runtime
user manager. Reenabling restores managed services. Site deletion stops the site's
runtime before account changes. Ordinary keep-home deletion preserves runtime
data separately from the site home; a confirmed site purge removes the verified
dedicated runtime account and its managed data. Unrelated administrator containers are not
part of site teardown. Do not manually remove a site's Linux user while its
rootless daemon is running. Legacy same-user runtime records or unverified
accounts/daemons are refused rather than automatically adopted or migrated;
back up and resolve them administratively before enabling the revised runtime.

## Backups and removal

Existing site backups are webroot/database archives, not Docker backups. They do
not automatically include Docker volumes, image layers, or files elsewhere in a
site home, and do not provide application-consistent snapshots of running
containers. Back up persistent application data separately and test restoration.

Before removing Docker, stop every managed runtime and back up required data.
Rootful Docker may also host unrelated workloads: do not blindly remove
`/var/lib/docker`, subordinate-ID entries, or user lingering for unrelated users.
Follow Docker's distribution-specific uninstall instructions after stopping all
required workloads; package removal and deleting container data are separate
decisions.
