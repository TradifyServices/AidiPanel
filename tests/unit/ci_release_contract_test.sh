#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CI="${ROOT}/.github/workflows/ci.yml"

require() {
  local pattern="$1" label="$2"
  grep -Fq -- "$pattern" "$CI" || { printf 'FAIL: %s\n' "$label" >&2; exit 1; }
  printf 'ok: %s\n' "$label"
}

require_count() {
  local pattern="$1" expected="$2" label="$3" actual
  actual=$(grep -Fc -- "$pattern" "$CI" || true)
  [[ "$actual" -eq "$expected" ]] \
    || { printf 'FAIL: %s (expected %s, got %s)\n' "$label" "$expected" "$actual" >&2; exit 1; }
  printf 'ok: %s\n' "$label"
}

reject() {
  local pattern="$1" label="$2"
  if grep -Fq -- "$pattern" "$CI"; then
    printf 'FAIL: %s\n' "$label" >&2
    exit 1
  fi
  printf 'ok: %s\n' "$label"
}

reject_regex() {
  local pattern="$1" label="$2"
  if grep -Eq -- "$pattern" "$CI"; then
    printf 'FAIL: %s\n' "$label" >&2
    exit 1
  fi
  printf 'ok: %s\n' "$label"
}

require 'for test in tests/unit/*.sh' 'CI runs every tracked shell contract'
require 'npm ci' 'CI installs the exact frontend lockfile'
require 'npm run build' 'CI rebuilds generated frontend assets'
require 'git diff --exit-code -- panel-app/public/assets' 'CI rejects stale generated assets'
require 'npm audit --audit-level=high' 'CI checks build-time and runtime dependency advisories'
require_count 'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1' 4 \
  'every checkout step uses the immutable v7.0.1 release'
require_count 'actions/setup-node@949feb2413d6458794dcd2491c4babbbce0c15c1 # v7.1.0' 1 \
  'frontend setup uses the immutable v7.1.0 release'
require_count 'actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7.0.2' 1 \
  'release upload uses the immutable v7.0.2 release'
reject 'actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5' \
  'deprecated Node 20 checkout pin is absent'
reject 'actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020' \
  'deprecated Node 20 setup-node pin is absent'
reject 'actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02' \
  'deprecated Node 20 upload-artifact pin is absent'
reject_regex 'uses:[[:space:]]+actions/(checkout|setup-node|upload-artifact)@v[0-9]+' \
  'third-party actions never use a movable major tag'
require 'name: Verify release version' 'release publication verifies the source version'
require 'source_version="${GITHUB_REF_NAME#v}"' 'release version derives from the immutable tag'
require 'grep -Fqx "readonly PANEL_VERSION=\"${source_version}\"" install.sh' 'release tag must match the installer version'
require 'grep -Fqx "readonly CLI_VERSION=\"${source_version}\"" aidipanel' 'release tag must match the CLI version'
require 'grep -Fqx "readonly PANEL_VERSION=\"${source_version}\"" panel-app/deploy-panel.sh' 'release tag must match the deployer version'
require 'sha256sum install-aidipanel.sh aidipanel aidipanel-panel-app.tar.gz' 'release artifacts include integrity hashes'
require 'SHA256SUMS' 'release upload includes the checksum manifest'
require 'printf '\''# AIDIPANEL_RELEASE_VERSION=%s\n'\''' 'release manifest includes the signed version header'
require 'gh release create "$GITHUB_REF_NAME" "${flags[@]}" --draft' 'CI creates an unpublished draft'
require 'release-signing-public.pub' 'release publishes the public verification key'
require 'secrets.RELEASE_SIGNING_PRIVATE_KEY' 'release signing uses the configured secret'
require 'tools/release/sign-manifest.sh' 'release manifest is signed'
require 'gh release download "$GITHUB_REF_NAME" --dir release-check' 'uploaded assets are checked before publication'
require '[[ "$remote_commit" == "$GITHUB_SHA" ]]' 'tag still points to the built commit'
require 'gh release edit "$GITHUB_REF_NAME" --draft=false' 'verified release is published'
require 'needs: [lint-installer, lint-php, frontend]' 'publication depends on CI checks'

printf 'CI release contract passed\n'
