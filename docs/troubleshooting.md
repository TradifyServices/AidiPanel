# Troubleshooting

## Optional Docker and Valkey

If Docker was skipped, container pages are unavailable until it is installed and
enabled in the root-owned panel configuration. Do not rerun the full installer on
an existing production stack just to add Docker. Follow the official signed
Docker repository instructions for the host distribution, install the rootless
prerequisites listed in [Docker containers](docker.md), start the system daemon,
and set `INSTALL_DOCKER=true` in `/opt/aidipanel/config/panel.conf` as root.
Administrators must then enable each site's rootless runtime explicitly.

If rootless creation reports missing resource controllers, check cgroup v2 and
systemd user-service delegation; do not bypass the checks or grant the site user
access to `/var/run/docker.sock`. User namespaces/AppArmor and subordinate UID/GID
ranges also need to be usable. Test a reboot before relying on the user daemon.

For a Valkey installation, inspect `valkey-server` rather than `redis-server`
with `systemctl status` and use `valkey-cli` for direct diagnostics. Existing
`aidipanel cache:redis-*` commands retain their Redis-compatible names and route
to the configured engine. Never manually disable per-site ACLs to work around an
installation failure.

## Install / panel

**Port 8443 already in use**
Choose another port at install time: `--port 9443`. Check what holds it with
`sudo ss -ltnp | grep :8443`.

**Nginx fails to start or reload**
Run `sudo nginx -t` to see the exact config error. AidiPanel rolls back a bad
vhost on save, but a manual edit can still break the global config.

**PHP version install fails**
Some PHP point releases lack every extension in the third-party repo. AidiPanel
skips repo-absent extension packages and logs them. Check
`/var/log/aidipanel-install.log` for the package that failed.

**Certbot / Let's Encrypt fails**
Usually DNS: the domain (and `www` if requested) must resolve to this server
before issuance. AidiPanel pre-checks DNS per name and reports which one failed.

**Redis not active**
`sudo systemctl status redis-server`. If it was skipped at install (`--no-redis`),
install it later and enable it.

**SQLite permission errors in the panel**
The panel runs as the dedicated `aidipanel` user; the database lives at
`/opt/aidipanel/storage/db/aidipanel.sqlite`. Ensure the `storage` tree is owned
by `aidipanel:aidipanel`.

## CI

**shellcheck job is red**
Run it locally: `shellcheck -S warning install.sh aidipanel panel-app/deploy-panel.sh`.
Warnings fail the job; fix them or justify with a scoped `# shellcheck disable=` line.
