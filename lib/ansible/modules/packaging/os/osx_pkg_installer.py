#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2018, Mitchell Ludwig <mitchell.ludwig@gmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import print_function

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community'
}

DOCUMENTATION = '''
---
module: osx_pkg_installer

short_description: Wrapper for OSX "installer" utility for installing .pkg files

version_added: "2.6"

description:
    - "This module provides a clean way to manage the installation of pkg files into OSX.
       Before using this module, consider the M(homebrew) or M(homebrew_cask) modules. Homebrew is better, but
       this is for when the package is not on homebrew. Or for when you disagree that homebrew
       is better, and just want to use pkg files. You do you."

options:
    app_name:
        description:
            - The name of the Application. See C(creates). 
        required: true
    pkg_path:
        description:
            - The path to a .pkg file to install.
        required: false
    state:
        description:
            - If C(present), unpack the package unless it exists (see app_name, creates, package_id). 
            - "If C(absent), if the .app the package creates exists, move it to the trash. 
               Override with the 'creates' option. Removing pkg files automatically is dangerous."
        choices: [ absent, present ]
        default: present
    creates:
        description:
            - "On state: present, this is a file or directory name, 
               when it already exists, this step will not be run."
            - "On state: absent, this is a file or directory name to delete, 
               if it does not exist, this step will not be run."
        default:
            - "If running with target: /, C(/Applications/$APP_NAME.app)"
            - "If running with target: CurrentUserHomeDirectory, C($HOME/Applications/$APP_NAME.app)"
        required: false
    target:
        description:
            - "The path to install the package to. 
               Defaults to C(/) when run as root. Applications are available to all users.
               Defaults to C(CurrentUserHomeDirectory) when run as user. Applications are available to current user."
        default:
            - "If running as root: C(/)"
            - "If running as unprivileged user: C(CurrentUserHomeDirectory)"
        required: false
    package_id:
        desription:
            - "A package-id to check for with C(pkgutil --pkg-info $package_id [--volume ~])"
            - "If state:present, if the package-id exists on the system, this step will be skipped"
            - "If state:absent, C(pkgutil --pkg-info $package_id) and C(pkgutil --files $package_id) will be used to
               enumerate the files to delete, and C(pkgutil --forget $package_id)."
        required: false
    confident_to_remove:
        description:
            - If set to C(yes), then it will actually delete all of the package files
            - If set to C(no), then it will list all of the package files that it would delete, then fail
        type: bool
        default: no

notes:
   - To explore your installed packages, look at the command line utilities C(pkgutil) and C(installer).
   - To see if it is safe to uninstall your package, use C(pkgutil --pkgs [--volume ~]) to find your package_id. 
     Then use C(pkgutil --pkg-info $package_id [--volume ~]) to find out where the package is installed. 
     Then use C(pkgutil --files $package_id [--volume ~]) to enumerate all the files of the package.
     Then make a decision with your brain if you really should delete the thing.
     Keep in mind that some things depend on other things and you could ruin other software if you
     wander around deleting dependencies.
author:
    - Mitchell Ludwig (@maludwig)
'''

EXAMPLES = '''
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

# TODO: Specify return params
RETURN = '''
message:
    description: mitchell is a fuckwit who forgot this
    type: str
'''

import os
import re
import datetime
import shutil
from ansible.module_utils.basic import AnsibleModule


class PkgException(Exception):
    pass


def gen_timestamp():
    return datetime.datetime.utcnow().isoformat()


def run_command(module, verbose_result, command_list, check_rc=True):
    rc, out, err = module.run_command(command_list, check_rc=check_rc)
    if 'commands' not in verbose_result:
        verbose_result['commands'] = dict()
    verbose_result['commands'][gen_timestamp()] = dict(
        command_list=command_list,
        check_rc=check_rc,
        rc=rc,
        stdout=out,
        stderr=err,
    )
    return rc, out, err


def parse_out(key, std_out):
    regex = r'[\s\S]*' + key + r': (.*)'
    match = re.match(regex, std_out)
    if match:
        return match.group(1)
    else:
        raise PkgException("Key not found in output.", key, std_out)


def parse_pkg_info(std_out):
    install_timestamp = int(parse_out('install-time', std_out))
    volume = parse_out('volume', std_out)
    location = parse_out('location', std_out)
    return dict(
        package_id=parse_out('package-id', std_out),
        version=parse_out('version', std_out),
        volume=volume,
        location=location,
        # join cannot merge absolute dirs join('/foo','/')=='/'
        root_dir=os.path.realpath(volume + '/' + location),
        install_timestamp=install_timestamp,
        install_datetime=datetime.datetime.fromtimestamp(install_timestamp),
    )


def pkg_info(module, result, verbose_result, package_id, volume):
    rc, out, err = run_command(
        module,
        verbose_result,
        ['/usr/sbin/pkgutil', '--pkg-info', package_id, '--volume', volume],
        check_rc=False,
    )
    if rc == 0:
        result['pkg_info'] = parse_pkg_info(out)
        result['pkg_info']['state'] = 'present'
    else:
        result['pkg_info'] = dict(
            state='absent',
            # out=out.split("\n"),
            # err=err.split("\n"),
            # rc=rc,
        )
    return result['pkg_info']


def parse_package_files(root_dir, std_out):
    files = []
    for path_tail in std_out.split('\n'):
        # Protect poor end users from accidentally deleting their
        # /, /Applications, and
        # ~, ~/Applications directories
        if path_tail != '' and path_tail != 'Applications':
            files.append(os.path.join(root_dir, path_tail))
    return files


def package_files(module, result, verbose_result, package_id, volume):
    info = pkg_info(module, result, verbose_result, package_id, volume)

    command_list = ['/usr/sbin/pkgutil', '--files', package_id, '--volume', volume]
    rc, out, err = run_command(module, verbose_result, command_list)
    result['pkg_files'] = parse_package_files(info['root_dir'], out)
    return result['pkg_files']

def forget_package(module, result, verbose_result, package_id, volume):

    command_list = ['/usr/sbin/pkgutil', '--forget', package_id, '--volume', volume]
    rc, out, err = run_command(module, verbose_result, command_list)
    result['forget'] = rc, out, err
    return result['forget']

def is_present(module, result, verbose_result, creates, package_id, volume):
    if package_id is not None:
        info = pkg_info(module, result, verbose_result, package_id, volume)
        found_package_id = info['state'] == 'present'
        return found_package_id
    else:
        creates_exists = os.path.exists(creates)
        return creates_exists


def install(module, result, verbose_result, pkg_path, target):
    real_pkg_path = os.path.realpath(pkg_path)
    if not os.path.isfile(real_pkg_path):
        raise PkgException('pkg file not found at %s' % real_pkg_path)

    rc, out, err = run_command(
        module, verbose_result,
        ['/usr/sbin/installer', '-pkg', pkg_path, '-target', target]
    )


def uninstall(module, result, verbose_result, package_id, volume):
    files = package_files(module, result, verbose_result, package_id, volume)
    verbose_result['files'] = files
    verbose_result['removal'] = []
    for file_path in files:
        if os.path.isdir(file_path):
            verbose_result['removal'].append("Removing directory: %s" % file_path)
            shutil.rmtree(file_path)
        elif os.path.isfile(file_path):
            verbose_result['removal'].append("Removing file: %s" % file_path)
            os.remove(file_path)
    forget_package(module, result, verbose_result, package_id, volume)
    # raise PkgException("Not implemented")


def list_all_packages(module, result, verbose_result, volume):
    rc, out, err = module.run_command(['/usr/sbin/pkgutil', '--pkgs', '--volume', volume])
    verbose_result['all_packages'] = dict(
        rc=rc,
        std_out=out,
        std_err=err,
    )
    if not rc == 0:
        raise PkgException('installer failed', rc, out, err)
    if 'installed_packages' not in result:
        result['installed_packages'] = dict()

    package_list = out.strip().split('\n')
    result['installed_packages'][gen_timestamp()] = package_list
    return package_list


def find_new_packages(module, result, verbose_result, volume, original_package_list):
    new_package_list = list_all_packages(module, result, verbose_result, volume)
    result['new_packages'] = list(set(new_package_list) - set(original_package_list))
    return result['new_packages']


def run_module():
    module_args = dict(
        app_name=dict(type='str', required=True),
        pkg_path=dict(type='str', required=False, default=''),
        creates=dict(type='str', required=False),
        state=dict(type='str', required=False, choices=['present', 'absent'], default='present'),
        target=dict(type='str', required=False),
        package_id=dict(type='str', required=False),
        confident_to_remove=dict(type='bool', default=False),
    )

    verbose_result = dict()

    module = AnsibleModule(
        argument_spec=module_args,
        supports_check_mode=True
    )

    result = dict(
        changed=False,
        message='',
    )

    messages = []

    is_root = os.geteuid() == 0

    app_name = module.params['app_name']
    pkg_path = module.params['pkg_path']
    creates = module.params['creates']
    state = module.params['state']
    target = module.params['target']
    package_id = module.params['package_id']
    confident_to_remove = module.params['confident_to_remove']

    should_be_present = state == 'present'
    verbose_result['should_be_present'] = should_be_present

    # Setup defaults
    if is_root:
        volume = '/'
        messages.append('Running as root')
        if target is None:
            target = '/'
    else:
        volume = os.path.expanduser('~')
        messages.append('Running as unprivileged user')
        if target is None:
            target = 'CurrentUserHomeDirectory'
    if creates is None:
        creates = os.path.join(volume, 'Applications', '%s.app' % app_name)

    verbose_result['creates'] = creates
    verbose_result['target'] = target
    verbose_result['volume'] = volume

    try:
        if state == 'present':
            if pkg_path is None:
                raise PkgException("Missing pkg_path when state is present")

        if state == 'absent':
            if package_id is None:
                raise PkgException("Missing package_id when state is absent")

        original_package_list = list_all_packages(module, result, verbose_result, volume)
        verbose_result['original_package_list'] = original_package_list

        originally_present = is_present(module, result, verbose_result, creates, package_id, volume)
        verbose_result['originally_present'] = originally_present

        result['changed'] = originally_present != should_be_present
        # module.fail_json(msg=str("Debug"), **module.params)

        if module.check_mode:
            messages.append('Checking for %s for pkg at %s' % (app_name, pkg_path))
        else:
            messages.append('Running for %s for pkg at %s' % (app_name, pkg_path))
            if should_be_present:

                if not originally_present:
                    install(module, result, verbose_result, pkg_path, target)
            else:

                if originally_present:
                    files = package_files(module, result, verbose_result, package_id, volume)
                    verbose_result['files'] = files
                    if confident_to_remove:
                        uninstall(module, result, verbose_result, package_id, volume)

                    else:
                        result['files'] = files
                        raise PkgException('Not confident_to_remove this package',
                                           'Review the files and become confident to continue')

        verbose_result['messages'] = '. '.join(messages)

        if module._verbosity > 0:
            result.update(verbose_result)
        module.exit_json(**result)
    # except PkgException as e:
    except Exception as e:
        result['error'] = e.args
        if module._verbosity > 0:
            result.update(verbose_result)
        module.fail_json(msg=str(e), **result)


def main():
    run_module()


if __name__ == '__main__':
    main()
