#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TMP_ROOT"' EXIT
export AIDIPANEL_LIB_ONLY=1
source "$ROOT/aidipanel"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
die() { printf '%s\n' "$*" >&2; exit 1; }
_require_root() { :; }

printf 'INSTALL_REDIS=false\n' > "$TMP_ROOT/panel.conf"
_cache_engine_load "$TMP_ROOT/panel.conf"
[[ "$CACHE_ENGINE" == none && "$INSTALL_DOCKER" == false ]] || fail 'legacy cache opt-out'
printf 'INSTALL_REDIS=true\n' > "$TMP_ROOT/panel.conf"
_cache_engine_load "$TMP_ROOT/panel.conf"
[[ "$CACHE_ENGINE $CACHE_SERVICE $CACHE_CLI" == 'redis redis-server redis-cli' ]] || fail 'legacy Redis default'
printf 'CACHE_ENGINE=valkey\nINSTALL_REDIS=true\nINSTALL_DOCKER=true\n' > "$TMP_ROOT/panel.conf"
_cache_engine_load "$TMP_ROOT/panel.conf"
[[ "$CACHE_SERVICE $CACHE_CLI $REDIS_CONF $REDIS_ACL_FILE $CACHE_ACCOUNT" == 'valkey-server valkey-cli /etc/valkey/valkey.conf /etc/valkey/users.acl valkey' ]] || fail 'Valkey runtime paths'
_redis_admin_secret() { printf 'test-secret'; }
timeout() { local IFS=' '; printf '%s|%s\n' "$REDISCLI_AUTH" "$*"; }
[[ "$(_redis PING)" == 'test-secret|3 valkey-cli --user aidipanel_admin PING' ]] || fail 'Valkey authenticated invocation'
printf 'CACHE_ENGINE=none\n' > "$TMP_ROOT/panel.conf"
_cache_engine_load "$TMP_ROOT/panel.conf"
timeout() { fail 'cache none invokes runtime'; }
systemctl() { fail 'cache none controls runtime'; }
if ( _redis PING ); then fail 'cache none reports success'; fi
if ( _cache_redis_enable ); then fail 'cache none enables runtime'; fi
if ( _service_action start redis ); then fail 'cache none starts service alias'; fi
[[ "$(_cache_redis_acl --action status)" == *'acl_enabled=0'* ]] || fail 'cache none reports stale ACL state'
if ( _cache_redis_per_site --action disable --domain example.com ); then fail 'cache none changes WordPress'; fi
_cache_install_wp_plugins example.com false true > "$TMP_ROOT/plugin-output"
grep -q '^redis_plugin=skipped_cache_disabled$' "$TMP_ROOT/plugin-output" || fail 'cache none installs object cache plugin'
if (
  export CACHE_ENGINE=valkey PHP_EXTENSIONS='fpm redis'
  _php_installed() { return 1; }
  _php_version_valid() { return 0; }
  log() { :; }
  apt-cache() { [[ "$2" != php8.5-redis ]]; }
  apt-get() {
    [[ "$1" != update ]] || return 0
    touch "$TMP_ROOT/php-install-attempted"
    return 1
  }
  _ensure_php_version 8.5
) > "$TMP_ROOT/php-error" 2>&1; then fail 'on-demand PHP install accepted missing required cache extension'; fi
[[ ! -e "$TMP_ROOT/php-install-attempted" ]] || fail 'on-demand PHP install silently skips required cache extension'
printf 'CACHE_ENGINE=unexpected\n' > "$TMP_ROOT/panel.conf"
if ( _cache_engine_load "$TMP_ROOT/panel.conf" ); then fail 'unknown persisted engine accepted'; fi
printf 'cache engine contract passed\n'
