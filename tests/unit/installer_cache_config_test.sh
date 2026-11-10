#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TMP_ROOT"' EXIT
eval "$(sed '/^main "\$@"$/d' "$ROOT/install.sh")"
trap 'rm -rf -- "$TMP_ROOT"' EXIT
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
log() { :; }; ok() { :; }; warn() { :; }; ui_ok() { :; }
die() { printf '%s\n' "$*" >&2; exit 1; }
chown() { printf '%s\n' "$*" >> "$TMP_ROOT/owners"; }
systemctl() { printf '%s\n' "$*" >> "$TMP_ROOT/services"; }
_resolve_cache_engine() {
  export CACHE_CONF="$TMP_ROOT/valkey.conf" CACHE_ACL_FILE="$TMP_ROOT/users.acl"
  export CACHE_ACCOUNT=valkey CACHE_SERVICE=valkey-server
}
printf '  bind 0.0.0.0\nprotected-mode no\nsave 3600 1\nsave 300 100\nappendonly yes\nmaxmemory 0\n# maxmemory-policy noeviction\n' > "$TMP_ROOT/valkey.conf"
export CACHE_ENGINE=valkey INSTALL_REDIS=true
run() { "$@"; }
_configure_redis
grep -q '^bind 127.0.0.1 ::1$' "$TMP_ROOT/valkey.conf" || fail 'cache is not loopback bound'
grep -q '^protected-mode yes$' "$TMP_ROOT/valkey.conf" || fail 'cache protected mode is disabled'
grep -q '^save ""$' "$TMP_ROOT/valkey.conf" || fail 'snapshot persistence remains enabled'
grep -q '^appendonly no$' "$TMP_ROOT/valkey.conf" || fail 'AOF persistence remains enabled'
grep -q '^maxmemory-policy allkeys-lru$' "$TMP_ROOT/valkey.conf" || fail 'LRU policy missing'
[[ "$(grep -c '^maxmemory ' "$TMP_ROOT/valkey.conf")" == 1 ]] || fail 'conflicting memory limits'
grep -q "^aclfile $TMP_ROOT/users.acl$" "$TMP_ROOT/valkey.conf" || fail 'wrong ACL path'
grep -q 'valkey:valkey' "$TMP_ROOT/owners" || fail 'wrong ACL service account'
grep -q 'valkey-server' "$TMP_ROOT/services" || fail 'wrong cache restarted'

policy_helper=$(awk '/^_install_all_php_versions\(\) \{/ {capture=1} capture {print} capture && /^}$/ {exit}' "$ROOT/install.sh")
policy_helper=${policy_helper//\/etc\/aidipanel/$TMP_ROOT}
eval "$policy_helper"
php_install_helper=$(declare -f _install_php_version)
_install_php_version() { :; }; _configure_php_fpm() { :; }
export CACHE_ENGINE=none
_install_all_php_versions
[[ " $PHP_EXTENSIONS " != *' redis '* ]] || fail 'cache none still requires phpredis'
export CACHE_ENGINE=valkey
_install_all_php_versions
[[ " $PHP_EXTENSIONS " == *' redis '* ]] || fail 'Valkey lacks compatible phpredis extension'
printf 'installer cache configuration contract passed\n'

apt-cache() { return 1; }
eval "$php_install_helper"
_apt_install() { fail 'missing PHP extension still proceeds to package installation'; }
PHP_EXTENSIONS='fpm redis'
if ( _install_php_version 8.5 ); then fail 'required cache extension unavailable but accepted'; fi
