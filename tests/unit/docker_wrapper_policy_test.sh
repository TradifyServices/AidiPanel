#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_ROOT=$(mktemp -d)
trap 'rm -rf -- "$TEST_ROOT"' EXIT
for source_file in "$ROOT/install.sh" "$ROOT/panel-app/deploy-panel.sh"; do
awk '
  /cat > "\$wrapper[^"]*" <<[[:space:]]*.WRAPPER/ { capture=1; next }
  capture && index($0, "if [[ ! -x /usr/local/bin/aidipanel") == 1 { print "printf allowed"; exit }
  capture { print }
' "$source_file" > "$TEST_ROOT/wrapper"
for operation in status list create start stop restart remove logs; do
  [[ "$(bash "$TEST_ROOT/wrapper" "docker:$operation")" == allowed ]] || exit 1
  [[ "$(bash "$TEST_ROOT/wrapper" "docker:$operation" --domain owned.example)" == allowed ]] || exit 1
done
for operation in enable disable; do
  [[ "$(bash "$TEST_ROOT/wrapper" "docker:$operation" --domain owned.example)" == allowed ]] || exit 1
  if bash "$TEST_ROOT/wrapper" "docker:$operation" >/dev/null 2>&1; then echo 'FAIL: rootful provisioning allowed' >&2; exit 1; fi
done
for operation in create list enable disable; do
  if bash "$TEST_ROOT/wrapper" "docker:$operation" --domain owned.example --user root >/dev/null 2>&1; then echo 'FAIL: user override allowed' >&2; exit 1; fi
  if bash "$TEST_ROOT/wrapper" "docker:$operation" --domain owned.example --host unix:///var/run/docker.sock >/dev/null 2>&1; then echo 'FAIL: socket override allowed' >&2; exit 1; fi
done
if bash "$TEST_ROOT/wrapper" docker:exec >/dev/null 2>&1; then echo 'FAIL: arbitrary Docker command allowed' >&2; exit 1; fi
done
printf 'Docker wrapper policy tests passed\n'
