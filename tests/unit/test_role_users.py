from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import subprocess
import sys

import pytest

COLLECTION_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

# Stands in for ctrliq.ascender.user so the users role can run without a controller.
# It accepts what the role passes and reports whether a password reached the module.
STUB_USER_MODULE = '''
from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(
        argument_spec=dict(
            username=dict(), new_username=dict(), password=dict(no_log=True), email=dict(),
            first_name=dict(), last_name=dict(), is_superuser=dict(type='bool'),
            is_system_auditor=dict(type='bool'), update_secrets=dict(type='bool', no_log=False),
            organization=dict(), preferred_language=dict(), preferred_theme=dict(), state=dict(),
            controller_host=dict(), controller_username=dict(), controller_password=dict(no_log=True),
            controller_oauthtoken=dict(no_log=True), request_timeout=dict(), validate_certs=dict(type='bool'),
            controller_config_file=dict(),
        ),
        supports_check_mode=True,
    )
    password = module.params['password']
    module.exit_json(changed=False, password_sent=password is not None, password_is_change_me=password == 'change_me')


if __name__ == '__main__':
    main()
'''

PLAYBOOK = '''
- hosts: localhost
  connection: local
  gather_facts: false
  roles:
    - ctrliq.ascender.users
  post_tasks:
    - ansible.builtin.assert:
        that: __controller_user_accounts_job_async.results | map(attribute='password_sent') | list == expected_password_sent
        fail_msg: "password_sent per entry: {{ __controller_user_accounts_job_async.results | map(attribute='password_sent') | list }}"
    - ansible.builtin.assert:
        that: __controller_user_accounts_job_async.results | selectattr('password_is_change_me') | list | length == 0
        fail_msg: an entry was sent the password change_me
'''


@pytest.fixture
def run_users_role(tmp_path):
    """Run the users role from this checkout in check mode, against a stub user module."""
    collection = tmp_path / 'ansible_collections' / 'ctrliq' / 'ascender'
    (collection / 'plugins' / 'modules').mkdir(parents=True)
    (collection / 'plugins' / 'modules' / 'user.py').write_text(STUB_USER_MODULE)
    os.symlink(os.path.join(COLLECTION_ROOT, 'roles'), str(collection / 'roles'))
    os.symlink(os.path.join(COLLECTION_ROOT, 'meta'), str(collection / 'meta'))
    playbook = tmp_path / 'playbook.yml'
    playbook.write_text(PLAYBOOK)

    def run(extra_vars):
        extra_vars = dict(extra_vars, controller_configuration_users_secure_logging=False, ansible_python_interpreter=sys.executable)
        vars_file = tmp_path / 'vars.json'
        vars_file.write_text(json.dumps(extra_vars))
        env = dict(
            os.environ,
            ANSIBLE_COLLECTIONS_PATH=str(tmp_path),
            ANSIBLE_COLLECTIONS_SCAN_SYS_PATH='false',
            ANSIBLE_LOCAL_TEMP=str(tmp_path / 'tmp'),
            ANSIBLE_NOCOLOR='true',
        )
        cmd = [sys.executable, '-m', 'ansible.cli.playbook', '--check', '-i', 'localhost,', '-e', '@' + str(vars_file), str(playbook)]
        return subprocess.run(cmd, env=env, cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, check=False)

    return run


def test_users_role_sends_no_password_when_none_declared(run_users_role):
    """An entry without a password must not be given one, or update_secrets writes it over the existing password."""
    result = run_users_role(dict(controller_user_accounts=[dict(username='svc-ci')], expected_password_sent=[False]))
    assert result.returncode == 0, result.stdout


def test_users_role_sends_a_declared_password(run_users_role):
    accounts = [dict(username='jsmith', password='p4ssword'), dict(username='svc-ci')]
    result = run_users_role(dict(controller_user_accounts=accounts, expected_password_sent=[True, False]))
    assert result.returncode == 0, result.stdout


def test_users_role_applies_an_explicit_default_password(run_users_role):
    """Setting controller_user_default_password still applies it to entries without their own."""
    result = run_users_role(dict(controller_user_accounts=[dict(username='svc-ci')], controller_user_default_password='s3cret', expected_password_sent=[True]))
    assert result.returncode == 0, result.stdout
