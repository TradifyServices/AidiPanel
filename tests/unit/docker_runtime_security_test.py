import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest import mock


HELPER_PATH = Path(__file__).resolve().parents[2] / 'panel-app/bin/docker-manager.py'


class RuntimeSecurityTests(unittest.TestCase):
    def setUp(self):
        specification = importlib.util.spec_from_file_location('runtime_security_helper', HELPER_PATH)
        self.helper = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(self.helper)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.runtime_home = self.directory / 'runtime' / '1200'
        self.runtime_home.mkdir(parents=True, mode=0o700)
        self.runtime_home.parent.chmod(0o711)
        with mock.patch.object(self.helper.os, 'geteuid', return_value=0):
            self.manager = self.helper.DockerManager('root')
        self.manager.scope = 'site'
        self.manager.uid = 1200
        self.manager.gid = 1200
        self.manager.runtime_user = 'apdock_1200'
        self.manager.runtime_home = self.runtime_home
        self.runtime_account = types.SimpleNamespace(
            pw_uid=1900, pw_gid=1900, pw_dir=str(self.runtime_home),
            pw_shell='/usr/sbin/nologin', pw_name='apdock_1200')
        self.groups = [types.SimpleNamespace(gr_gid=1900, gr_name='apdock_1200', gr_mem=[])]

    def verify(self):
        real_stat = Path.stat

        def metadata(path, *arguments, **keywords):
            result = real_stat(path, *arguments, **keywords)
            if path == self.runtime_home:
                return types.SimpleNamespace(st_uid=1900, st_mode=result.st_mode)
            if path in self.directory.parents:
                return types.SimpleNamespace(st_uid=os.getuid(), st_mode=0o40755)
            return result

        with mock.patch.object(self.helper, 'ROOT_UID', os.getuid()), \
             mock.patch.object(self.helper.pwd, 'getpwnam', return_value=self.runtime_account), \
             mock.patch.object(self.helper.pwd, 'getpwall', return_value=[self.runtime_account]), \
             mock.patch.object(self.helper.grp, 'getgrall', return_value=self.groups), \
             mock.patch.object(Path, 'stat', metadata):
            self.manager.verify_runtime(1900, self.runtime_account.pw_gid)

    def test_private_dedicated_identity_is_accepted(self):
        self.verify()
        self.assertEqual(self.manager.runtime_uid, 1900)
        self.assertEqual(self.manager.socket, '/run/user/1900/docker.sock')

    def test_runtime_primary_group_cannot_be_site_group(self):
        self.runtime_account.pw_gid = 1200
        with self.assertRaises(self.helper.ManagerError):
            self.verify()

    def test_runtime_primary_group_cannot_be_shared_under_another_name(self):
        self.groups.append(types.SimpleNamespace(gr_gid=1900, gr_name='sitegroup', gr_mem=[]))
        with self.assertRaises(self.helper.ManagerError):
            self.verify()

    def test_runtime_ancestor_cannot_be_mutable_by_site_processes(self):
        self.directory.chmod(0o777)
        with self.assertRaises(self.helper.ManagerError):
            self.verify()

    def test_volume_inspection_rejects_non_object_driver_options(self):
        self.manager.identity = 'site:owned.example:1200'
        volume = {'Name': 'aidipanel-1200-data', 'Driver': 'local', 'Options': '',
                  'Labels': {self.helper.MANAGED_LABEL: 'true', self.helper.SCOPE_LABEL: self.manager.identity}}
        with mock.patch.object(self.manager, 'docker', return_value=json.dumps([volume])):
            with self.assertRaises(self.helper.ManagerError):
                self.manager.verify_volume(volume['Name'])

    def test_site_actions_share_lifecycle_lock_before_dispatch(self):
        for action in ('status', 'create', 'disable'):
            with self.subTest(action=action):
                events = []
                with mock.patch.object(self.helper, 'ROOT_UID', os.getuid()), \
                     mock.patch.object(self.helper, 'STATE_DIR', self.directory / 'state'), \
                     mock.patch.object(self.helper.fcntl, 'flock', side_effect=lambda *args: events.append('lock')), \
                     mock.patch.object(self.manager, '_execute', side_effect=lambda *args: events.append('dispatch'), create=True):
                    self.manager.execute(action, {})
                self.assertEqual(events[:2], ['lock', 'dispatch'])

    @unittest.skipUnless(shutil.which('systemctl'), 'systemd client is not installed')
    def test_systemd_offline_disable_only_changes_temporary_enablement_links(self):
        for name in ('units', 'config', 'home', 'run'):
            (self.directory / name).mkdir()
        unit = 'aidipanel-offline-fixture.service'
        (self.directory / 'units' / unit).write_text(
            '[Service]\nType=oneshot\nExecStart=/usr/bin/true\n[Install]\nWantedBy=default.target\n')
        environment = {
            'PATH': '/usr/bin:/bin', 'HOME': str(self.directory / 'home'),
            'XDG_CONFIG_HOME': str(self.directory / 'config'),
            'XDG_RUNTIME_DIR': str(self.directory / 'run'),
            'DBUS_SESSION_BUS_ADDRESS': 'unix:path=' + str(self.directory / 'no-bus'),
            'SYSTEMD_UNIT_PATH': str(self.directory / 'units'), 'SYSTEMD_OFFLINE': '1',
        }
        link = self.directory / 'config/systemd/user/default.target.wants' / unit
        for operation in ('enable', 'disable'):
            result = subprocess.run([shutil.which('systemctl'), '--user', '--no-reload', operation, unit],
                                    env=environment, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(link.is_symlink(), operation == 'enable')


if __name__ == '__main__':
    unittest.main()
