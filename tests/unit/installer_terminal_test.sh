#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 - "$ROOT/install.sh" <<'PY'
import errno
import os
import pty
import select
import signal
import sys
import time

installer = sys.argv[1]
for flags, answers, expected in [
    ([], [b'valkey\n', b'y\n'], ['CACHE_ENGINE=valkey', 'INSTALL_DOCKER=true']),
    (['--cache-engine', 'none'], [b'\n'], ['CACHE_ENGINE=none', 'INSTALL_DOCKER=false']),
    (['--no-docker'], [b'\n'], ['CACHE_ENGINE=redis', 'INSTALL_DOCKER=false']),
    (['--cache-engine', 'valkey', '--with-docker'], [], ['CACHE_ENGINE=valkey', 'INSTALL_DOCKER=true']),
]:
    child_pid, terminal = pty.fork()
    if child_pid == 0:
        script = 'cat -- "$1"; printf \'\\nprintf "PIPE_SCRIPT_END\\\\n"\\n\''
        os.execlp('bash', 'bash', '-c', '{ ' + script + '; } | bash -s -- --dry-run "${@:2}"', 'test', installer, *flags)
    output = b''
    answer_index = 0
    deadline = time.monotonic() + 8
    try:
        while time.monotonic() < deadline:
            if not select.select([terminal], [], [], 0.1)[0]:
                continue
            try:
                chunk = os.read(terminal, 65536)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            output += chunk
            prompts = output.count(b'[redis]: ') + output.count(b'[y/N]: ')
            if prompts > answer_index and answer_index < len(answers):
                os.write(terminal, answers[answer_index])
                answer_index += 1
        else:
            raise AssertionError('piped installer blocked: ' + repr(output))
        _, status = os.waitpid(child_pid, 0)
        child_pid = None
        assert status == 0, output
        decoded = output.decode()
        for marker in [*expected, 'PIPE_SCRIPT_END']:
            assert marker in decoded, decoded
        assert answer_index == len(answers), decoded
        if not answers:
            assert '[redis]: ' not in decoded and '[y/N]: ' not in decoded, decoded
    finally:
        os.close(terminal)
        if child_pid is not None:
            os.kill(child_pid, signal.SIGKILL)
            os.waitpid(child_pid, 0)
print('installer controlling-terminal and piped-script contract passed')
PY
