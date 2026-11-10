# AidiPanel Web Panel App

This is the web panel application for AidiPanel. It is deployed automatically by `install.sh`.

## Manual Deploy

If you need to re-deploy or update the panel app:

```bash
cd panel-app/
sudo bash deploy-panel.sh
```

On an existing installation, deployment preserves panel accounts, passwords,
sites, databases, configuration, and runtime storage. A random admin password is
generated only when deploying a clean panel database with no existing admin.

For normal release upgrades, prefer `sudo aidipanel self:update`; it downloads
the matching CLI and panel assets, verifies `SHA256SUMS`, and deploys both together.

## Structure

```
panel-app/
├── deploy-panel.sh     ← Deploy script
├── bin/                ← Scheduled panel helpers
├── build/              ← Frontend asset build scripts
├── resources/          ← Frontend source files
├── public/             ← Web root (Nginx serves this)
│   └── index.php       ← Entry point
├── app/
│   ├── Core/           ← Framework core (Router, DB, Auth, Session)
│   ├── Controllers/    ← Page controllers
│   ├── Views/          ← PHP templates
│   └── Middleware/     ← Auth + CSRF middleware
```

Runtime storage is preserved separately at `/opt/aidipanel/storage`; it is not
part of the release application tree.

## Stack

- Pure PHP, no framework (Router + SQLite + Alpine.js)
- No Composer needed
- Runs as the dedicated `aidipanel` user through `aidipanel-fpm`
- Served by Nginx on port 8443 by default

## Frontend Build

Use Node.js 24.15 or newer with npm:

```bash
npm ci
npm run build
npm test
npm audit --audit-level=high
```

Tailwind CSS 4 is built locally; the CodeMirror 6 editor and its languages are
bundled for offline use. Deployment serves the generated files in
`public/assets/`; Node.js is not needed on the panel server. Regenerate and
include the assets with frontend source/dependency updates. Vendored runtime
license notices are included in `public/assets/vendor/THIRD-PARTY-LICENSES.txt`.
Tailwind 4 targets modern browsers; review its
[browser compatibility requirements](https://tailwindcss.com/docs/compatibility)
before deploying to users who need legacy browser support.

ApexCharts is deliberately pinned to the existing MIT-licensed 4.7.0 release.
The current 8.8.1 release requires an OEM license for embedding in a product used
by others; updating that dependency requires appropriate licensing or a separate
chart-library migration. Other packages target the stable releases verified at
the time of the update, not automatic unreviewed upgrades.

## Admin Password

Generated randomly on the initial installation and saved to
`/opt/aidipanel/credentials.conf`. Re-deploying does not rotate it.

```bash
sudo grep PANEL_ADMIN /opt/aidipanel/credentials.conf
```
