#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TEST_ROOT"' EXIT
PANEL_DIR="$TEST_ROOT/panel"
PANEL_CONF="$TEST_ROOT/panel.conf"
HOME_BASE="$TEST_ROOT/home"
mkdir -p "$PANEL_DIR/bin" "$HOME_BASE/siteuser"
touch "$PANEL_DIR/bin/docker-manager.py"

for function_name in _docker_manage _docker_site_stop _panel_config_get _security_lock; do
  function_body=$(awk -v signature="${function_name}() {" '$0 == signature { capture=1 } capture { print } capture && /^}/ { exit }' "$ROOT/aidipanel")
  [[ -n "$function_body" ]] || { echo "FAIL: $function_name is missing" >&2; exit 1; }
  eval "$function_body"
done

die() { printf '%s\n' "$*" >&2; exit 1; }
_require_root() { :; }
_domain_valid() { [[ "$1" == owned.example ]]; }
_validate_site_user() { [[ "$1" == siteuser ]]; }
_site_purge_guard() { [[ "$1" == owned.example && "$2" == siteuser && "$3" == siteuser ]]; }
_security_lock_path() { printf '%s/site-delete.lock' "$TEST_ROOT"; }
_cron_resolve() {
  [[ "$1" == owned.example ]] || die 'foreign domain'
  export CRON_USER=siteuser
}
python3() {
  printf '%s\n' "$@" > "$TEST_ROOT/arguments"
  cat > "$TEST_ROOT/payload"
  printf '{"success":true}\n'
}

output=$(_docker_manage status)
[[ "$output" == '{"available":false,"enabled":false,"containers":[]}' ]] || die 'disabled Docker status is not safe'
[[ ! -e "$TEST_ROOT/arguments" ]] || die 'disabled Docker invoked the backend'
if ( _docker_manage create ) </dev/null >/dev/null 2>&1; then die 'disabled Docker allowed creation'; fi

printf 'INSTALL_DOCKER=true\n' > "$PANEL_CONF"
(
  exec 202>"$TEST_ROOT/site-delete.lock"
  flock -x 202
  if ( SECURITY_LOCK_WAIT=0 _docker_manage enable --domain owned.example ) 202>&- </dev/null > /dev/null 2>&1; then
    die 'Docker enable raced past the site deletion lock'
  fi
  [[ ! -e "$TEST_ROOT/arguments" ]] || die 'blocked enable reached the backend'
)
printf '{"environment":{"TOKEN":"secret-value"}}' | _docker_manage create --domain owned.example > /dev/null
grep -Fxq siteuser "$TEST_ROOT/arguments" || die 'site identity was not resolved'
grep -Fxq "$HOME_BASE/siteuser" "$TEST_ROOT/arguments" || die 'site home was not resolved'
grep -Fq secret-value "$TEST_ROOT/payload" || die 'secret input did not reach stdin'
if grep -Fq secret-value "$TEST_ROOT/arguments"; then die 'secret was exposed in argv'; fi

for invalid_args in '--user root' '--domain foreign.example' '--domain owned.example --scope root' '--domain owned.example --purge'; do
  IFS=' ' read -r -a arguments <<< "$invalid_args"
  if ( _docker_manage list "${arguments[@]}" ) >/dev/null 2>&1; then die "unsafe arguments accepted: $invalid_args"; fi
done
if ( _docker_manage enable ) </dev/null >/dev/null 2>&1; then die 'rootful provisioning exposed'; fi
if ( _docker_manage exec ) </dev/null >/dev/null 2>&1; then die 'arbitrary operation exposed'; fi

_docker_site_stop owned.example siteuser false </dev/null
grep -Fxq disable "$TEST_ROOT/arguments" || die 'site deletion did not stop rootless Docker'
if grep -Fxq -- --purge "$TEST_ROOT/arguments"; then die 'keep-home deletion purges Docker data'; fi
_docker_site_stop owned.example siteuser true </dev/null
grep -Fxq -- --purge "$TEST_ROOT/arguments" || die 'confirmed purge did not include Docker runtime data'
if ( _docker_site_stop foreign.example siteuser true ) >/dev/null 2>&1; then die 'teardown ignored site identity'; fi

printf 'Docker CLI boundary tests passed\n'
