#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TMP_ROOT"' EXIT

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
installer_library=$(sed '/^main "\$@"$/d' "$ROOT/install.sh")

selection() (
  eval "$installer_library"
  trap - EXIT
  warn() { :; }
  die() { printf '%s\n' "$*" >&2; exit 1; }
  _parse_args "$@"
  printf '%s %s %s\n' "$CACHE_ENGINE" "$INSTALL_REDIS" "$INSTALL_DOCKER"
)

[[ "$(selection)" == 'redis true false' ]] || fail 'unattended defaults'
[[ "$(selection --cache-engine valkey --with-docker)" == 'valkey true true' ]] || fail 'explicit selections'
[[ "$(selection --no-redis --no-docker)" == 'none false false' ]] || fail 'legacy opt-out'
[[ "$(selection --cache-engine none --no-redis)" == 'none false false' ]] || fail 'matching aliases'
for arguments in '--cache-engine invalid' '--cache-engine' '--cache-engine redis --no-redis' '--no-redis --cache-engine valkey' '--cache-engine redis --cache-engine valkey' '--with-docker --no-docker' '--no-docker --with-docker'; do
  read -ra flags <<< "$arguments"
  if selection "${flags[@]}" >"$TMP_ROOT/output" 2>&1; then fail "accepted $arguments"; fi
done

(
  eval "$installer_library"
  trap - EXIT
  log() { :; }; warn() { :; }; ok() { :; }
  die() { printf '%s\n' "$*" >&2; exit 1; }
  apt-cache() { printf '  Candidate: 7.2.0\n'; }
  curl() {
    printf '%s\n' "$*" >> "$TMP_ROOT/network"
    if [[ "$*" == *Packages.gz* && "$*" != *--head* ]]; then
      printf 'Package: docker-ce\nPackage: docker-ce-cli\nPackage: containerd.io\nPackage: docker-buildx-plugin\nPackage: docker-ce-rootless-extras\n' | gzip
    fi
  }
  export OS_ID=ubuntu OS_CODENAME=noble ARCH=x86_64 CACHE_ENGINE=valkey INSTALL_REDIS=true INSTALL_DOCKER=true
  _resolve_cache_engine
  [[ "$CACHE_PACKAGE $CACHE_SERVICE $CACHE_CLI $CACHE_CONF $CACHE_ACCOUNT $CACHE_ACL_FILE" == 'valkey-server valkey-server valkey-cli /etc/valkey/valkey.conf valkey /etc/valkey/users.acl' ]] || fail 'Valkey installer paths'
  _assert_optional_components_available
  # Real apt-cache output can exceed a pipe buffer after the candidate line.
  (
    apt-cache() { printf '  Candidate: 7.2.0\n'; seq 1 100000; }
    _assert_apt_candidate valkey-server
  )
  curl() { return 1; }
  if ( _assert_optional_components_available ) >"$TMP_ROOT/docker-unavailable" 2>&1; then fail 'unavailable official Docker repository accepted'; fi
  grep -q 'omit --with-docker' "$TMP_ROOT/docker-unavailable" || fail 'unsupported Docker lacks recovery guidance'
  export DRY_RUN=true
  _apt_install() { fail 'dry-run installs packages'; }
  _install_verified_apt_key() { fail 'dry-run writes key'; }
  systemctl() { fail 'dry-run starts daemon'; }
  _install_redis
  _configure_redis
  _install_docker
  export INSTALL_DOCKER=false DRY_RUN=false
  _install_docker
  apt-cache() { printf '  Candidate: (none)\n'; }
  if ( _assert_optional_components_available ) >"$TMP_ROOT/unavailable" 2>&1; then fail 'unavailable Valkey accepted'; fi
  grep -q -- '--cache-engine redis' "$TMP_ROOT/unavailable" || fail 'unavailable cache lacks recovery guidance'
)

mkdir "$TMP_ROOT/bin"
for command in mkdir touch chmod apt-get systemctl swapon mkswap install tee; do
  printf '#!/bin/sh\nprintf "unexpected mutation: %%s\\n" "$0" >&2\nexit 91\n' > "$TMP_ROOT/bin/$command"
  chmod +x "$TMP_ROOT/bin/$command"
done
setsid env PATH="$TMP_ROOT/bin:$PATH" bash "$ROOT/install.sh" --dry-run --cache-engine none --no-docker </dev/null >"$TMP_ROOT/dry-run" 2>&1 || fail "dry-run failed: $(cat "$TMP_ROOT/dry-run")"
grep -q 'CACHE_ENGINE=none' "$TMP_ROOT/dry-run" || fail 'dry-run omits selected cache'
grep -q 'INSTALL_DOCKER=false' "$TMP_ROOT/dry-run" || fail 'dry-run omits Docker opt-out'
setsid env PATH="$TMP_ROOT/bin:$PATH" bash "$ROOT/install.sh" --dry-run </dev/null >"$TMP_ROOT/defaults" 2>&1 || fail 'headless dry-run failed'
grep -q 'CACHE_ENGINE=redis' "$TMP_ROOT/defaults" || fail 'headless cache default changed'
grep -q 'INSTALL_DOCKER=false' "$TMP_ROOT/defaults" || fail 'headless Docker default changed'
(
  fixture_library=${installer_library//\/opt\/aidipanel/$TMP_ROOT/panel}
  fixture_library=${fixture_library//\/var\/www/$TMP_ROOT/sites}
  eval "$fixture_library"
  trap - EXIT
  log() { :; }; ok() { :; }
  chown() { :; }
  export OS_ID=ubuntu OS_VERSION_ID=24.04 OS_CODENAME=noble CACHE_ENGINE=valkey INSTALL_REDIS=true INSTALL_DOCKER=true
  _create_panel_scaffold
  grep -qx 'CACHE_ENGINE=valkey' "$TMP_ROOT/panel/config/panel.conf" || fail 'selected cache not persisted'
  grep -qx 'INSTALL_REDIS=true' "$TMP_ROOT/panel/config/panel.conf" || fail 'compatibility cache flag not persisted'
  grep -qx 'INSTALL_DOCKER=true' "$TMP_ROOT/panel/config/panel.conf" || fail 'Docker opt-in not persisted'
)
printf 'installer component contract passed\n'
