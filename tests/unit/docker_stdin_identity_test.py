import importlib.util
import os
from pathlib import Path
import pwd
import unittest


class DockerStdinIdentityTest(unittest.TestCase):
    @unittest.skipUnless(os.geteuid() == 0 and Path("/usr/sbin/runuser").exists(), "requires root and runuser")
    def test_runtime_user_can_reopen_private_stdin_pipe(self):
        path = Path(__file__).resolve().parents[2] / "panel-app/bin/docker-manager.py"
        spec = importlib.util.spec_from_file_location("docker_helper_stdin", path)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        account = pwd.getpwnam("nobody")
        output = helper.run_command(["/usr/sbin/runuser", "-u", "nobody", "--", "/bin/cat", "/dev/stdin"],
                                    input_data=b"PRIVATE=value\n", stdin_uid=account.pw_uid)
        self.assertEqual(output, "PRIVATE=value\n")
