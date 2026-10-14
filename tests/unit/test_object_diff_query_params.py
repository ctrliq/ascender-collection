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
        return [{'id': 1, 'is_superuser': True, 'kind': '', 'has_inventory_sources': False, 'unified_job_template': 1}]
'''

NO_DIFF = '''
from __future__ import absolute_import, division, print_function
__metaclass__ = type
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        return []
'''


def run_playbook(tmp_path, play):
    (tmp_path / 'lookup_plugins').mkdir(exist_ok=True)
    (tmp_path / 'lookup_plugins' / 'record_api.py').write_text(RECORDER)
    (tmp_path / 'lookup_plugins' / 'no_diff.py').write_text(NO_DIFF)
    (tmp_path / 'play.yml').write_text(play)
    record = tmp_path / 'record.jsonl'
    record.write_text('')
    env = dict(os.environ, OBJECT_DIFF_RECORD=str(record), ANSIBLE_ROLES_PATH=ROLES_DIR, ANSIBLE_NOCOLOR='1', ANSIBLE_RETRY_FILES_ENABLED='0')
    proc = subprocess.run(
        [sys.executable, '-m', 'ansible.cli.playbook', '-i', 'localhost,', str(tmp_path / 'play.yml')],
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
