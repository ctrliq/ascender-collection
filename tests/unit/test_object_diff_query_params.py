from __future__ import absolute_import, division, print_function

__metaclass__ = type

# The object_diff role's list fetches, rendered by ansible-playbook against a stub controller_api lookup that
# records the query_params it receives. No controller or database is involved.

import json
import os
import subprocess
import sys
import textwrap

import pytest
import yaml

ROLES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'roles'))
EXTRA = {'labels__name': 'casc-managed'}

# task file -> (endpoint, the query_params it sends without extra parameters), one entry per list fetch being diffed
FETCHES = {
    'applications': [('applications', {'organization': 1})],
    'credential_types': [('credential_types', {'managed': False})],
    'credentials': [('credentials', {'organization': 1})],
    'execution_environments': [('execution_environments', {'organization': 1})],
    'groups': [('groups', {'inventory': 1, 'not__description': 'imported'})],
    'hosts': [('hosts', {'inventory': 1, 'not__description': 'imported'})],
    'inventories': [('inventories', {'organization': 1})],
    'inventory_sources': [('inventory_sources', {'organization': 1})],
    'job_templates': [('job_templates', {'organization': 1})],
    'notification_templates': [('notification_templates', {'organization': 1})],
    'projects': [('projects', {'organization': 1})],
    'schedules': [('job_templates', {'organization': 1}), ('workflow_job_templates', {'organization': 1})],
    'teams': [('teams', {'organization': 1})],
    'workflow_job_templates': [('workflow_job_templates', {'organization': 1})],
}

RECORDER = '''
from __future__ import absolute_import, division, print_function
__metaclass__ = type
import json
import os
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        with open(os.environ['OBJECT_DIFF_RECORD'], 'a') as f:
            f.write(json.dumps({'endpoint': terms[0], 'query_params': kwargs.get('query_params')}) + '\\n')
        return [{'id': 1, 'is_superuser': True, 'kind': '', 'has_inventory_sources': False, 'unified_job_template': 1, 'version': '25.6.2'}]
'''

NO_DIFF = '''
from __future__ import absolute_import, division, print_function
__metaclass__ = type
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return []
'''


def run_playbook(tmp_path, play, args=()):
    (tmp_path / 'lookup_plugins').mkdir(exist_ok=True)
    (tmp_path / 'lookup_plugins' / 'record_api.py').write_text(RECORDER)
    (tmp_path / 'lookup_plugins' / 'no_diff.py').write_text(NO_DIFF)
    (tmp_path / 'play.yml').write_text(play)
    record = tmp_path / 'record.jsonl'
    record.write_text('')
    env = dict(os.environ, OBJECT_DIFF_RECORD=str(record), ANSIBLE_ROLES_PATH=ROLES_DIR, ANSIBLE_NOCOLOR='1', ANSIBLE_RETRY_FILES_ENABLED='0')
    if (tmp_path / 'bin').is_dir():
        env['PATH'] = '%s%s%s' % (tmp_path / 'bin', os.pathsep, env['PATH'])
        env['ANSIBLE_COLLECTIONS_PATH'] = str(tmp_path / 'collections')
    proc = subprocess.run(
        [sys.executable, '-m', 'ansible.cli.playbook', '-i', 'localhost,', str(tmp_path / 'play.yml')] + list(args),
        cwd=str(tmp_path), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True,
    )
    return proc, [json.loads(line) for line in record.read_text().splitlines()]


def diff_play(task_file, extra_vars):
    vars_block = {
        'controller_api_plugin': 'record_api',
        'controller_role_plugin': 'no_diff',
        'controller_hostname': 'controller.example.com',
        'controller_oauthtoken': 'token',
        'controller_validate_certs': False,
        'controller_configuration_object_diff_secure_logging': False,
        'is_controller_v4': True,
        'orgs': 'Default',
    }
    vars_block.update(extra_vars)
    play = [{
        'hosts': 'localhost',
        'connection': 'local',
        'gather_facts': False,
        'vars': vars_block,
        'tasks': [{'ansible.builtin.include_role': {'name': 'object_diff', 'tasks_from': task_file}}],
    }]
    return yaml.safe_dump(play)


def list_fetches(calls):
    # The organization lookup by name, and the inventory walk in groups.yml / hosts.yml, are not the diffed list.
    return [c for c in calls if c['query_params'] and 'name' not in c['query_params'] and 'not__total_groups' not in c['query_params']
            and 'not__total_hosts' not in c['query_params']]


@pytest.mark.parametrize('task_file', sorted(FETCHES))
def test_object_diff_fetch_takes_extra_query_params(tmp_path, task_file):
    proc, calls = run_playbook(tmp_path, diff_play(task_file, {'controller_configuration_object_diff_query_params': EXTRA}))
    assert proc.returncode == 0, proc.stdout
    expected = [(endpoint, dict(params, **EXTRA)) for endpoint, params in FETCHES[task_file]]
    assert [(c['endpoint'], c['query_params']) for c in list_fetches(calls)] == expected


@pytest.mark.parametrize('task_file', sorted(FETCHES))
def test_object_diff_fetch_unchanged_by_default(tmp_path, task_file):
    proc, calls = run_playbook(tmp_path, diff_play(task_file, {}))
    assert proc.returncode == 0, proc.stdout
    assert [(c['endpoint'], c['query_params']) for c in list_fetches(calls)] == FETCHES[task_file]


@pytest.mark.parametrize('task_file', ['groups', 'hosts'])
def test_object_diff_inventory_walk_not_narrowed(tmp_path, task_file):
    proc, calls = run_playbook(tmp_path, diff_play(task_file, {'controller_configuration_object_diff_query_params': EXTRA}))
    assert proc.returncode == 0, proc.stdout
    walk = [c for c in calls if c['endpoint'] == 'inventories']
    assert walk and all('labels__name' not in c['query_params'] for c in walk)


def spec_play(value):
    # Validates the way role argument validation does: the spec's options against the variables in scope. The
    # role's defaults/main.yml supplies a boolean secure_logging; the spec's default for it is an untemplated string.
    return textwrap.dedent('''\
        - hosts: localhost
          connection: local
          gather_facts: false
          vars:
            controller_configuration_object_diff_secure_logging: false
            controller_configuration_object_diff_query_params: {value}
          tasks:
            - ansible.builtin.validate_argument_spec:
                argument_spec: "{{{{ (lookup('ansible.builtin.file', '{spec}') | from_yaml).argument_specs.main.options }}}}"
        ''').format(spec=os.path.join(ROLES_DIR, 'object_diff', 'meta', 'argument_specs.yml'), value=json.dumps(value))


def test_object_diff_argument_spec_accepts_query_params(tmp_path):
    proc, dummy = run_playbook(tmp_path, spec_play(EXTRA))
    assert proc.returncode == 0, proc.stdout


def test_object_diff_argument_spec_declares_query_params_a_dict(tmp_path):
    proc, dummy = run_playbook(tmp_path, spec_play(['labels__name', 'casc-managed']))
    assert proc.returncode != 0, proc.stdout
    assert 'controller_configuration_object_diff_query_params' in proc.stdout


# Every key a fetch sets for its own scope, with a value that would widen it if the extras won.
SCOPE_OVERRIDES = {'organization': 999, 'inventory': 999, 'managed': True, 'managed_by_tower': True, 'not__description': 'none'}


@pytest.mark.parametrize('task_file', sorted(FETCHES))
def test_object_diff_fetch_keeps_its_scope_over_extra_query_params(tmp_path, task_file):
    # Run the task file directly, past the role's check, so only the merge order decides.
    extra = dict(SCOPE_OVERRIDES, **EXTRA)
    proc, calls = run_playbook(tmp_path, diff_play(task_file, {'controller_configuration_object_diff_query_params': extra}))
    assert proc.returncode == 0, proc.stdout
    expected = [(endpoint, dict(extra, **params)) for endpoint, params in FETCHES[task_file]]
    assert [(c['endpoint'], c['query_params']) for c in list_fetches(calls)] == expected


def check_play(extra):
    return yaml.safe_dump([{
        'hosts': 'localhost',
        'connection': 'local',
        'gather_facts': False,
        'vars': {'controller_configuration_object_diff_query_params': extra},
        'tasks': [{'ansible.builtin.include_role': {'name': 'object_diff', 'tasks_from': 'query_params'}}],
    }])


@pytest.mark.parametrize('extra', [
    {'organization': 999},
    {'inventory': 999},
    {'managed': True},
    {'managed_by_tower': True},
    {'not__description': 'none'},
    {'or__organization': 999},
    {'not__inventory': 999},
    {'organization__in': '1,999'},
    {'chain__or__inventory__name': 'Other'},
    dict(EXTRA, organization=999),
])
def test_object_diff_rejects_query_params_that_replace_its_scope(tmp_path, extra):
    proc, dummy = run_playbook(tmp_path, check_play(extra))
    assert proc.returncode != 0, proc.stdout
    assert 'can only narrow' in proc.stdout
    assert all(key in proc.stdout for key in extra if key != 'labels__name')


@pytest.mark.parametrize('extra', [{}, EXTRA, {'name__startswith': 'Demo', 'labels__name': 'casc-managed'}])
def test_object_diff_accepts_query_params_that_narrow(tmp_path, extra):
    proc, dummy = run_playbook(tmp_path, check_play(extra))
    assert proc.returncode == 0, proc.stdout


@pytest.mark.parametrize('task_file, expected', [
    ('credential_types', [('credential_types', dict(SCOPE_OVERRIDES, managed_by_tower=False, **EXTRA))]),
])
def test_object_diff_fetch_keeps_its_scope_before_controller_v4(tmp_path, task_file, expected):
    # Controllers older than 4.0.0 take the managed_by_tower fetch instead of managed.
    extra = dict(SCOPE_OVERRIDES, **EXTRA)
    proc, calls = run_playbook(tmp_path, diff_play(task_file, {'is_controller_v4': False, 'controller_configuration_object_diff_query_params': extra}))
    assert proc.returncode == 0, proc.stdout
    assert [(c['endpoint'], c['query_params']) for c in list_fetches(calls)] == expected


FAKE_GALAXY = """#!/bin/sh
echo "ctrliq.ascender 25.6.2"
"""


def role_run(tmp_path, extra):
    # The whole role through main.yml, as a caller runs it, with the controller_api and object diff lookups stubbed in a
    # stand-in ctrliq.ascender collection and an ansible-galaxy that lists it.
    lookups = tmp_path / 'collections' / 'ansible_collections' / 'ctrliq' / 'ascender' / 'plugins' / 'lookup'
    lookups.mkdir(parents=True, exist_ok=True)
    (lookups / 'controller_api.py').write_text(RECORDER)
    (lookups / 'controller_object_diff.py').write_text(NO_DIFF)
    (tmp_path / 'bin').mkdir(exist_ok=True)
    (tmp_path / 'bin' / 'ansible-galaxy').write_text(FAKE_GALAXY)
    os.chmod(str(tmp_path / 'bin' / 'ansible-galaxy'), 0o755)
    return yaml.safe_dump([{
        'hosts': 'localhost',
        'connection': 'local',
        'gather_facts': False,
        'vars': {
            'controller_hostname': 'controller.example.com',
            'controller_oauthtoken': 'token',
            'controller_validate_certs': False,
            'controller_configuration_object_diff_secure_logging': False,
            'orgs': 'Default',
            'controller_projects': [],
            'controller_configuration_object_diff_query_params': extra,
        },
        'roles': ['object_diff'],
    }])


def test_object_diff_rejects_conflicting_query_params_under_tags(tmp_path):
    # Callers usually select object types with --tags; the check must still run and stop the role before any fetch.
    proc, calls = run_playbook(tmp_path, role_run(tmp_path, {'organization': 999}), ['--tags', 'projects'])
    assert proc.returncode != 0, proc.stdout
    assert 'can only narrow' in proc.stdout
    assert not [c for c in calls if c['endpoint'] == 'projects']


def test_object_diff_narrows_under_tags(tmp_path):
    proc, calls = run_playbook(tmp_path, role_run(tmp_path, EXTRA), ['--tags', 'projects'])
    assert proc.returncode == 0, proc.stdout
    assert [(c['endpoint'], c['query_params']) for c in list_fetches(calls)] == [('projects', dict(EXTRA, organization=1))]
