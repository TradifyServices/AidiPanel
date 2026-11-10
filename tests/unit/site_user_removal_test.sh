#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
eval "$(sed -n '/^_remove_site_user() {$/,/^}$/p' "$ROOT/aidipanel")"
CLI_LOG=/dev/null
id() { return "${ACCOUNT_ABSENT:-0}"; }
gpasswd() { return 0; }
userdel() { return 1; }
getent() { return 1; }
if _remove_site_user siteuser strict; then
  echo 'failed userdel must fail strict removal' >&2
  exit 1
fi
ACCOUNT_ABSENT=1 _remove_site_user siteuser strict
_remove_site_user siteuser
grep -Fq '_remove_site_user "$site_user" strict || die ' "$ROOT/aidipanel"
