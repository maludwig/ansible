#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2018, Mitchell Ludwig <mitchell.ludwig@gmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import print_function
import json

import datetime

from ansible.compat.tests.mock import patch, Mock
from ansible.module_utils import basic
from ansible.modules.packaging.os import osx_pkg_installer

from units.modules.utils import AnsibleExitJson, AnsibleFailJson, ModuleTestCase, set_module_args


def exit_json(*args, **kwargs):
    """function to patch over exit_json; package return data into an exception"""
    if 'changed' not in kwargs:
        kwargs['changed'] = False
    raise AnsibleExitJson(kwargs)


def fail_json(*args, **kwargs):
    """function to patch over fail_json; package return data into an exception"""
    kwargs['failed'] = True
    raise AnsibleFailJson(kwargs)


def get_bin_path(self, arg, required=False):
    """Mock AnsibleModule.get_bin_path"""
    if arg.endswith('pkgutil'):
        return '/booga/pkgutil'
    elif arg.endswith('installer'):
        return '/booga/installer'
    else:
        if required:
            fail_json(msg='%r not found !' % arg)


def run_command(*args, **kwargs):
    pass


INSTALLER_SUCCESSFUL_OUT = """
installer: Package name is 1Password
installer: Installing at base path /Users/mitchell.ludwig
installer: The install was successful.
"""

JDK_PKG_INFO = """
package-id: com.oracle.jdk-9.0.4
version: 1.1
volume: /
location: Library/Java/JavaVirtualMachines/jdk-9.0.4.jdk
install-time: 1520292242
"""

JDK_ID = 'com.oracle.jdk-9.0.4'

ORIGINAL_PKGS = """
com.apple.pkg.OSX_10_13_IncompatibleAppList.16U1254
com.apple.pkg.DevSDK_macOS1013_Public
com.apple.pkg.XProtectPlistConfigData.16U4027
com.apple.pkg.CLTools_Executables
net.pulsesecure.TnccPlugin.pkg
com.oracle.jdk8u152
"""

FINAL_PKGS = """
com.reddit.sdk
com.apple.pkg.OSX_10_13_IncompatibleAppList.16U1254
com.apple.pkg.DevSDK_macOS1013_Public
com.apple.pkg.XProtectPlistConfigData.16U4027
com.apple.pkg.CLTools_Executables
com.oracle.jdk-9.0.4
net.pulsesecure.TnccPlugin.pkg
com.oracle.jdk8u152
com.oracle.jdk-9.0.1
"""

EXPECTED_NEW_PKGS = [
    "com.reddit.sdk",
    "com.oracle.jdk-9.0.4",
    "com.oracle.jdk-9.0.1",
]


class TestOSXPkgInstaller(ModuleTestCase):

    def setUp(self):
        self.mock_module = patch.multiple(basic.AnsibleModule,
                                          exit_json=exit_json,
                                          fail_json=fail_json,
                                          get_bin_path=get_bin_path,
                                          run_command=run_command)
        self.mock_module.start()
        self.addCleanup(self.mock_module.stop)

    def test_module_fail_when_required_args_missing(self):
        with self.assertRaises(AnsibleFailJson):
            set_module_args({})
            osx_pkg_installer.main()

    def test_run_command_logs_output(self):
        stdout = 'asdf'
        stderr = 'fdsa'
        rc = 0
        verbose_result = dict()
        mock_module = Mock()
        mock_module.run_command.return_value = rc, stdout, stderr
        osx_pkg_installer.run_command(mock_module, verbose_result, ['echo', 'asdf'])
        mock_module.run_command.assert_called_once_with(['echo', 'asdf'], check_rc=True)
        self.assertEqual(len(verbose_result['commands']), 1)
        for timestamp in verbose_result['commands']:
            exec_result = verbose_result['commands'][timestamp]
            self.assertEqual(exec_result['rc'], 0)
            self.assertEqual(exec_result['stdout'], 'asdf')
            self.assertEqual(exec_result['stderr'], 'fdsa')

    def test_parsing(self):
        version = osx_pkg_installer.parse_out('version', JDK_PKG_INFO)
        self.assertEqual('1.1', version)
        package_id = osx_pkg_installer.parse_out('package-id', JDK_PKG_INFO)
        self.assertEqual(JDK_ID, package_id)

    def test_parse_pkg_info(self):
        info = osx_pkg_installer.parse_pkg_info(JDK_PKG_INFO)
        self.assertEqual(info, {
            'install_datetime': datetime.datetime(2018, 3, 5, 16, 24, 2),
            'install_timestamp': 1520292242,
            'location': 'Library/Java/JavaVirtualMachines/jdk-9.0.4.jdk',
            'package_id': JDK_ID,
            'root_dir': '/Library/Java/JavaVirtualMachines/jdk-9.0.4.jdk',
            'version': '1.1',
            'volume': '/'
        })

    def test_pkg_info_with_jdk_present(self):
        stdout = JDK_PKG_INFO
        stderr = ''
        rc = 0
        result = dict()
        verbose_result = dict()
        mock_module = Mock()
        mock_module.run_command.return_value = rc, stdout, stderr
        osx_pkg_installer.pkg_info(mock_module, result, verbose_result, JDK_ID, '/')
        mock_module.run_command.assert_called_once_with(
            ['/usr/sbin/pkgutil', '--pkg-info', JDK_ID, '--volume', '/'], check_rc=False)
        self.assertEqual(len(verbose_result['commands']), 1)
        for timestamp in verbose_result['commands']:
            exec_result = verbose_result['commands'][timestamp]
            self.assertEqual(exec_result['rc'], rc)
            self.assertEqual(exec_result['stdout'], stdout)
            self.assertEqual(exec_result['stderr'], stderr)
        self.assertEqual(result['pkg_info'], {
            'install_datetime': datetime.datetime(2018, 3, 5, 16, 24, 2),
            'install_timestamp': 1520292242,
            'location': 'Library/Java/JavaVirtualMachines/jdk-9.0.4.jdk',
            'package_id': JDK_ID,
            'root_dir': '/Library/Java/JavaVirtualMachines/jdk-9.0.4.jdk',
            'state': 'present',
            'version': '1.1',
            'volume': '/'
        })

    def test_pkg_info_with_jdk_absent(self):
        stdout = ''
        stderr = "No receipt for 'com.oracle.jdk-9.0.4' found at '/'."
        rc = 1
        result = dict()
        verbose_result = dict()
        mock_module = Mock()
        mock_module.run_command.return_value = rc, stdout, stderr
        osx_pkg_installer.pkg_info(mock_module, result, verbose_result, JDK_ID, '/')
        mock_module.run_command.assert_called_once_with(
            ['/usr/sbin/pkgutil', '--pkg-info', JDK_ID, '--volume', '/'], check_rc=False)
        self.assertEqual(len(verbose_result['commands']), 1)
        for timestamp in verbose_result['commands']:
            exec_result = verbose_result['commands'][timestamp]
            self.assertEqual(exec_result['rc'], rc)
            self.assertEqual(exec_result['stdout'], stdout)
            self.assertEqual(exec_result['stderr'], stderr)
        self.assertEqual(result['pkg_info'], {'state': 'absent'})

    def test_parse_package_files(self):
        files = osx_pkg_installer.parse_package_files(
            '/',
            '\na\ns/\nd\nf\nApplications/1Password.app/Config/info.plist\n'
        )
        self.assertEqual(files, ['/a', '/s/', '/d', '/f', '/Applications/1Password.app/Config/info.plist'])
        files = osx_pkg_installer.parse_package_files(
            '/Users/mitchell.ludwig',
            'a\ns/\nd\nf\nApplications/1Password.app/Config/info.plist'
        )
        self.assertEqual(files, [
            '/Users/mitchell.ludwig/a',
            '/Users/mitchell.ludwig/s/',
            '/Users/mitchell.ludwig/d',
            '/Users/mitchell.ludwig/f',
            '/Users/mitchell.ludwig/Applications/1Password.app/Config/info.plist'
        ])

    def test_package_files(self):
        stdout = 'settings.plist\nContents/Home/lib/modules\nContents/Home/lib/security/public_suffix_list.dat\n'
        stderr = ""
        rc = 0
        result = dict()
        verbose_result = dict()
        mock_module = Mock()
        mock_module.run_command.return_value = rc, stdout, stderr

        # with patch.object('ansible.modules.packaging.os.osx_pkg_installer.pkg_info', )
        with patch.object(osx_pkg_installer, 'pkg_info') as pkg_info:
            pkg_info.return_value = {
                'install_datetime': datetime.datetime(2018, 3, 5, 16, 24, 2),
                'install_timestamp': 1520292242,
                'location': 'Library/Java/JavaVirtualMachines/jdk-9.0.4.jdk',
                'package_id': JDK_ID,
                'root_dir': '/Library/Java/JavaVirtualMachines/jdk-9.0.4.jdk',
                'state': 'present',
                'version': '1.1',
                'volume': '/'
            }
            files = osx_pkg_installer.package_files(mock_module, result, verbose_result, JDK_ID, '/')
        self.assertEqual(files, [
            '/Library/Java/JavaVirtualMachines/jdk-9.0.4.jdk/settings.plist',
            '/Library/Java/JavaVirtualMachines/jdk-9.0.4.jdk/Contents/Home/lib/modules',
            '/Library/Java/JavaVirtualMachines/jdk-9.0.4.jdk/Contents/Home/lib/security/public_suffix_list.dat'
        ])

    def test_is_present_with_jdk_present(self):
        stdout = JDK_PKG_INFO
        stderr = ""
        rc = 0
        result = dict()
        verbose_result = dict()
        mock_module = Mock()
        mock_module.run_command.return_value = rc, stdout, stderr

        creates = '/Applications/Java9'
        present = osx_pkg_installer.is_present(mock_module, result, verbose_result, creates, JDK_ID, '/')
        mock_module.run_command.assert_called_once_with(
            ['/usr/sbin/pkgutil', '--pkg-info', JDK_ID, '--volume', '/'],
            check_rc=False
        )
        self.assertTrue(present)

    def test_is_present_with_jdk_absent(self):
        stdout = ''
        stderr = "No receipt for 'com.oracle.jdk-9.0.4' found at '/'."
        rc = 1
        result = dict()
        verbose_result = dict()
        mock_module = Mock()
        mock_module.run_command.return_value = rc, stdout, stderr

        creates = '/Applications/Java9'
        present = osx_pkg_installer.is_present(mock_module, result, verbose_result, creates, JDK_ID, '/')
        mock_module.run_command.assert_called_once_with(
            ['/usr/sbin/pkgutil', '--pkg-info', JDK_ID, '--volume', '/'],
            check_rc=False
        )
        self.assertFalse(present)

    def test_is_present_with_creates(self):

        result = dict()
        verbose_result = dict()
        mock_module = Mock()

        creates = '/this/path/does/not/and/will/never/exist'
        present = osx_pkg_installer.is_present(mock_module, result, verbose_result, creates, None, '/')
        self.assertFalse(present)

        creates = '/Users'
        present = osx_pkg_installer.is_present(mock_module, result, verbose_result, creates, None, '/')
        self.assertTrue(present)

    def test_list_all_packages(self):
        stdout = ORIGINAL_PKGS
        stderr = ""
        rc = 0
        result = dict()
        verbose_result = dict()
        mock_module = Mock()
        mock_module.run_command.return_value = rc, stdout, stderr

        original_packages = osx_pkg_installer.list_all_packages(mock_module, result, verbose_result, '/')
        mock_module.run_command.assert_called_once_with(['/usr/sbin/pkgutil', '--pkgs', '--volume', '/'])
        self.assertEqual([
            'com.apple.pkg.OSX_10_13_IncompatibleAppList.16U1254',
            'com.apple.pkg.DevSDK_macOS1013_Public',
            'com.apple.pkg.XProtectPlistConfigData.16U4027',
            'com.apple.pkg.CLTools_Executables',
            'net.pulsesecure.TnccPlugin.pkg',
            'com.oracle.jdk8u152'
        ], original_packages)

    def test_find_new_packages(self):
        stdout = FINAL_PKGS
        stderr = ""
        rc = 0
        result = dict()
        verbose_result = dict()
        mock_module = Mock()
        mock_module.run_command.return_value = rc, stdout, stderr

        original_packages = [
            'com.apple.pkg.OSX_10_13_IncompatibleAppList.16U1254',
            'com.apple.pkg.DevSDK_macOS1013_Public',
            'com.apple.pkg.XProtectPlistConfigData.16U4027',
            'com.apple.pkg.CLTools_Executables',
            'net.pulsesecure.TnccPlugin.pkg',
            'com.oracle.jdk8u152'
        ]

        new_packages = osx_pkg_installer.find_new_packages(mock_module, result, verbose_result, '/', original_packages)
        mock_module.run_command.assert_called_once_with(['/usr/sbin/pkgutil', '--pkgs', '--volume', '/'])

        self.assertEqual(
            set(['com.reddit.sdk', 'com.oracle.jdk-9.0.1', 'com.oracle.jdk-9.0.4']),
            set(new_packages)
        )

    # def test_run_command(self):
    #     with patch.object(basic.AnsibleModule, 'run_command') as mock_run_command:
    #         stdout = 'asdf'
    #         stderr = 'fdsa'
    #         rc = 0
    #         mock_run_command.return_value = rc, stdout, stderr  # successful execution
    #         osx_pkg_installer.run_command()
    #         with self.assertRaises(AnsibleExitJson) as result_ex:
    #             osx_pkg_installer.main()
    #         result = result_ex.exception.args[0]
    #         self.assertFalse(result['changed'])  # ensure result is changed
    #
    #     mock_run_command.assert_called_once_with('/usr/bin/my_command --value 10 --name test')


'''

# Install a pkg that does not create an app. Without app or creates, this will always be "changed".
- name: Install the JDK poorly
  become: true
  osx_pkg_installer:
    app_name: JDK 9.0.1
    pkg_path: "/Users/mitchell.ludwig/Downloads/JDK 9.0.1.pkg"
    state: present
    
# Install a pkg only if the file/folder it creates does not exist.
- name: Install the JDK properly
  become: true
  osx_pkg_installer:
    app_name: JDK 9.0.1
    pkg_path: "/Users/mitchell.ludwig/Downloads/JDK 9.0.1.pkg"
    creates: "/Library/Java/JavaVirtualMachines/jdk-9.0.1.jdk"

# Install this pkg as root, only if /Applications/1Password 6.app does not exist
- become: true
  osx_pkg_installer:
    app_name: 1Password 6
    pkg_path: "/Volumes/USBSTIK/1Password-6.8.7.pkg"
    
# Install this pkg, for this user only, only if ~/Applications/1Password 6.app does not exist
- osx_pkg_installer:
    app_name: 1Password 6
    pkg_path: "/Volumes/USBSTIK/1Password-6.8.7.pkg"

# Install this pkg as root, only if "pkgutil --pkgs" does not contain a match for the package_id.
- become: true
  osx_pkg_installer:
    app_name: 1Password 6
    pkg_path: "/Volumes/USBSTIK/1Password-6.8.7.pkg"
    package_id: com.agilebits.pkg.onepassword
    
# Uninstall this pkg as root, if "pkgutil --pkgs" contains the package_id.
- become: true
  osx_pkg_installer:
    app_name: 1Password 6
    package_id: com.agilebits.pkg.onepassword
    state: absent
    
    '''
