"""filetree_create skips only null values in extra_vars, extra_data and survey specs.

The templates used to test ``(value | string) is not match('None')``. ``match`` anchors at the
start only, so any value whose text starts with "None" ("None", "Nonesuch", "None of these") was
dropped as if it were null. Each template is rendered with ansible.builtin.template from a fake
controller_api lookup and loaded back with include_vars, the way filetree_read loads it.

These tests do not need the ascender server, so run them with ``pytest --noconftest``.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / 'roles/filetree_create/templates'

FAKE_LOOKUP = '''
import json, os
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        with open(os.environ['FAKE_API_DATA']) as f:
            value = json.load(f).get(terms[0], [])
        return value if isinstance(value, list) else [value]
'''

# Values that start with "None" but are not null, plus a real null and an empty string.
VARS_IN = {'answer': 'Nonesuch', 'reply': 'None of these', 'literal': 'None', 'region': 'us-east-1',
           'unset': None, 'blank': ''}
# Null and empty values are still skipped.
VARS_OUT = {'answer': 'Nonesuch', 'reply': 'None of these', 'literal': 'None', 'region': 'us-east-1'}

SURVEY = {'name': '', 'description': '', 'spec': [
    {'question_name': 'None of the above?', 'question_description': 'Nonetheless, pick one', 'required': True,
     'type': 'multiplechoice', 'variable': 'noise_level', 'min': None, 'max': None, 'default': 'None',
     'choices': ['None', 'Low', 'High'], 'new_question': True}]}
QUESTION = {'question_name': 'None of the above?', 'question_description': 'Nonetheless, pick one', 'required': True,
            'type': 'multiplechoice', 'variable': 'noise_level', 'default': 'None',
            'choices': ['None', 'Low', 'High'], 'new_question': True}

BASE_VARS = {
    'template_overrides_resources': {}, 'template_overrides_global': {}, 'organization': 'Default',
    'is_controller_v4': True, 'controller_api_plugin': 'fake_api', 'controller_hostname': 'controller.example.com',
    'controller_oauthtoken': 'x', 'controller_validate_certs': False, 'query_controller_api_max_objects': 100,
}

NO_NOTIFICATIONS = {k: [] for k in ('query_notification_error', 'query_notification_started', 'query_notification_success',
                                    'query_notification_approvals', 'query_notification_changed')}

JOB_TEMPLATE = {
    'name': 'Deploy', 'description': '', 'inventory': 1, 'playbook': 'site.yml', 'scm_branch': '', 'forks': 0,
    'limit': '', 'verbosity': 0, 'job_type': 'run', 'job_slice_count': 1, 'job_slice_pinned_hosts': '',
    'use_fact_cache': False, 'allow_simultaneous': False, 'ask_scm_branch_on_launch': False,
    'ask_diff_mode_on_launch': False, 'ask_tags_on_launch': False, 'ask_skip_tags_on_launch': False,
    'ask_job_type_on_launch': False, 'ask_verbosity_on_launch': False, 'ask_variables_on_launch': False,
    'ask_inventory_on_launch': False, 'ask_limit_on_launch': False, 'ask_credential_on_launch': False,
    'ask_execution_environment_on_launch': False, 'ask_labels_on_launch': False, 'ask_forks_on_launch': False,
    'ask_job_slice_count_on_launch': False, 'ask_timeout_on_launch': False, 'ask_instance_groups_on_launch': False,
    'extra_vars': json.dumps(VARS_IN), 'job_tags': '', 'force_handlers': False, 'skip_tags': '',
    'start_at_task': '', 'timeout': 0, 'custom_virtualenv': None, 'host_config_key': '', 'survey_enabled': True,
    'become_enabled': False, 'diff_mode': False, 'webhook_service': '', 'webhook_credential': None,
    'prevent_instance_group_fallback': False, 'prevent_relaunch': False,
    'summary_fields': {'organization': {'name': 'Default'}, 'project': {'name': 'playbooks'},
                       'inventory': {'name': 'Prod'}, 'execution_environment': {'name': 'EE'}, 'credentials': []},
    'related': {'instance_groups': '/jt/ig/', 'survey_spec': '/jt/survey/'}}

WORKFLOW = {
    'id': 7, 'name': 'Release', 'description': '', 'summary_fields': {'organization': {'name': 'Default'}},
    'ask_variables_on_launch': False, 'allow_simultaneous': False, 'allow_overwrite_flow_vars_on_relaunch': False,
    'scm_branch': '', 'limit': '', 'ask_limit_on_launch': False, 'ask_inventory_on_launch': False,
    'webhook_service': '', 'job_tags': '', 'skip_tags': '', 'ask_tags_on_launch': False,
    'ask_skip_tags_on_launch': False, 'ask_labels_on_launch': False, 'ask_scm_branch_on_launch': False,
    'extra_vars': json.dumps(VARS_IN), 'survey_enabled': True, 'related': {'survey_spec': '/wf/survey/'}}

NODE = {
    'id': 11, 'identifier': 'start', 'verbosity': 0, 'limit': '', 'job_type': None, 'all_parents_must_converge': False,
    'max_retries': 0, 'extra_data': VARS_IN, 'success_nodes': [], 'always_nodes': [], 'failure_nodes': [],
    'summary_fields': {'workflow_job_template': {'name': 'Release'}, 'inventory': {'name': 'Prod'},
                       'unified_job_template': {'name': 'Deploy', 'unified_job_type': 'job'}}}

CASES = {
    'job_template': dict(template='current_job_templates.j2', key='controller_templates',
                         vars=dict(NO_NOTIFICATIONS, query_labels=[], current_job_templates_asset_value=JOB_TEMPLATE),
                         api={'/jt/ig/': [], '/jt/survey/': SURVEY}),
    'workflow_job_template': dict(template='current_workflow_job_templates.j2', key='controller_workflows',
                                  vars=dict(NO_NOTIFICATIONS, query_labels=[],
                                            current_workflow_job_templates_asset_value=WORKFLOW),
                                  api={'/wf/survey/': SURVEY, 'api/v2/workflow_job_template_nodes/': [NODE]}),
}


def _ansible_playbook():
    exe = pathlib.Path(sys.executable).parent / 'ansible-playbook'
    return str(exe) if exe.exists() else shutil.which('ansible-playbook')


@pytest.fixture(scope='module')
def exported():
    """Render both templates in one playbook run. Returns {case: (rendered text, loaded entry)}."""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        (d / 'lookup_plugins').mkdir()
        (d / 'lookup_plugins/fake_api.py').write_text(FAKE_LOOKUP)
        (d / 'ansible.cfg').write_text('[defaults]\n')
        data, tasks = {}, []
        for case, spec in CASES.items():
            task_vars = {}
            for name, value in spec['vars'].items():
                key = '%s/%s' % (case, name)
                data[key] = value
                task_vars[name] = "{{ query('fake_api', %r)%s }}" % (key, '' if isinstance(value, list) else ' | first')
            data.update(spec['api'])
            out = str(d / ('%s.yml' % case))
            tasks.append({'name': case, 'rescue': [{'ansible.builtin.debug': {'msg': 'failed: %s' % case}}], 'block': [
                {'ansible.builtin.template': {'src': str(TEMPLATES / spec['template']), 'dest': out}, 'vars': task_vars},
                {'ansible.builtin.include_vars': {'file': out, 'name': 'loaded'}},
                {'ansible.builtin.copy': {'content': '{{ loaded | to_json }}', 'dest': out + '.json'}},
            ]})
        (d / 'data.json').write_text(json.dumps(data))
        (d / 'play.yml').write_text(json.dumps([{'hosts': 'localhost', 'gather_facts': False, 'vars': BASE_VARS,
                                                 'tasks': tasks}]))
        env = dict(os.environ, ANSIBLE_CONFIG=str(d / 'ansible.cfg'), FAKE_API_DATA=str(d / 'data.json'),
                   ANSIBLE_NOCOLOR='1')
        proc = subprocess.run([_ansible_playbook(), '-i', 'localhost,', '-c', 'local', str(d / 'play.yml')],
                              cwd=str(d), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True, check=False)
        result = {}
        for case, spec in CASES.items():
            out = d / ('%s.yml' % case)
            text = out.read_text() if out.exists() else None
            loaded = d / ('%s.yml.json' % case)
            result[case] = (text, json.loads(loaded.read_text())[spec['key']][0] if loaded.exists() else None)
        result['_log'] = proc.stdout
        yield result


def _entry(exported, case):
    text, entry = exported[case]
    assert entry is not None, 'export or re-import failed:\n%s\n%s' % (text, exported['_log'][-4000:])
    return text, entry


@pytest.mark.parametrize('case', sorted(CASES))
def test_extra_vars_keep_values_that_start_with_none(exported, case):
    text, entry = _entry(exported, case)
    assert entry['extra_vars'] == VARS_OUT, text


def test_workflow_node_extra_data_keeps_values_that_start_with_none(exported):
    text, entry = _entry(exported, 'workflow_job_template')
    assert entry['simplified_workflow_nodes'][0]['extra_data'] == VARS_OUT, text


@pytest.mark.parametrize('case', sorted(CASES))
def test_survey_keeps_values_that_start_with_none(exported, case):
    text, entry = _entry(exported, case)
    assert entry['survey_spec']['spec'] == [QUESTION], text
