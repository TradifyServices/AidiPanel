import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import types
import unittest
from unittest import mock


HELPER = Path(__file__).resolve().parents[2] / "panel-app/bin/docker-manager.py"
CONTAINER_ID = "a" * 64


def load_helper():
    specification = importlib.util.spec_from_file_location("docker_manager", HELPER)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class DockerManagerTest(unittest.TestCase):
    def setUp(self):
        if not HELPER.is_file():
            self.fail("Task 3 Docker helper is missing")
        self.helper = load_helper()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.home = self.directory / "siteuser"
        self.home.mkdir()
        self.root_data = self.directory / "docker-data"
        self.root_data.mkdir()
        self.root_data.chmod(0o755)
        self.state = self.directory / "state"
        self.runtime_dir = self.directory / "runtime"
        self.storage = self.runtime_dir / "1200"
        self.runtime_uid = os.getuid()
        self.runtime_gid = os.getgid()
        self.runtime_present = False
        self.volumes = {}
        self.cgroups = self.directory / "cgroups"
        self.delegation = self.cgroups / "user.slice" / ("user-" + str(self.runtime_uid) + ".slice") / ("user@" + str(self.runtime_uid) + ".service")
        self.delegation.mkdir(parents=True)
        (self.cgroups / "cgroup.controllers").write_text("cpu memory pids\n")
        (self.delegation / "cgroup.controllers").write_text("cpu memory pids\n")
        self.units = self.directory / "units"
        self.units.mkdir()
        self.units.chmod(0o755)
        self.subuid = self.directory / "subuid"
        self.subgid = self.directory / "subgid"
        self.mountinfo = self.directory / "mountinfo"
        self.mountinfo.write_text("")
        self.subuid.write_text("other:100000:65536\n")
        self.subgid.write_text("other:100000:65536\n")
        self.subuid.chmod(0o644)
        self.subgid.chmod(0o644)
        self.calls = []
        self.available = True
        self.containers = {}
        self.log_output = "application started\n"
        self.information = {
            "CgroupDriver": "systemd", "CgroupVersion": "2",
            "MemoryLimit": True, "CpuCfsQuota": True, "PidsLimit": True, "SwapLimit": True,
            "SecurityOptions": ["name=rootless", "name=seccomp,profile=builtin"],
            "DockerRootDir": str(self.storage / "data"),
        }
        self.account = types.SimpleNamespace(pw_uid=1200, pw_gid=1200, pw_dir=str(self.home), pw_shell="/usr/sbin/nologin", pw_name="siteuser")
        self.runtime_account = types.SimpleNamespace(pw_uid=self.runtime_uid, pw_gid=self.runtime_gid, pw_dir=str(self.storage), pw_shell="/usr/sbin/nologin", pw_name="apdock_1200")
        real_stat = Path.stat
        real_lexists = os.path.lexists

        def trusted_ancestor_stat(path, *arguments, **keywords):
            metadata = real_stat(path, *arguments, **keywords)
            if path in self.directory.parents:
                values = list(metadata)
                values[0] = (metadata.st_mode & ~0o777) | 0o755
                values[4] = os.getuid()
                return os.stat_result(values)
            return metadata
        self.patches = [
            mock.patch.object(self.helper, "ROOT_UID", os.getuid()),
            mock.patch.object(self.helper, "ROOT_SOCKET", self.directory / "root.sock"),
            mock.patch.object(self.helper, "CGROUP_ROOT", self.cgroups, create=True),
            mock.patch.object(self.helper, "MOUNTINFO", self.mountinfo, create=True),
            mock.patch.object(self.helper, "ROOT_DATA", self.root_data),
            mock.patch.object(self.helper, "STATE_DIR", self.state),
            mock.patch.object(self.helper, "RUNTIME_DIR", self.runtime_dir),
            mock.patch.object(self.helper, "UNIT_DIR", self.units),
            mock.patch.object(self.helper, "SUBUID", self.subuid),
            mock.patch.object(self.helper, "SUBGID", self.subgid),
            mock.patch.object(self.helper.pwd, "getpwnam", side_effect=self.get_account),
            mock.patch.object(self.helper.pwd, "getpwall", side_effect=lambda: [self.account] + ([self.runtime_account] if self.runtime_present else [])),
            mock.patch.object(self.helper.grp, "getgrnam", side_effect=self.get_group),
            mock.patch.object(self.helper.grp, "getgrall", side_effect=lambda: [self.get_group("apdock_1200")] if self.runtime_present else []),
            mock.patch.object(Path, "stat", trusted_ancestor_stat),
            mock.patch.object(self.helper.os, "geteuid", return_value=0),
            mock.patch.object(self.helper.os, "fchown"),
            mock.patch.object(self.helper.os, "chown"),
            mock.patch.object(self.helper.os.path, "lexists", side_effect=lambda path: False if str(path) == "/run/user/" + str(self.runtime_uid) + "/docker.sock" else real_lexists(path)),
            mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False),
            mock.patch.object(self.helper, "run_command", side_effect=self.command),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def get_account(self, name):
        if name == "siteuser":
            return self.account
        if name == "apdock_1200" and self.runtime_present:
            return self.runtime_account
        raise KeyError(name)

    def get_group(self, name):
        if name == "apdock_1200" and self.runtime_present:
            return types.SimpleNamespace(gr_name=name, gr_gid=self.runtime_gid, gr_mem=[])
        raise KeyError(name)

    def manager(self, scope="root"):
        return self.helper.DockerManager(scope, "owned.example" if scope == "site" else None,
                                         "siteuser" if scope == "site" else None,
                                         str(self.home) if scope == "site" else None)

    def test_site_named_mount_is_scoped_and_legacy_bind_is_rejected(self):
        manager = self.manager("site")
        self.assertEqual(manager.validate_mount({"name": "data", "target": "/data", "readonly": True}),
                         "type=volume,src=aidipanel-1200-data,dst=/data,readonly")
        for volume in ({"source": str(self.home), "target": "/data", "readonly": False},
                       {"name": "../host", "target": "/data", "readonly": False},
                       {"name": "data", "target": "/run/docker.sock", "readonly": False}):
            with self.subTest(volume=volume), self.assertRaises(self.helper.ManagerError):
                manager.validate_mount(volume)

    def test_site_volume_requires_managed_labels_local_driver_and_no_options(self):
        manager = self.manager("site")
        volume = {"Name": "aidipanel-1200-data", "Driver": "local", "Options": None,
                  "Labels": {self.helper.MANAGED_LABEL: "true", self.helper.SCOPE_LABEL: manager.identity}}
        with mock.patch.object(manager, "docker", return_value=json.dumps([volume])):
            manager.verify_volume(volume["Name"])
        for changes in ({"Driver": "other"}, {"Options": {"device": "/etc", "o": "bind"}},
                        {"Options": ""}, {"Options": []}, {"Labels": {}}, {"Name": "unrelated"}):
            with self.subTest(changes=changes), mock.patch.object(manager, "docker", return_value=json.dumps([{**volume, **changes}])):
                with self.assertRaises(self.helper.ManagerError):
                    manager.verify_volume(volume["Name"])

    def test_site_volume_is_created_with_scope_before_inspection(self):
        manager = self.manager("site")
        with mock.patch.object(manager, "docker", return_value="aidipanel-1200-data\n") as docker, \
             mock.patch.object(manager, "verify_volume") as inspect:
            manager.prepare_volume("data")
        self.assertIn(self.helper.SCOPE_LABEL + "=" + manager.identity, docker.call_args.args[0])
        inspect.assert_called_once_with("aidipanel-1200-data")

    def test_runtime_account_is_verified_and_socket_is_separate(self):
        manager = self.manager("site")
        parent = self.directory / "runtime"
        parent.mkdir(mode=0o711)
        parent.chmod(0o711)
        home = parent / "1200"
        home.mkdir(mode=0o700)
        home.chmod(0o700)
        manager.runtime_home = home
        account = types.SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(home), pw_shell="/usr/sbin/nologin")
        with mock.patch.object(self.helper.pwd, "getpwnam", return_value=account), \
             mock.patch.object(self.helper.pwd, "getpwall", return_value=[account]), \
             mock.patch.object(self.helper.grp, "getgrall", return_value=[types.SimpleNamespace(gr_gid=account.pw_gid, gr_name="apdock_1200", gr_mem=[])]):
            manager.verify_runtime(account.pw_uid, account.pw_gid)
            self.assertEqual(manager.socket, "/run/user/" + str(account.pw_uid) + "/docker.sock")
            self.assertNotEqual(manager.runtime_uid, manager.uid)
            self.assertIn("--user apdock_1200", " ".join(manager.user_command([])))
            account.pw_shell = "/bin/bash"
            with self.assertRaises(self.helper.ManagerError):
                manager.verify_runtime(account.pw_uid, account.pw_gid)

    def inspected(self, scope="root", environment=None):
        return {
            "Id": CONTAINER_ID, "Name": "/web", "Config": {
                "Image": "nginx:alpine", "Env": environment or [],
                "Labels": {"io.aidipanel.managed": "true", "io.aidipanel.scope": "root" if scope == "root" else "site:owned.example:1200"},
            },
            "State": {"Status": "running", "Error": "must not be returned"},
            "HostConfig": {"NanoCpus": 1000000000, "Memory": 536870912, "MemorySwap": 536870912, "PidsLimit": 128},
            "NetworkSettings": {"Ports": {"80/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8080"}]}},
        }

    def command(self, arguments, input_data=b"", timeout=30, output_limit=1048576, **options):
        self.calls.append((list(arguments), input_data, timeout, output_limit))
        if arguments[0] == "/usr/sbin/useradd":
            self.runtime_present = True
        if arguments[0] == "/usr/sbin/userdel":
            self.runtime_present = False
        if "--property=ActiveState" in arguments:
            return "active\n"
        if "/usr/bin/docker" not in arguments:
            return ""
        docker_arguments = arguments[arguments.index("/usr/bin/docker") + 1:]
        if not self.available:
            raise self.helper.ManagerError("Docker command failed")
        if "info" in docker_arguments:
            return json.dumps(self.information)
        if "ps" in docker_arguments:
            return "\n".join(self.containers)
        if "volume" in docker_arguments:
            name = docker_arguments[-1]
            if "create" in docker_arguments:
                self.volumes.setdefault(name, {"Name": name, "Driver": "local", "Options": None,
                                               "Labels": {self.helper.MANAGED_LABEL: "true", self.helper.SCOPE_LABEL: "site:owned.example:1200"}})
                return name + "\n"
            if "inspect" in docker_arguments:
                return json.dumps([self.volumes[name]])
        if "inspect" in docker_arguments:
            return json.dumps([self.containers[docker_arguments[-1]]])
        if "logs" in docker_arguments:
            return self.log_output
        if "create" in docker_arguments:
            scope = "site" if "/usr/sbin/runuser" in arguments else "root"
            self.containers[CONTAINER_ID] = self.inspected(scope)
            return CONTAINER_ID + "\n"
        return ""

    def execute(self, action, payload=None, scope="root", purge=False):
        return self.manager(scope).execute(action, payload or {}, purge=purge)

    def test_unknown_keys_flags_and_nonfinite_limits_are_rejected_before_execution(self):
        cases = [
            {"privileged": True}, {"image": "--privileged"}, {"name": "bad name"},
            {"cpus": float("nan")}, {"cpus": float("inf")}, {"cpus": True},
            {"cpus": 0}, {"cpus": 33}, {"memory_mb": 0}, {"memory_mb": 65537},
            {"memory_mb": 512.5}, {"pids_limit": -1}, {"pids_limit": 4097},
            {"environment": {"TOKEN": "secret\nnext"}}, {"environment": {"BAD=KEY": "value"}},
            {"ports": [{"host": 8080, "container": 80, "ip": "0.0.0.0"}]},
            {"ports": [{"host": 0, "container": 80}]}, {"ports": [{"host": True, "container": 80}]},
            {"volumes": [{"source": str(self.root_data), "target": "/app", "readonly": "false"}]},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.calls.clear()
                with self.assertRaises(self.helper.ManagerError):
                    self.execute("create", {"name": "web", "image": "nginx:alpine", **changes})
                self.assertEqual(self.calls, [])

    def test_create_has_finite_defaults_loopback_ports_and_stdin_only_secrets(self):
        result = self.execute("create", {
            "name": "web", "image": "nginx:alpine", "environment": {"TOKEN": "top-secret"},
            "ports": [{"host": 8080, "container": 80}],
        })
        self.assertEqual(result, {"success": True, "id": CONTAINER_ID})
        command, input_data, timeout, output_limit = next(call for call in self.calls if "create" in call[0])
        self.assertIn("unix:///var/run/docker.sock", command)
        self.assertIn("127.0.0.1:8080:80/tcp", command)
        self.assertIn("--env-file", command)
        self.assertIn("/dev/stdin", command)
        self.assertEqual(input_data, b"TOKEN=top-secret\n")
        self.assertNotIn("top-secret", " ".join(command))
        self.assertIn("--cpus", command)
        self.assertIn("536870912", command)
        self.assertIn("128", command)
        self.assertLessEqual(timeout, 180)
        self.assertLessEqual(output_limit, 1048576)

    def test_site_commands_use_fixed_socket_runuser_and_clean_environment(self):
        self.enable_fixture()
        with mock.patch.dict(os.environ, {"DOCKER_HOST": "tcp://attacker:2375", "DOCKER_CONTEXT": "evil", "LD_PRELOAD": "/evil"}):
            result = self.execute("list", scope="site")
        self.assertEqual(result, {"available": True, "enabled": True, "containers": []})
        for command, input_data, timeout, output_limit in self.calls:
            self.assertEqual(command[:6], ["/usr/sbin/runuser", "--user", "apdock_1200", "--", "/usr/bin/env", "-i"])
            self.assertIn("HOME=" + str(self.storage), command)
            self.assertIn("XDG_RUNTIME_DIR=/run/user/" + str(self.runtime_uid), command)
            self.assertIn("unix:///run/user/" + str(self.runtime_uid) + "/docker.sock", command)
            self.assertNotIn("attacker", " ".join(command))

    def test_unavailable_reads_are_structured_and_do_not_provision(self):
        self.available = False
        for action in ("status", "list"):
            self.assertEqual(self.execute(action), {"available": False, "enabled": False, "containers": []})
        self.assertTrue(all("/usr/bin/docker" in call[0] for call in self.calls))

    def test_cross_scope_and_unmanaged_ids_cannot_be_used(self):
        self.enable_fixture()
        for scope in ("root", "site"):
            for action in ("start", "stop", "restart", "remove", "logs"):
                self.containers[CONTAINER_ID] = self.inspected("site" if scope == "root" else "root")
                self.calls.clear()
                with self.assertRaises(self.helper.ManagerError):
                    self.execute(action, {"id": CONTAINER_ID}, scope)
                self.assertFalse(any(action in call[0] for call in self.calls))
        self.containers[CONTAINER_ID] = self.inspected()
        self.containers[CONTAINER_ID]["Config"]["Labels"].pop("io.aidipanel.managed")
        with self.assertRaises(self.helper.ManagerError):
            self.execute("remove", {"id": CONTAINER_ID})

    def test_lifecycle_uses_verified_canonical_id_and_disallows_additional_options(self):
        self.containers[CONTAINER_ID] = self.inspected()
        for action in ("start", "stop", "restart", "remove"):
            self.assertEqual(self.execute(action, {"id": CONTAINER_ID}), {"success": True})
            self.assertEqual(self.calls[-1][0][-1], CONTAINER_ID)
        for payload in ({"id": "--all"}, {"id": "web"}, {"id": CONTAINER_ID, "force": True}):
            with self.assertRaises(self.helper.ManagerError):
                self.execute("remove", payload)

    def test_list_exposes_only_sanitized_fields_and_skips_unmanaged_containers(self):
        self.containers[CONTAINER_ID] = self.inspected(environment=["TOKEN=top-secret"])
        self.containers["b" * 64] = self.inspected("site")
        self.containers["b" * 64]["Id"] = "b" * 64
        result = self.execute("list")
        self.assertEqual(result["containers"], [{
            "id": CONTAINER_ID, "name": "web", "image": "nginx:alpine", "state": "running",
            "status": "running", "ports": [{"host": 8080, "container": 80}],
        }])
        self.assertNotIn("top-secret", json.dumps(result))
        self.assertNotIn("must not be returned", json.dumps(result))

    def test_logs_redact_environment_and_bound_tail_and_output(self):
        self.containers[CONTAINER_ID] = self.inspected(environment=["TOKEN=top-secret", "EMPTY="])
        self.log_output = "token=top-secret\n" + "line\n" * 20000
        result = self.execute("logs", {"id": CONTAINER_ID})
        self.assertNotIn("top-secret", result["logs"])
        self.assertLessEqual(len(result["logs"].encode()), 65536)
        command = self.calls[-1][0]
        self.assertIn("--tail", command)
        self.assertIn("200", command)

    def test_mounts_reject_escapes_symlinks_nested_sockets_and_special_targets(self):
        outside = self.directory / "outside"
        outside.mkdir()
        link = self.root_data / "link"
        link.symlink_to(outside, target_is_directory=True)
        valid = self.root_data / "valid"
        valid.mkdir()
        bound_socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(bound_socket.close)
        bound_socket.bind(str(valid / "api.sock"))
        for source, target in [(str(outside), "/app"), (str(link), "/app"), (str(valid), "/app"),
                               (str(self.root_data / ".." / "outside"), "/app"),
                               (str(outside), "/var/run/docker.sock")]:
            with self.subTest(source=source, target=target):
                self.calls.clear()
                with self.assertRaises(self.helper.ManagerError):
                    self.execute("create", {"name": "web", "image": "nginx", "volumes": [
                        {"source": source, "target": target, "readonly": True}]})
                self.assertEqual(self.calls, [])

    def test_valid_site_mounts_use_scoped_volumes(self):
        self.enable_fixture()
        result = self.execute("create", {"name": "web", "image": "nginx", "volumes": [
            {"name": "content", "target": "/app", "readonly": True}]}, "site")
        self.assertTrue(result["success"])
        command = next(call[0] for call in self.calls if "create" in call[0] and "volume" not in call[0])
        self.assertIn("type=volume,src=aidipanel-1200-content,dst=/app,readonly", command)

    def test_site_volume_reuse_inspects_before_each_container(self):
        self.enable_fixture()
        payload = {"name": "web", "image": "nginx", "volumes": [{"name": "data", "target": "/data", "readonly": False}]}
        self.execute("create", payload, "site")
        original_volume = self.volumes["aidipanel-1200-data"]
        self.calls.clear()
        self.execute("create", payload, "site")
        self.assertIs(self.volumes["aidipanel-1200-data"], original_volume)
        commands = [call[0] for call in self.calls]
        inspection = next(index for index, command in enumerate(commands) if "volume" in command and "inspect" in command)
        creation = next(index for index, command in enumerate(commands) if "create" in command and "volume" not in command)
        self.assertLess(inspection, creation)

    def test_site_refuses_existing_volume_with_foreign_labels_or_bind_options(self):
        self.enable_fixture()
        payload = {"name": "web", "image": "nginx", "volumes": [{"name": "data", "target": "/data", "readonly": False}]}
        for changes in ({"Labels": {self.helper.MANAGED_LABEL: "true", self.helper.SCOPE_LABEL: "site:other:1200"}},
                        {"Options": {"type": "none", "device": "/etc", "o": "bind"}}, {"Driver": "other"}):
            with self.subTest(changes=changes):
                self.volumes["aidipanel-1200-data"] = {"Name": "aidipanel-1200-data", "Driver": "local", "Options": None,
                                                        "Labels": {self.helper.MANAGED_LABEL: "true", self.helper.SCOPE_LABEL: "site:owned.example:1200"}, **changes}
                self.calls.clear()
                with self.assertRaises(self.helper.ManagerError):
                    self.execute("create", payload, "site")
                self.assertFalse(any("create" in call[0] and "volume" not in call[0] for call in self.calls))

    def test_site_container_with_host_bind_is_not_operated(self):
        self.enable_fixture()
        self.containers[CONTAINER_ID] = self.inspected("site")
        self.containers[CONTAINER_ID]["Mounts"] = [{"Type": "bind", "Source": "/etc", "Destination": "/data"}]
        for action in ("start", "restart", "logs", "remove"):
            with self.subTest(action=action), self.assertRaises(self.helper.ManagerError):
                self.execute(action, {"id": CONTAINER_ID}, "site")

    def test_rejected_create_removes_only_its_anonymous_volumes(self):
        self.enable_fixture()
        original = self.command

        def create_with_anonymous_volume(arguments, **options):
            result = original(arguments, **options)
            if "create" in arguments and "volume" not in arguments:
                self.containers[CONTAINER_ID]["Mounts"] = [{"Type": "volume", "Name": "b" * 64}]
            return result

        with mock.patch.object(self.helper, "run_command", side_effect=create_with_anonymous_volume):
            with self.assertRaises(self.helper.ManagerError):
                self.execute("create", {"name": "database", "image": "postgres"}, "site")
        cleanup = [call[0] for call in self.calls if "rm" in call[0]]
        self.assertTrue(any(command[-3:] == ["rm", "--volumes", CONTAINER_ID] for command in cleanup))
        self.assertFalse(any("prune" in call[0] or call[0][-2:] == ["volume", "rm"] for call in self.calls))

    def test_offline_disable_removes_enablement_without_starting_user_manager(self):
        self.enable_fixture()
        self.calls.clear()
        original = self.command

        def offline(arguments, **options):
            if "--property=ActiveState" in arguments:
                self.calls.append((list(arguments), b"", 30, 1048576))
                return "inactive\n"
            return original(arguments, **options)

        with mock.patch.object(self.helper, "run_command", side_effect=offline), \
             mock.patch.object(self.helper.DockerManager, "info", side_effect=self.helper.ManagerError("offline")), \
             mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            self.execute("disable", scope="site")
        commands = [call[0] for call in self.calls]
        disable = next((command for command in commands if "disable" in command), [])
        self.assertIn("SYSTEMD_OFFLINE=1", disable)
        self.assertIn("--no-reload", disable)
        self.assertNotIn("--now", disable)
        self.assertFalse(any("start" in command for command in commands))

    def test_creation_refuses_unenforceable_cgroups(self):
        self.enable_fixture()
        for changes in ({"CgroupDriver": "none"}, {"MemoryLimit": False}, {"PidsLimit": False}, {"CpuCfsQuota": False}, {"SwapLimit": False}):
            with self.subTest(changes=changes):
                self.information.update(changes)
                self.calls.clear()
                with self.assertRaisesRegex(self.helper.ManagerError, "cgroup"):
                    self.execute("create", {"name": "web", "image": "nginx"}, "site")
                self.assertFalse(any("create" in call[0] for call in self.calls))
                self.information.update({"CgroupDriver": "systemd", "MemoryLimit": True, "PidsLimit": True, "CpuCfsQuota": True, "SwapLimit": True})

    def test_creation_refuses_missing_site_cpu_controller_delegation(self):
        self.enable_fixture()
        (self.delegation / "cgroup.controllers").write_text("memory pids\n")
        with self.assertRaisesRegex(self.helper.ManagerError, "delegation"):
            self.execute("create", {"name": "web", "image": "nginx"}, "site")
        self.assertFalse(any("create" in call[0] for call in self.calls))

    def test_root_mounts_refuse_writable_ancestors(self):
        ancestor = self.root_data / "writable"
        ancestor.mkdir()
        ancestor.chmod(0o777)
        content = ancestor / "content"
        content.mkdir(mode=0o755)
        with self.assertRaises(self.helper.ManagerError):
            self.execute("create", {"name": "web", "image": "nginx", "volumes": [
                {"source": str(content), "target": "/app", "readonly": True}]})
        self.assertEqual(self.calls, [])

    def test_mounts_refuse_same_filesystem_bind_mounts_and_their_descendants(self):
        bound_directory = self.root_data / "bind"
        bound_directory.mkdir(mode=0o755)
        child = bound_directory / "content"
        child.mkdir(mode=0o755)
        self.mountinfo.write_text("123 1 0:5 /etc " + str(bound_directory) + " rw - ext4 /dev/example rw\n")
        for source in (bound_directory, child):
            with self.subTest(source=source):
                self.calls.clear()
                with self.assertRaises(self.helper.ManagerError):
                    self.execute("create", {"name": "web", "image": "nginx", "volumes": [
                        {"source": str(source), "target": "/app", "readonly": True}]})
                self.assertEqual(self.calls, [])

    def test_purge_refuses_mounted_managed_data_before_removing_any_files(self):
        self.enable_fixture()
        storage = self.storage
        (storage / "data").mkdir()
        (storage / "data/keep").write_text("persistent")
        self.mountinfo.write_text("123 1 0:5 / " + str(storage / "data") + " rw - ext4 /dev/example rw\n")
        with mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            with self.assertRaisesRegex(self.helper.ManagerError, "Unmount"):
                self.execute("disable", scope="site", purge=True)
        self.assertEqual((storage / "data/keep").read_text(), "persistent")

    def test_prerequisite_failure_reports_missing_components(self):
        with mock.patch.object(self.helper.os, "access", return_value=False):
            with self.assertRaisesRegex(self.helper.ManagerError, "prerequisites"):
                self.manager("site").prerequisites()
        self.assertEqual(self.calls, [])

    def test_ubuntu_packaged_rootlesskit_unconfined_profile_allows_prerequisites(self):
        manager = self.manager("site")
        original_read = Path.read_text
        original_stat = Path.stat
        original_exists = Path.exists

        def read_text(path, *args, **kwargs):
            if str(path) == "/proc/sys/kernel/apparmor_restrict_unprivileged_userns":
                return "1\n"
            if str(path) == "/sys/kernel/security/apparmor/profiles":
                return "rootlesskit (unconfined)\n"
            return original_read(path, *args, **kwargs)

        def stat_path(path, *args, **kwargs):
            if str(path) in ("/usr/bin/newuidmap", "/usr/bin/newgidmap"):
                return types.SimpleNamespace(st_uid=os.getuid(), st_mode=0o104755)
            return original_stat(path, *args, **kwargs)

        with mock.patch.object(self.helper.os, "access", return_value=True), \
             mock.patch.object(Path, "read_text", read_text), \
             mock.patch.object(Path, "stat", stat_path), \
             mock.patch.object(Path, "exists", lambda path: True if str(path) == "/proc/sys/kernel/apparmor_restrict_unprivileged_userns" else original_exists(path)), \
             mock.patch.object(Path, "is_dir", return_value=True), \
             mock.patch.object(self.helper, "no_symlinks"), \
             mock.patch.object(manager, "subordinate_ranges", return_value=("a", "b")):
            self.assertEqual(manager.prerequisites(), ("a", "b"))

    def test_provisioning_does_not_adopt_an_existing_daemon(self):
        self.runtime_present = True
        with mock.patch.object(self.helper.DockerManager, "prerequisites"):
            with self.assertRaisesRegex(self.helper.ManagerError, "adopt"):
                self.execute("enable", scope="site")
        self.assertEqual(self.calls, [])

    def test_enable_with_unsupported_daemon_cgroups_rolls_back_only_its_user_unit(self):
        self.information["CpuCfsQuota"] = False
        with mock.patch.object(self.helper.DockerManager, "prerequisites"), \
             mock.patch.object(self.helper.DockerManager, "subordinate_ranges", return_value=(None, None)), \
             mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            with self.assertRaisesRegex(self.helper.ManagerError, "delegation"):
                self.execute("enable", scope="site")
        self.assertTrue(any("disable" in call[0] and "aidipanel-docker-1200.service" in call[0] for call in self.calls))
        self.assertTrue(any("disable-linger" in call[0] and "apdock_1200" in call[0] for call in self.calls))
        self.assertFalse(any("docker.service" in call[0] for call in self.calls))

    def test_start_and_restart_refuse_limits_removed_after_creation(self):
        self.containers[CONTAINER_ID] = self.inspected()
        for key in ("NanoCpus", "Memory", "PidsLimit"):
            for action in ("start", "restart"):
                with self.subTest(key=key, action=action):
                    self.containers[CONTAINER_ID]["HostConfig"][key] = 0
                    self.calls.clear()
                    with self.assertRaisesRegex(self.helper.ManagerError, "resource"):
                        self.execute(action, {"id": CONTAINER_ID})
                    self.assertFalse(any(action in call[0] for call in self.calls))
                    self.containers[CONTAINER_ID] = self.inspected()

    def test_ignored_resource_limits_remove_only_the_new_managed_container(self):
        normal_command = self.command

        def ignored_limits(arguments, **options):
            output = normal_command(arguments, **options)
            if "create" in arguments:
                self.containers[CONTAINER_ID]["HostConfig"]["Memory"] = 0
            return output

        with mock.patch.object(self.helper, "run_command", side_effect=ignored_limits):
            with self.assertRaisesRegex(self.helper.ManagerError, "resource"):
                self.execute("create", {"name": "web", "image": "nginx"})
        self.assertEqual(self.calls[-1][0][-3:], ["rm", "--volumes", CONTAINER_ID])

    def test_socket_validation_rejects_symlinks_and_wrong_owners(self):
        self.enable_fixture()
        manager = self.manager("site")
        manager.runtime_record()
        self.containers[CONTAINER_ID] = self.inspected("site")
        target = self.directory / "real.sock"
        bound_socket = socket.socket(socket.AF_UNIX)
        self.addCleanup(bound_socket.close)
        bound_socket.bind(str(target))
        manager.socket = str(self.directory / "docker.sock")
        Path(manager.socket).symlink_to(target)
        with self.assertRaises(self.helper.ManagerError):
            manager.validate_socket()
        self.assertEqual(self.calls, [])
        manager.socket = str(target)
        manager.runtime_uid = 1200
        with self.assertRaises(self.helper.ManagerError):
            manager.validate_socket()
        self.assertEqual(self.calls, [])

    def test_mount_rejects_symlinked_ancestor_and_nested_file_link(self):
        content = self.root_data / "content"
        content.mkdir(mode=0o755)
        (content / "nested").symlink_to("/etc/passwd")
        with self.assertRaises(self.helper.ManagerError):
            self.execute("create", {"name": "web", "image": "nginx", "volumes": [
                {"source": str(content), "target": "/app", "readonly": True}]})
        self.assertEqual(self.calls, [])

    def test_purge_passes_pinned_parent_descriptor_to_safe_rmtree(self):
        self.enable_fixture()
        storage = self.storage
        storage.mkdir(parents=True, exist_ok=True)
        original_rmtree = self.helper.shutil.rmtree
        calls = []

        def remove_directory(path, *arguments, **options):
            calls.append((path, options.get("dir_fd")))
            return original_rmtree(path, *arguments, **options)

        remove_directory.avoids_symlink_attacks = True
        with mock.patch.object(self.helper.shutil, "rmtree", side_effect=remove_directory) as removal, \
             mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            removal.avoids_symlink_attacks = True
            self.execute("disable", scope="site", purge=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "1200")
        self.assertIsInstance(calls[0][1], int)

    def test_root_provisioning_and_purge_on_other_actions_are_rejected(self):
        for action in ("enable", "disable"):
            with self.assertRaises(self.helper.ManagerError):
                self.execute(action)
        with self.assertRaises(self.helper.ManagerError):
            self.execute("remove", {"id": CONTAINER_ID}, purge=True)
        self.assertEqual(self.calls, [])

    def test_site_mutations_and_logs_require_an_administrator_provisioned_record(self):
        self.containers[CONTAINER_ID] = self.inspected("site")
        for action in ("create", "start", "stop", "restart", "remove", "logs"):
            with self.subTest(action=action):
                self.calls.clear()
                payload = {"name": "web", "image": "nginx"} if action == "create" else {"id": CONTAINER_ID}
                with self.assertRaisesRegex(self.helper.ManagerError, "provision"):
                    self.execute(action, payload, "site")
                self.assertEqual(self.calls, [])

    def test_unprovisioned_site_reads_report_installed_disabled_without_using_any_daemon(self):
        self.containers[CONTAINER_ID] = self.inspected("site")
        with mock.patch.object(self.helper.os, "access", return_value=True):
            for action in ("status", "list"):
                self.assertEqual(self.execute(action, scope="site"), {"available": True, "enabled": False, "containers": []})
        self.assertEqual(self.calls, [])

    def test_all_site_operations_reject_mismatched_or_untrusted_runtime_records(self):
        self.enable_fixture()
        self.containers[CONTAINER_ID] = self.inspected("site")
        marker = self.state / "1200.json"
        valid_record = marker.read_text()
        for defect in ("domain", "home", "user", "uid", "unit", "runtime_user", "runtime_home", "runtime_uid", "runtime_gid", "version", "permissions", "ownership"):
            for action in ("status", "list", "create", "start", "stop", "restart", "remove", "logs"):
                with self.subTest(defect=defect, action=action):
                    marker.write_text(valid_record)
                    marker.chmod(0o600)
                    if defect == "permissions":
                        marker.chmod(0o666)
                    elif defect != "ownership":
                        record = json.loads(valid_record)
                        record[defect] = 1201 if defect in ("uid", "runtime_uid", "runtime_gid", "version") else "foreign"
                        marker.write_text(json.dumps(record))
                    metadata = marker.stat()
                    fake_metadata = types.SimpleNamespace(st_mode=metadata.st_mode, st_uid=1200 if defect == "ownership" else os.getuid())
                    self.calls.clear()
                    payload = {"name": "web", "image": "nginx"} if action == "create" else {} if action in ("status", "list") else {"id": CONTAINER_ID}
                    with mock.patch.object(self.helper.os, "fstat", return_value=fake_metadata):
                        with self.assertRaises(self.helper.ManagerError):
                            self.execute(action, payload, "site")
                    self.assertEqual(self.calls, [])

    def test_recorded_runtime_account_must_still_exist(self):
        self.enable_fixture()
        self.runtime_present = False
        for action in ("status", "create", "disable"):
            payload = {"name": "web", "image": "nginx"} if action == "create" else {}
            with self.subTest(action=action), self.assertRaises(self.helper.ManagerError):
                self.execute(action, payload, "site")
        self.assertFalse(any("userdel" in call[0] for call in self.calls))

    def test_unrecorded_runtime_account_is_not_adopted_or_removed(self):
        self.runtime_present = True
        for action in ("enable", "disable"):
            with self.subTest(action=action), self.assertRaises(self.helper.ManagerError):
                self.execute(action, scope="site")
        self.assertTrue(self.runtime_present)
        self.assertFalse(any(command[0] in ("/usr/sbin/useradd", "/usr/sbin/userdel") for command, *_ in self.calls))

    def test_unrecorded_subordinate_allocations_are_not_adopted(self):
        self.subuid.write_text("other:100000:65536\napdock_1200:300000:65536\n")
        self.subgid.write_text("other:100000:65536\napdock_1200:300000:65536\n")
        with mock.patch.object(self.helper.DockerManager, "prerequisites"):
            with self.assertRaises(self.helper.ManagerError):
                self.execute("enable", scope="site")
        self.assertFalse(any(call[0][0] == "/usr/sbin/useradd" for call in self.calls))
        self.assertEqual(self.subuid.read_text(), "other:100000:65536\napdock_1200:300000:65536\n")

    def test_all_site_operations_reject_an_unrelated_daemon_data_directory(self):
        self.enable_fixture()
        self.containers[CONTAINER_ID] = self.inspected("site")
        self.information["DockerRootDir"] = str(self.home / ".local/share/unrelated-docker")
        for action in ("status", "list", "create", "start", "stop", "restart", "remove", "logs"):
            with self.subTest(action=action):
                self.calls.clear()
                payload = {"name": "web", "image": "nginx"} if action == "create" else {} if action in ("status", "list") else {"id": CONTAINER_ID}
                with self.assertRaisesRegex(self.helper.ManagerError, "runtime"):
                    self.execute(action, payload, "site")
                self.assertTrue(all("info" in call[0] for call in self.calls))

    def test_site_actions_reject_storage_replaced_with_a_symlink_after_provisioning(self):
        self.enable_fixture()
        self.containers[CONTAINER_ID] = self.inspected("site")
        storage = self.storage
        storage.rmdir()
        outside = self.directory / "unrelated-storage"
        outside.mkdir()
        storage.symlink_to(outside, target_is_directory=True)
        for action in ("status", "list", "create", "start", "stop", "restart", "remove", "logs"):
            with self.subTest(action=action):
                self.calls.clear()
                payload = {"name": "web", "image": "nginx"} if action == "create" else {} if action in ("status", "list") else {"id": CONTAINER_ID}
                with self.assertRaises(self.helper.ManagerError):
                    self.execute(action, payload, "site")
                self.assertTrue(all("info" in call[0] for call in self.calls))

    def test_storage_preparation_rejects_wrong_runtime_home_owner(self):
        self.enable_fixture()
        manager = self.manager("site")
        manager.runtime_record()
        real_stat = Path.stat

        def wrong_owner(path, *arguments, **keywords):
            metadata = real_stat(path, *arguments, **keywords)
            if path == self.storage:
                values = list(metadata)
                values[4] = 1200
                return os.stat_result(values)
            return metadata

        with mock.patch.object(Path, "stat", wrong_owner), mock.patch.object(self.helper.os, "chown") as change_owner:
            with self.assertRaises(self.helper.ManagerError):
                manager.prepare_storage()
            self.assertFalse(change_owner.called)

    def test_storage_is_private_and_rejects_symlinks(self):
        self.enable_fixture()
        manager = self.manager("site")
        manager.runtime_record()
        home_owner = self.home.stat().st_uid
        manager.prepare_storage()
        self.assertEqual(self.home.stat().st_uid, home_owner)
        self.assertFalse((self.home / ".config/systemd/user").exists())
        outside = self.directory / "outside"
        outside.mkdir()
        self.storage.rmdir()
        self.storage.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(self.helper.ManagerError):
            manager.prepare_storage()
        self.assertEqual(list(outside.iterdir()), [])

    def test_standard_images_retain_docker_default_bounded_capabilities(self):
        self.execute("create", {"name": "web", "image": "nginx:alpine"})
        command = next(call[0] for call in self.calls if "create" in call[0])
        self.assertNotIn("--cap-drop", command)
        self.assertNotIn("--cap-add", command)
        self.assertIn("no-new-privileges=true", command)

    def test_subordinate_ranges_preserve_existing_and_allocate_disjoint_ranges(self):
        self.subuid.write_text("other:100000:65536\napdock_1200:300000:65536\n")
        self.subgid.write_text("other:200000:65536\n")
        self.assertEqual(self.manager("site").subordinate_ranges(), (None, "100000-165535"))
        self.assertEqual(self.subuid.read_text(), "other:100000:65536\napdock_1200:300000:65536\n")
        for records in ("other:100000:65536\napdock_1200:120000:65536\n",
                        "apdock_1200:100000:100\n", "other:invalid:65536\n"):
            self.subuid.write_text(records)
            with self.assertRaises(self.helper.ManagerError):
                self.manager("site").subordinate_ranges()

    def test_enable_refuses_to_start_when_subordinate_allocation_was_not_applied(self):
        with mock.patch.object(self.helper.DockerManager, "prerequisites"), \
             mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            with self.assertRaisesRegex(self.helper.ManagerError, "subordinate"):
                self.execute("enable", scope="site")
        self.assertFalse(any("enable-linger" in call[0] for call in self.calls))

    def test_enable_allocates_missing_subordinate_ids_without_overwriting_other_users(self):
        original_command = self.command

        def allocate_ids(arguments, **options):
            if arguments[0] == "/usr/sbin/usermod":
                beginning, ending = map(int, arguments[2].split("-"))
                source = self.subuid if arguments[1] == "--add-subuids" else self.subgid
                source.write_text(source.read_text() + arguments[-1] + ":" + str(beginning) + ":" + str(ending - beginning + 1) + "\n")
            return original_command(arguments, **options)

        with mock.patch.object(self.helper.DockerManager, "prerequisites"), \
             mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False), \
             mock.patch.object(self.helper, "run_command", side_effect=allocate_ids):
            self.assertEqual(self.execute("enable", scope="site"), {"success": True})
        self.assertEqual(self.subuid.read_text(), "other:100000:65536\napdock_1200:165536:65536\n")
        self.assertEqual(self.subgid.read_text(), "other:100000:65536\napdock_1200:165536:65536\n")

    def test_enable_checks_prerequisites_before_host_mutation(self):
        with mock.patch.object(self.helper.DockerManager, "prerequisites", side_effect=self.helper.ManagerError("Missing rootless prerequisites")):
            with self.assertRaisesRegex(self.helper.ManagerError, "prerequisites"):
                self.execute("enable", scope="site")
        self.assertEqual(self.calls, [])
        self.assertFalse(self.units.joinpath("aidipanel-docker-1200.service").exists())

    def test_enable_installs_dedicated_user_unit_without_changing_login_or_groups(self):
        with mock.patch.object(self.helper.DockerManager, "prerequisites"), \
             mock.patch.object(self.helper.DockerManager, "subordinate_ranges", return_value=(None, None)), \
             mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            self.assertEqual(self.execute("enable", scope="site"), {"success": True})
        unit = (self.units / "aidipanel-docker-1200.service").read_text()
        self.assertIn("ConditionUser=" + str(self.runtime_uid), unit)
        self.assertIn("Delegate=cpu memory pids", unit)
        self.assertIn("--data-root=" + str(self.storage / "data"), unit)
        self.assertIn("unix:///run/user/" + str(self.runtime_uid) + "/docker.sock", unit)
        flattened = [argument for call in self.calls for argument in call[0]]
        self.assertIn("enable-linger", flattened)
        self.assertIn("enable", flattened)
        self.assertIn("/usr/sbin/nologin", flattened)
        self.assertNotIn("--groups", flattened)
        self.assertNotIn("docker.service", flattened)
        self.assertTrue((self.state / "1200.json").is_file())
        self.assertTrue(self.storage.is_dir())

    def test_enable_waits_for_user_daemon_readiness_with_a_bounded_deadline(self):
        original_info = self.helper.DockerManager.info
        attempts = []

        def delayed_information(manager):
            attempts.append(True)
            if len(attempts) < 3:
                raise self.helper.ManagerError("Daemon is starting")
            return original_info(manager)

        with mock.patch.object(self.helper.DockerManager, "prerequisites"), \
             mock.patch.object(self.helper.DockerManager, "subordinate_ranges", return_value=(None, None)), \
             mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False), \
             mock.patch.object(self.helper.DockerManager, "info", delayed_information), \
             mock.patch.object(self.helper.time, "sleep"):
            try:
                self.assertEqual(self.execute("enable", scope="site"), {"success": True})
            except self.helper.ManagerError:
                self.fail("Enable must wait for a starting daemon rather than disabling it immediately")
        self.assertEqual(len(attempts), 3)

    def test_disable_without_managed_runtime_is_noop_only_without_socket_or_service(self):
        with mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            self.assertEqual(self.execute("disable", scope="site"), {"success": True})

    def test_disable_refuses_unrecorded_socket_without_adopting_or_stopping_it(self):
        real_lexists = self.helper.os.path.lexists
        with mock.patch.object(self.helper.os.path, "lexists", side_effect=lambda path: str(path) == "/run/user/1200/docker.sock" or real_lexists(path)):
            for purge in (False, True):
                with self.subTest(purge=purge), self.assertRaisesRegex(self.helper.ManagerError, "unrecorded"):
                    self.execute("disable", scope="site", purge=purge)
        self.assertEqual(self.calls, [])

    def test_disable_refuses_unrecorded_service_files_even_without_socket(self):
        manager = self.manager("site")
        self.units.mkdir(parents=True, exist_ok=True)
        (self.units / manager.unit).write_text("unrecorded service")
        with mock.patch.object(manager, "socket_exists", return_value=False), self.assertRaisesRegex(self.helper.ManagerError, "unrecorded"):
            manager.execute("disable", {}, purge=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.calls, [])

    def enable_fixture(self):
        with mock.patch.object(self.helper.DockerManager, "prerequisites"), \
             mock.patch.object(self.helper.DockerManager, "subordinate_ranges", return_value=(None, None)), \
             mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            self.execute("enable", scope="site")
        self.calls.clear()

    def test_disable_keeps_data_and_refuses_to_stop_unrelated_daemon_workloads(self):
        self.enable_fixture()
        storage = self.storage / "data"
        storage.mkdir(parents=True)
        (storage / "keep").write_text("persistent")
        self.containers[CONTAINER_ID] = self.inspected("site")
        self.assertEqual(self.execute("disable", scope="site"), {"success": True})
        self.assertEqual((storage / "keep").read_text(), "persistent")
        self.assertTrue(any("stop" in call[0] and CONTAINER_ID in call[0] for call in self.calls))
        self.assertTrue(any("disable" in call[0] and "aidipanel-docker-1200.service" in call[0] for call in self.calls))
        self.assertTrue(any("disable-linger" in call[0] and "apdock_1200" in call[0] for call in self.calls))
        self.assertTrue(any("stop" in call[0] and "user@" + str(self.runtime_uid) + ".service" in call[0] for call in self.calls))
        self.containers["b" * 64] = self.inspected("root")
        self.containers["b" * 64]["Id"] = "b" * 64
        self.calls.clear()
        with self.assertRaisesRegex(self.helper.ManagerError, "unmanaged"):
            self.execute("disable", scope="site")
        self.assertFalse(any("stop" in call[0] or "disable" in call[0] for call in self.calls))

    def test_disable_then_reenable_reuses_runtime_and_preserves_data(self):
        self.enable_fixture()
        (self.storage / "data").mkdir()
        (self.storage / "data" / "keep").write_text("persistent")
        original_record = (self.state / "1200.json").read_text()
        self.execute("disable", scope="site")
        self.calls.clear()
        with mock.patch.object(self.helper.DockerManager, "prerequisites"), \
             mock.patch.object(self.helper.DockerManager, "subordinate_ranges", return_value=(None, None)):
            self.execute("enable", scope="site")
        self.assertEqual((self.storage / "data" / "keep").read_text(), "persistent")
        self.assertEqual((self.state / "1200.json").read_text(), original_record)
        self.assertFalse(any(call[0][0] in ("/usr/sbin/useradd", "/usr/sbin/userdel") for call in self.calls))

    def test_explicit_purge_removes_only_managed_storage_and_unit(self):
        self.enable_fixture()
        storage = self.storage
        storage.mkdir(parents=True, exist_ok=True)
        (storage / "data").mkdir()
        (storage / "data/keep").write_text("data")
        unrelated = self.home / "unrelated"
        unrelated.mkdir()
        (unrelated / "keep").write_text("unrelated")
        with mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            self.assertEqual(self.execute("disable", scope="site", purge=True), {"success": True})
        self.assertFalse(storage.exists())
        self.assertTrue((unrelated / "keep").exists())
        self.assertFalse((self.units / "aidipanel-docker-1200.service").exists())
        self.assertEqual(self.subuid.read_text(), "other:100000:65536\n")
        commands = [call[0] for call in self.calls]
        linger_index = next(i for i, command in enumerate(commands) if "disable-linger" in command)
        stop_index = next(i for i, command in enumerate(commands) if "user@" + str(self.runtime_uid) + ".service" in command and "stop" in command)
        self.assertLess(linger_index, stop_index)
        self.assertFalse(any("--user" in command for command in commands[stop_index + 1:]))
        self.assertFalse(self.runtime_present)
        self.assertTrue(any(command == ["/usr/sbin/userdel", "apdock_1200"] for command in commands))

    def test_offline_manager_purge_skips_user_bus(self):
        self.enable_fixture()
        original = self.command
        def offline(arguments, **options):
            if "--property=ActiveState" in arguments:
                self.calls.append((list(arguments), b"", 30, 1048576))
                return "inactive\n"
            return original(arguments, **options)
        with mock.patch.object(self.helper, "run_command", side_effect=offline), \
             mock.patch.object(self.helper.DockerManager, "info", side_effect=self.helper.ManagerError("offline")), \
             mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            self.execute("disable", scope="site", purge=True)
        user_commands = [call[0] for call in self.calls if "--user" in call[0]]
        self.assertTrue(user_commands)
        self.assertTrue(all("SYSTEMD_OFFLINE=1" in command and "--no-reload" in command and "--now" not in command for command in user_commands))
        self.assertTrue(any("disable-linger" in call[0] for call in self.calls))

    def test_disable_rejects_socket_remaining_after_stop(self):
        self.enable_fixture()
        with mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=True):
            with self.assertRaisesRegex(self.helper.ManagerError, "socket"):
                self.execute("disable", scope="site")

    def test_purge_refuses_storage_symlink_without_touching_target(self):
        self.enable_fixture()
        storage = self.storage
        storage.parent.mkdir(parents=True, exist_ok=True)
        if storage.is_dir():
            storage.rmdir()
        outside = self.directory / "unrelated"
        outside.mkdir()
        (outside / "keep").write_text("safe")
        storage.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(self.helper.ManagerError):
            self.execute("disable", scope="site", purge=True)
        self.assertEqual((outside / "keep").read_text(), "safe")

    def test_purge_supports_supported_distribution_python_before_311(self):
        self.enable_fixture()
        storage = self.storage
        storage.mkdir(parents=True, exist_ok=True)
        (storage / "keep").write_text("data")
        with mock.patch.object(self.helper.sys, "version_info", (3, 10, 0)), \
             mock.patch.object(self.helper.DockerManager, "socket_exists", return_value=False):
            self.execute("disable", scope="site", purge=True)
        self.assertFalse(storage.exists())

    def test_command_runner_bounds_output_timeout_and_discards_secret_errors(self):
        runner_module = load_helper()
        for program, timeout, limit in [("import time; time.sleep(1)", 0.03, 1024),
                                        ("print('secret' * 10000)", 2, 1024),
                                        ("import sys; sys.stderr.write('secret'); sys.exit(1)", 2, 1024)]:
            with self.subTest(program=program):
                with self.assertRaises(runner_module.ManagerError) as caught:
                    runner_module.run_command(["/usr/bin/python3", "-c", program], timeout=timeout, output_limit=limit)
                self.assertNotIn("secret", str(caught.exception))

    def test_cli_rejects_bad_json_unknown_args_and_missing_identity_as_safe_json(self):
        cases = [
            (["create", "--scope", "root"], '{"image":"nginx", "environment":{"TOKEN":"secret"}, "bad":true}'),
            (["create", "--scope", "root"], '{"name":"web","name":"other","image":"nginx"}'),
            (["create", "--scope", "root"], '{"cpus":NaN}'),
            (["list", "--scope", "root", "--host", "secret"], '{}'),
            (["list", "--scope", "site"], '{}'),
            (["list", "--scope", "root"], '{"secret":"secret"}'),
        ]
        for arguments, payload in cases:
            with self.subTest(arguments=arguments, payload=payload):
                output = io.StringIO()
                with mock.patch("sys.stdin", io.StringIO(payload)), contextlib.redirect_stdout(output):
                    result = self.helper.main(arguments)
                self.assertNotEqual(result, 0)
                response = json.loads(output.getvalue())
                self.assertFalse(response["success"])
                self.assertIn("error", response)
                self.assertNotIn("secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
