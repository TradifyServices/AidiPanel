#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TMP_ROOT"' EXIT
eval "$(sed '/^main "\$@"$/d' "$ROOT/install.sh")"
trap 'rm -rf -- "$TMP_ROOT"' EXIT
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
log() { :; }; warn() { :; }; ok() { :; }
command() {
  [[ "$1 ${2:-}" != '-v wp' ]] || return 1
  builtin command "$@"
}
_download_first() {
  local destination="$1" url="$2"
  [[ "$url" == https://github.com/wp-cli/wp-cli/releases/download/v2.12.0/wp-cli-2.12.0.phar* ]] || fail "unversioned WP-CLI URL: $url"
  printf 'untrusted download\n' > "$destination"
}
install() { fail 'invalid checksum installed WP-CLI'; }
if _install_wpcli; then fail 'invalid checksum accepted'; fi
printf 'installer WP-CLI pinned-download contract passed\n'
