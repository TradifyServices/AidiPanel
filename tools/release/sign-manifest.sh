#!/usr/bin/env bash
set -euo pipefail

[[ $# == 3 && -n "${RELEASE_SIGNING_PRIVATE_KEY:-}" ]] || { echo 'Missing signing key or arguments' >&2; exit 1; }
manifest=$1
public_key=$2
signature=$3
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
umask 077
printf '%s\n' "$RELEASE_SIGNING_PRIVATE_KEY" > "$temporary/private.pem"
unset RELEASE_SIGNING_PRIVATE_KEY
openssl pkey -in "$temporary/private.pem" -pubout -outform DER -out "$temporary/derived.der"
openssl pkey -pubin -in "$public_key" -outform DER -out "$temporary/expected.der"
cmp -s "$temporary/derived.der" "$temporary/expected.der" || { echo 'Signing key does not match pinned public key' >&2; exit 1; }
openssl dgst -sha256 -sign "$temporary/private.pem" -out "$temporary/signature" "$manifest"
openssl dgst -sha256 -verify "$public_key" -signature "$temporary/signature" "$manifest"
mv "$temporary/signature" "$signature"
