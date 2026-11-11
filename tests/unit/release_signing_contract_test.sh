#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALLER="${ROOT}/install.sh"
CLI="${ROOT}/aidipanel"
CI="${ROOT}/.github/workflows/ci.yml"
PUBLIC_KEY="${ROOT}/config/release-signing-public.pub"

require() {
  local file="$1" pattern="$2" label="$3"
  grep -Fq -- "$pattern" "$file" || { printf 'FAIL: %s\n' "$label" >&2; exit 1; }
  printf 'ok: %s\n' "$label"
}

reject() {
  local file="$1" pattern="$2" label="$3"
  if grep -Fq -- "$pattern" "$file"; then
    printf 'FAIL: %s\n' "$label" >&2
    exit 1
  fi
  printf 'ok: %s\n' "$label"
}

[[ -s "$PUBLIC_KEY" ]] \
  || { printf 'FAIL: canonical release public key exists\n' >&2; exit 1; }
openssl pkey -pubin -in "$PUBLIC_KEY" -noout >/dev/null 2>&1 \
  || { printf 'FAIL: canonical release public key is valid PEM\n' >&2; exit 1; }

require "$INSTALLER" 'readonly AIDIPANEL_RELEASE_PUBLIC_KEY_B64=' 'installer pins the release public key'
require "$CLI" 'readonly AIDIPANEL_RELEASE_PUBLIC_KEY_B64=' 'CLI pins the release public key'
reject "$INSTALLER" '__AIDIPANEL_RELEASE_PUBLIC_KEY_B64__' 'installer key initialization is complete'
reject "$CLI" '__AIDIPANEL_RELEASE_PUBLIC_KEY_B64__' 'CLI key initialization is complete'
require "$INSTALLER" 'openssl dgst -sha256 -verify' 'installer verifies the signed manifest'
require "$CLI" 'openssl dgst -sha256 -verify' 'self-update verifies the signed manifest'
require "$INSTALLER" 'SHA256SUMS.sig' 'installer requires the detached signature'
require "$CLI" 'SHA256SUMS.sig' 'self-update requires the detached signature'
require "$CI" '# AIDIPANEL_RELEASE_VERSION=' 'release manifest binds the version'
require "$CI" '--draft' 'CI creates draft releases only'
require "$CI" 'RELEASE_SIGNING_PRIVATE_KEY' 'CI receives signing key from a secret'
require "$CI" 'tools/release/sign-manifest.sh' 'CI signs the release manifest'
require "$CI" 'gh release edit "$GITHUB_REF_NAME" --draft=false' 'CI publishes the signed release'

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
openssl ecparam -name prime256v1 -genkey -noout -out "$tmp/key.pem"
openssl pkey -in "$tmp/key.pem" -pubout -out "$tmp/public.pem"
printf 'test manifest\n' > "$tmp/SHA256SUMS"
RELEASE_SIGNING_PRIVATE_KEY=$(cat "$tmp/key.pem") bash "$ROOT/tools/release/sign-manifest.sh" "$tmp/SHA256SUMS" "$tmp/public.pem" "$tmp/signature"
openssl dgst -sha256 -verify "$tmp/public.pem" -signature "$tmp/signature" "$tmp/SHA256SUMS" >/dev/null
if RELEASE_SIGNING_PRIVATE_KEY=$(cat "$tmp/key.pem") bash "$ROOT/tools/release/sign-manifest.sh" "$tmp/SHA256SUMS" "$PUBLIC_KEY" "$tmp/bad-signature" 2>/dev/null; then
  printf 'FAIL: mismatched private key accepted\n' >&2
  exit 1
fi
[[ ! -e "$tmp/bad-signature" ]] || { printf 'FAIL: invalid signature retained\n' >&2; exit 1; }
if RELEASE_SIGNING_PRIVATE_KEY=$(cat "$PUBLIC_KEY") bash "$ROOT/tools/release/sign-manifest.sh" "$tmp/SHA256SUMS" "$PUBLIC_KEY" "$tmp/public-signature" 2>/dev/null; then
  printf 'FAIL: public key accepted as a private key\n' >&2
  exit 1
fi

key_b64=$(base64 -w0 "$PUBLIC_KEY")
installer_b64=$(sed -n 's/^readonly AIDIPANEL_RELEASE_PUBLIC_KEY_B64="\([^"]*\)"$/\1/p' "$INSTALLER")
cli_b64=$(sed -n 's/^readonly AIDIPANEL_RELEASE_PUBLIC_KEY_B64="\([^"]*\)"$/\1/p' "$CLI")
[[ "$installer_b64" == "$key_b64" && "$cli_b64" == "$key_b64" ]] \
  || { printf 'FAIL: embedded keys match canonical public key\n' >&2; exit 1; }

printf 'release signing contract passed\n'
