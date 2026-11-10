import importlib.util
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock


HELPER_PATH = Path(__file__).resolve().parents[2] / "panel-app/bin/docker-manager.py"


class DockerIntegrationTests(unittest.TestCase):
    def setUp(self):
        specification = importlib.util.spec_from_file_location("docker_integration_helper", HELPER_PATH)
        self.helper = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(self.helper)

    def test_unprovisioned_site_reports_installed_but_disabled(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(self.helper, "ROOT_UID", os.getuid()), mock.patch.object(self.helper, "STATE_DIR", Path(temporary) / "state"), mock.patch.object(self.helper.os, "geteuid", return_value=0):
            manager = self.helper.DockerManager("root")
            manager.scope = "site"
            with mock.patch.object(manager, "info", side_effect=self.helper.ManagerError("not provisioned")), mock.patch.object(self.helper.os, "access", return_value=True):
                self.assertEqual(manager.execute("status", {}), {"available": True, "enabled": False, "containers": []})

    def test_redaction_does_not_reprocess_its_own_replacement_marker(self):
        self.assertEqual(self.helper.redact("secret", ["TOKEN=secret", "LETTER=e"], 64), "[redacted]")

    def test_site_rejects_legacy_runtime_and_bind_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "sitehome"
            home.mkdir()
            account = types.SimpleNamespace(pw_uid=1200, pw_gid=1200, pw_dir=str(home))
            with mock.patch.object(self.helper, "ROOT_UID", os.getuid()), mock.patch.object(self.helper, "STATE_DIR", Path(temporary) / "state"), mock.patch.object(self.helper.os, "geteuid", return_value=0), mock.patch.object(self.helper.pwd, "getpwnam", return_value=account):
                manager = self.helper.DockerManager("site", "owned.example", "siteuser", str(home))
                manager.marker.parent.mkdir()
                manager.marker.write_text(json.dumps({"domain": manager.domain, "user": manager.user, "home": str(home), "uid": 1200, "unit": manager.unit}))
                manager.marker.chmod(0o600)
                with self.assertRaises(self.helper.ManagerError):
                    manager.runtime_record()
                with self.assertRaises(self.helper.ManagerError):
                    manager.validate_mount({"source": str(home), "target": "/data", "readonly": False})

    def test_enable_prepares_storage_for_root_owned_sftp_home(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            home = directory / "sitehome"
            home.mkdir()
            runtime_home = directory / "runtime" / "1200"
            subuid = directory / "subuid"
            subgid = directory / "subgid"
            subuid.write_text("")
            subgid.write_text("")
            subuid.chmod(0o644)
            subgid.chmod(0o644)
            site = types.SimpleNamespace(pw_uid=1200, pw_gid=1200, pw_dir=str(home), pw_name="siteuser")
            runtime = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(runtime_home), pw_shell="/usr/sbin/nologin", pw_name="apdock_1200")
            group = types.SimpleNamespace(gr_gid=runtime.pw_gid, gr_name=runtime.pw_name, gr_mem=[])
            created = []
            real_stat = Path.stat

            def stat_path(path, *arguments, **keywords):
                metadata = real_stat(path, *arguments, **keywords)
                if path in directory.parents:
                    values = list(metadata)
                    values[0] = (metadata.st_mode & ~0o777) | 0o755
                    values[4] = os.getuid()
                    return os.stat_result(values)
                return metadata

            def get_account(name):
                if name == "siteuser":
                    return site
                if name == runtime.pw_name and created:
                    return runtime
                raise KeyError(name)

            def get_group(name):
                if name == runtime.pw_name and created:
                    return group
                raise KeyError(name)

            def command(arguments, **options):
                if arguments[0] == "/usr/sbin/useradd":
                    created.append(True)
                return ""

            with mock.patch.object(self.helper, "ROOT_UID", os.getuid()), mock.patch.object(self.helper, "STATE_DIR", directory / "state"), mock.patch.object(self.helper, "RUNTIME_DIR", directory / "runtime"), mock.patch.object(self.helper, "UNIT_DIR", directory / "units"), mock.patch.object(self.helper.os, "geteuid", return_value=0), mock.patch.object(self.helper.pwd, "getpwnam", side_effect=get_account), mock.patch.object(self.helper.pwd, "getpwall", side_effect=lambda: [site] + ([runtime] if created else [])), mock.patch.object(self.helper.grp, "getgrnam", side_effect=get_group), mock.patch.object(self.helper.grp, "getgrall", side_effect=lambda: [group] if created else []), mock.patch.object(Path, "stat", stat_path):
                manager = self.helper.DockerManager("site", "owned.example", "siteuser", str(home))
                information = {
                    "CgroupDriver": "systemd", "CgroupVersion": "2", "MemoryLimit": True,
                    "CpuCfsQuota": True, "PidsLimit": True, "SwapLimit": True, "SecurityOptions": ["name=rootless"],
                    "DockerRootDir": str(manager.storage / "data"),
                }
                with mock.patch.object(self.helper, "SUBUID", subuid), mock.patch.object(self.helper, "SUBGID", subgid), mock.patch.object(manager, "prerequisites", return_value=(None, None)), mock.patch.object(manager, "subordinate_ranges", return_value=(None, None)), mock.patch.object(manager, "socket_exists", return_value=False), mock.patch.object(manager, "info", return_value=information), mock.patch.object(self.helper, "run_command", side_effect=command), mock.patch.object(self.helper.os, "chown"), mock.patch.object(self.helper.os, "fchown"):
                    manager.enable()
                self.assertTrue(runtime_home.is_dir())
                self.assertEqual(list(home.iterdir()), [])
                self.assertNotEqual(manager.runtime_uid, site.pw_uid)


if __name__ == "__main__":
    unittest.main()
