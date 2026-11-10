#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TMP_ROOT"' EXIT
eval "$(sed '/^main "\$@"$/d' "$ROOT/install.sh")"
trap 'rm -rf -- "$TMP_ROOT"' EXIT
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
log() { :; }; ok() { :; }; warn() { :; }
docker_helper=$(declare -f _install_docker)
docker_helper=${docker_helper//\/etc\/apt/$TMP_ROOT}
eval "$docker_helper"
mkdir -p "$TMP_ROOT/sources.list.d" "$TMP_ROOT/keyrings"
_install_verified_apt_key() {
  [[ "$1" == 'https://download.docker.com/linux/ubuntu/gpg' ]] || fail 'Docker key not from official source'
  [[ "$3" == 9DC858229FC7DD38854AE2D88D81803C0EBFCD88 ]] || fail 'unverified Docker key'
  [[ "$2" == "$TMP_ROOT/keyrings/aidipanel-docker.gpg" ]] || fail 'Docker key trusted globally instead of scoped keyring'
  printf 'verified key\n' > "$2"
}
_apt_update() { :; }
_assert_apt_candidate() { :; }
_apt_install() { printf '%s\n' "$@" > "$TMP_ROOT/packages"; }
run() { "$@"; }
systemctl() { printf '%s\n' "$*" > "$TMP_ROOT/service"; }
usermod() { fail 'Docker changes user groups'; }
useradd() { fail 'Docker eagerly creates site identities'; }
loginctl() { fail 'Docker eagerly enables site daemons'; }
export OS_ID=ubuntu OS_CODENAME=noble ARCH=aarch64 INSTALL_DOCKER=true
_install_docker
for package in docker-ce docker-ce-cli containerd.io docker-ce-rootless-extras uidmap dbus-user-session slirp4netns; do
  grep -qx "$package" "$TMP_ROOT/packages" || fail "Docker prerequisite missing: $package"
done
grep -q 'arch=arm64 signed-by=' "$TMP_ROOT/sources.list.d/aidipanel-docker.list" || fail 'Docker architecture/key scope missing'
grep -q 'https://download.docker.com/linux/ubuntu noble stable' "$TMP_ROOT/sources.list.d/aidipanel-docker.list" || fail 'Docker repository is not official stable'
grep -q 'docker' "$TMP_ROOT/service" || fail 'rootful Docker was not enabled'
printf 'installer signed Docker provisioning contract passed\n'
