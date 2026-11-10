#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TMP_ROOT"' EXIT
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
installer_library=$(sed '/^main "\$@"$/d' "$ROOT/install.sh")
installer_library=${installer_library//\/var\/log\/aidipanel-install.log/$TMP_ROOT/panel.log}
for ready in false true; do
  if (
    eval "$installer_library"
    log() { :; }; ok() { :; }; warn() { :; }
    _pkg_installed() { return 1; }
    _apt_install() { :; }
    run() { "$@"; }
    systemctl() { printf '%s\n' "$*" >> "$TMP_ROOT/$ready"; }
    export CACHE_ENGINE=valkey
    _install_redis
    export CACHE_ACL_READY="$ready"
    exit 1
  ) >/dev/null 2>&1; then fail 'simulated failure returned success'; fi
  if [[ "$ready" == false ]]; then
    grep -q 'disable' "$TMP_ROOT/$ready" || fail 'installer abort leaves cache running before ACL isolation'
    grep -q 'valkey-server' "$TMP_ROOT/$ready" || fail 'abort targets wrong service'
  elif grep -q 'disable' "$TMP_ROOT/$ready"; then
    fail 'later installer error disables an isolated cache'
  fi
done
printf 'installer cache pre-isolation abort contract passed\n'
