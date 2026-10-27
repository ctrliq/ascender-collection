"""filetree_create must export controller data so that filetree_read loads back the same values.

Each template is rendered with ansible.builtin.template, with its input coming from a fake
controller_api lookup the way the role supplies it, and loaded back with include_vars the way
filetree_read does. Values carry quotes, colons, newlines, unicode and Jinja syntax. The loaded
data must equal the values that would be applied, nothing may be templated on the way, and no
value may add keys to the YAML.

These tests do not need the ascender server, so run them with ``pytest --noconftest``.
"""
import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import jinja2
import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / 'roles/filetree_create/templates'
FILTER_SRC = ROOT / 'plugins/filter/export_yaml.py'

JINJA = 'ops{{ 6 * 7 }}'
HOSTILE = 'x"\n    injected_marker: "yes'
QUOTES = 'He said "hi", it\'s fine'
COLON = 'key: value # not a comment'
NEWLINES = 'line one\nline two\n'
UNICODE = 'Équipe – ops ✓'

FAKE_LOOKUP = '''
import json, os
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        with open(os.environ['FAKE_API_DATA']) as f:
            value = json.load(f)[terms[0]]
        return value if isinstance(value, list) else [value]
'''

BASE_VARS = {
    'template_overrides_resources': {},
    'template_overrides_global': {},
    'organization': 'Default',
    'is_aap': True,
    'controller_api_plugin': 'fake_api',
    'controller_hostname': 'controller.example.com',
    'controller_oauthtoken': 'x',
    'controller_validate_certs': False,
    'query_controller_api_max_objects': 100,
}

NO_NOTIFICATIONS = {
    'query_notification_error': [],
    'query_notification_started': [],
    'query_notification_success': [],
    'query_notification_approvals': [],
}

# Each case: template, the template's input variables (served through the fake lookup), the
# extra API endpoints the template queries itself, and the data include_vars must load back.
CASES = {
    'applications': dict(
        template='current_applications.j2',
        vars={'current_applications_asset_value': {
            'name': 'Portal: SSO ✓', 'description': QUOTES,
            'summary_fields': {'organization': {'name': 'Default'}},
            'authorization_grant_type': 'authorization-code',
            'redirect_uris': 'https://a.example.com/cb https://b.example.com/cb',
            'skip_authorization': False, 'client_type': 'confidential'}},
        expected={'controller_applications': [{
            'name': 'Portal: SSO ✓', 'description': QUOTES, 'organization': 'Default',
            'authorization_grant_type': 'authorization-code',
            'redirect_uris': 'https://a.example.com/cb https://b.example.com/cb',
            'skip_authorization': False, 'client_type': 'confidential'}]},
    ),
    'credential_types': dict(
        template='current_credential_types.j2',
        vars={'current_credential_types_asset_value': [{
            'name': 'Vault token', 'description': '', 'kind': 'cloud',
            'inputs': {'fields': [{'id': 'token', 'label': 'Token: "primary"', 'type': 'string', 'secret': True},
                                  {'id': 'ttl', 'label': 'TTL', 'type': 'string', 'default': '1h'}],
                       'required': ['token']},
            'injectors': {'env': {'VAULT_TOKEN': '{{ token }}'},
                          'extra_vars': {'vault_url': 'https://vault.example.com:8200', 'vault_ttl': '{{ ttl }}'}}}]},
        expected={'controller_credential_types': [{
            'name': 'Vault token', 'description': '', 'kind': 'cloud',
            'inputs': {'fields': [{'id': 'token', 'label': 'Token: "primary"', 'type': 'string', 'secret': True},
                                  {'id': 'ttl', 'label': 'TTL', 'type': 'string', 'default': '1h'}],
                       'required': ['token']},
            'injectors': {'env': {'VAULT_TOKEN': '{{ token }}'},
                          'extra_vars': {'vault_url': 'https://vault.example.com:8200', 'vault_ttl': '{{ ttl }}'}}}]},
    ),
    'credentials': dict(
        template='current_credentials.j2',
        vars={'current_credentials_asset_value': {
            'name': 'deploy key', 'description': NEWLINES, 'organization': 1,
            'summary_fields': {'credential_type': {'name': 'Machine'}, 'organization': {'name': 'Default'}},
            'inputs': {'username': 'deploy', 'password': '$encrypted$', 'become_method': 'sudo',
                       'ssh_key_data': '$encrypted$', 'become_username': JINJA}}},
        expected={'controller_credentials': [{
            'name': 'deploy key', 'description': NEWLINES, 'credential_type': 'Machine', 'organization': 'Default',
            'inputs': {'username': 'deploy', 'password': '', 'become_method': 'sudo', 'ssh_key_data': '',
                       'become_username': JINJA}}]},
    ),
    'execution_environments': dict(
        template='current_execution_environments.j2',
        vars={'current_execution_environments_asset_value': [
            {'name': 'EE "minimal"', 'description': JINJA, 'image': 'registry.example.com/ee:1.0', 'pull': 'missing',
             'summary_fields': {'organization': {'name': 'Default'}, 'credential': {'name': 'registry'}}},
            {'name': 'global ee', 'description': '', 'image': 'quay.io/ee:latest', 'pull': '', 'summary_fields': {}}]},
        expected={'controller_execution_environments': [
            {'name': 'EE "minimal"', 'description': JINJA, 'organization': 'Default',
             'image': 'registry.example.com/ee:1.0', 'pull': 'missing', 'credential': 'registry'},
            {'name': 'global ee', 'description': '', 'organization': '', 'image': 'quay.io/ee:latest', 'pull': ''}]},
    ),
    'groups': dict(
        template='current_groups.j2',
        vars={'current_groups_asset_value': [{
            'name': 'web: frontends', 'description': UNICODE, 'summary_fields': {'inventory': {'name': 'Prod'}},
            'variables': 'http_port: 8080\nmotd: "Welcome {{ inventory_hostname }}"\nempty: ""\n',
            'related': {'children': '/api/v2/groups/1/children/', 'hosts': '/api/v2/groups/1/hosts/'}}]},
        api={'/api/v2/groups/1/children/': [{'name': 'web-eu'}, {'name': 'web "us"'}],
             '/api/v2/groups/1/hosts/': [{'name': 'web1.example.com'}]},
        expected={'controller_groups': [{
            'name': 'web: frontends', 'description': UNICODE, 'inventory': 'Prod',
            'variables': {'http_port': 8080, 'motd': 'Welcome {{ inventory_hostname }}', 'empty': ''},
            'children': ['web-eu', 'web "us"'], 'hosts': ['web1.example.com']}]},
    ),
    'hosts': dict(
        template='current_hosts.j2',
        vars={'current_hosts_asset_value': [
            {'name': 'web1.example.com', 'description': "O'Brien's box", 'has_inventory_sources': False,
             'summary_fields': {'inventory': {'name': 'Prod'}}, 'instance_id': '', 'enabled': True,
             'variables': json.dumps({'ansible_host': '10.0.0.1', 'ansible_port': 2222, 'tags': ['web', 'a: b'],
                                      'nested': {'k': None, 'flag': False, 'ratio': 0.5}, 'note': JINJA})},
            {'name': 'synced', 'description': '', 'has_inventory_sources': True,
             'summary_fields': {'inventory': {'name': 'Prod'}}, 'instance_id': 'i-1', 'enabled': True, 'variables': ''}]},
        expected={'controller_hosts': [{
            'name': 'web1.example.com', 'description': "O'Brien's box", 'inventory': 'Prod', 'enabled': True,
            'variables': {'ansible_host': '10.0.0.1', 'ansible_port': 2222, 'tags': ['web', 'a: b'],
                          'nested': {'k': None, 'flag': False, 'ratio': 0.5}, 'note': JINJA}}]},
    ),
    'instance_groups': dict(
        template='current_instance_groups.j2',
        vars={'current_instance_groups_asset_value': [
            {'name': 'k8s: pods', 'policy_instance_minimum': 0, 'policy_instance_percentage': 50,
             'is_container_group': True, 'max_concurrent_jobs': 0, 'max_forks': 0, 'policy_instance_list': [],
             'summary_fields': {'credential': {'name': 'k8s cred'}},
             'pod_spec_override': 'apiVersion: v1\nkind: Pod\nmetadata:\n  namespace: "{{ ns }}"\n',
             'related': {'instances': '/api/v2/instance_groups/2/instances/'}},
            {'name': 'default', 'policy_instance_minimum': 1, 'policy_instance_percentage': 0,
             'is_container_group': False, 'max_concurrent_jobs': 10, 'max_forks': 50,
             'policy_instance_list': ['node1.example.com'], 'summary_fields': {}, 'pod_spec_override': '',
             'related': {'instances': '/api/v2/instance_groups/3/instances/'}}]},
        api={'/api/v2/instance_groups/2/instances/': [],
             '/api/v2/instance_groups/3/instances/': [{'hostname': 'node1.example.com'}]},
        expected={'controller_instance_groups': [
            {'name': 'k8s: pods', 'policy_instance_minimum': 0, 'policy_instance_percentage': 50,
             'is_container_group': True, 'max_concurrent_jobs': 0, 'max_forks': 0, 'credential': 'k8s cred',
             'pod_spec_override': 'apiVersion: v1\nkind: Pod\nmetadata:\n  namespace: "{{ ns }}"\n'},
            {'name': 'default', 'policy_instance_minimum': 1, 'policy_instance_percentage': 0,
             'is_container_group': False, 'max_concurrent_jobs': 10, 'max_forks': 50,
             'policy_instance_list': ['node1.example.com'], 'instances': ['node1.example.com']}]},
    ),
    'instance_groups_empty': dict(
        template='current_instance_groups.j2',
        vars={'current_instance_groups_asset_value': []},
        expected={'controller_instance_groups': []},
    ),
    'instances': dict(
        template='current_instances.j2',
        vars={'current_instances_asset_value': [
            {'hostname': 'exec1.example.com', 'capacity_adjustment': '1.00', 'enabled': True, 'managed_by_policy': True,
             'node_type': 'execution', 'node_state': 'installed', 'listener_port': 27199, 'peers': [5],
             'peers_from_control_nodes': False},
            {'hostname': 'control1', 'node_type': 'control', 'enabled': True}],
            '__receptor_peer_hostname_by_id': {'5': 'hop1.example.com'},
            '__instances_hostname_by_id': {}},
        expected={'controller_instances': [{
            'hostname': 'exec1.example.com', 'capacity_adjustment': '1.00', 'enabled': True, 'managed_by_policy': True,
            'node_type': 'execution', 'node_state': 'installed', 'listener_port': 27199,
            'peers': ['hop1.example.com'], 'peers_from_control_nodes': False}]},
    ),
    'inventories': dict(
        template='current_inventories.j2',
        vars={'inventory_organization': 'Default', 'current_inventories_asset_value': {
            'name': 'Prod: "east"', 'description': UNICODE, 'host_filter': None, 'kind': '',
            'prevent_instance_group_fallback': False,
            'variables': '---\nenv: prod\nowners: ["a@example.com"]\nbanner: ' + json.dumps(JINJA) + '\n',
            'related': {'input_inventories': '/api/v2/inventories/4/input_inventories/',
                        'instance_groups': '/api/v2/inventories/4/instance_groups/'}}},
        api={'/api/v2/inventories/4/input_inventories/': [],
             '/api/v2/inventories/4/instance_groups/': [{'name': 'default'}]},
        expected={'controller_inventories': [{
            'name': 'Prod: "east"', 'description': UNICODE, 'organization': 'Default', 'host_filter': '',
            'prevent_instance_group_fallback': False,
            'variables': {'env': 'prod', 'owners': ['a@example.com'], 'banner': JINJA},
            'instance_groups': ['default']}]},
    ),
    'inventory_sources': dict(
        template='current_inventory_sources.j2',
        vars={'current_inventory_sources_asset_value': [{
            'name': 'aws: ec2', 'description': '', 'source': 'scm', 'limit': '', 'source_path': 'inventories/aws_ec2.yml',
            'source_vars': json.dumps({'regions': ['us-east-1'], 'keyed_groups': [{'key': 'tags.Name', 'prefix': 'tag'}],
                                       'compose': {'ansible_host': 'private_ip_address'}, 'filters': JINJA}),
            'update_on_launch': True, 'overwrite': False, 'scm_branch': '', 'host_filter': '', 'enabled_var': 'status',
            'enabled_value': 'running', 'overwrite_vars': False, 'timeout': 0, 'verbosity': 1, 'update_cache_timeout': 0,
            'summary_fields': {'organization': {'name': 'Default'}, 'inventory': {'name': 'Prod'},
                               'credential': {'name': 'aws'}, 'source_project': {'name': 'inventory repo'},
                               'execution_environment': {'name': 'EE'}},
            'related': {'instance_groups': '/is/ig/', 'notification_templates_error': '/is/ne/',
                        'notification_templates_started': '/is/nst/', 'notification_templates_success': '/is/nsu/'}}]},
        api={'/is/ig/': [], '/is/ne/': [{'name': 'slack: "ops"'}], '/is/nst/': [], '/is/nsu/': []},
        expected={'controller_inventory_sources': [{
            'name': 'aws: ec2', 'description': '', 'organization': 'Default', 'source': 'scm', 'limit': '',
            'source_project': 'inventory repo', 'source_path': 'inventories/aws_ec2.yml',
            'source_vars': {'regions': ['us-east-1'], 'keyed_groups': [{'key': 'tags.Name', 'prefix': 'tag'}],
                            'compose': {'ansible_host': 'private_ip_address'}, 'filters': JINJA},
            'inventory': 'Prod', 'update_on_launch': True, 'overwrite': False, 'credential': 'aws', 'scm_branch': '',
            'host_filter': '', 'enabled_var': 'status', 'enabled_value': 'running', 'overwrite_vars': False,
            'timeout': 0, 'verbosity': 1, 'update_cache_timeout': 0, 'execution_environment': 'EE',
            'notification_templates_error': ['slack: "ops"']}]},
    ),
    'job_templates': dict(
        template='current_job_templates.j2',
        vars=dict(NO_NOTIFICATIONS, query_labels=[{'name': 'deploy: prod'}],
                  query_notification_error=[{'name': 'slack: "ops"'}],
                  current_job_templates_asset_value={
                      'name': 'Deploy "app"', 'description': JINJA, 'inventory': 1, 'playbook': 'site.yml',
                      'scm_branch': '', 'forks': 0, 'limit': 'web:&prod', 'verbosity': 1, 'job_type': 'run',
                      'job_slice_count': 1, 'job_slice_pinned_hosts': '', 'use_fact_cache': False,
                      'allow_simultaneous': False, 'ask_scm_branch_on_launch': False, 'ask_diff_mode_on_launch': False,
                      'ask_tags_on_launch': False, 'ask_skip_tags_on_launch': False, 'ask_job_type_on_launch': False,
                      'ask_verbosity_on_launch': False, 'ask_variables_on_launch': True, 'ask_inventory_on_launch': False,
                      'ask_limit_on_launch': True, 'ask_credential_on_launch': False,
                      'ask_execution_environment_on_launch': False, 'ask_labels_on_launch': False,
                      'ask_forks_on_launch': False, 'ask_job_slice_count_on_launch': False, 'ask_timeout_on_launch': False,
                      'ask_instance_groups_on_launch': False,
                      'extra_vars': '---\nregion: us-east-1\nretries: 3\nflags:\n  debug: false\nempty: ""\n'
                                    'hosts: ["a", "b: c"]\nmsg: ' + json.dumps(JINJA) + '\n',
                      'job_tags': '', 'force_handlers': False, 'skip_tags': '', 'start_at_task': '', 'timeout': 0,
                      'custom_virtualenv': None, 'host_config_key': '', 'survey_enabled': True, 'become_enabled': True,
                      'diff_mode': False, 'webhook_service': '', 'webhook_credential': None,
                      'prevent_instance_group_fallback': False,
                      'summary_fields': {'organization': {'name': 'Default'}, 'project': {'name': 'playbooks'},
                                         'inventory': {'name': 'Prod'}, 'execution_environment': {'name': 'EE'},
                                         'credentials': [{'name': 'deploy key'}, {'name': 'vault: "prod"'}]},
                      'related': {'instance_groups': '/jt/ig/', 'survey_spec': '/jt/survey/'}}),
        api={'/jt/ig/': [{'name': 'default'}],
             '/jt/survey/': {'name': '', 'description': '', 'spec': [
                 {'question_name': 'Target env?', 'question_description': 'Pick one: "prod" or dev', 'required': True,
                  'type': 'multiplechoice', 'variable': 'env', 'min': None, 'max': None, 'default': 'dev',
                  'choices': ['dev', 'prod: main', JINJA], 'new_question': True},
                 {'question_name': 'Password', 'question_description': '', 'required': False, 'type': 'password',
                  'variable': 'pw', 'min': 0, 'max': 32, 'default': '$encrypted$', 'choices': '', 'new_question': True}]}},
        expected={'controller_templates': [{
            'name': 'Deploy "app"', 'description': JINJA, 'organization': 'Default', 'project': 'playbooks',
            'inventory': 'Prod', 'playbook': 'site.yml', 'scm_branch': '', 'forks': 0, 'limit': 'web:&prod',
            'verbosity': 1, 'job_type': 'run', 'job_slice_count': 1, 'instance_groups': ['default'],
            'use_fact_cache': False, 'credentials': ['deploy key', 'vault: "prod"'], 'allow_simultaneous': False,
            'ask_scm_branch_on_launch': False, 'ask_diff_mode_on_launch': False, 'ask_tags_on_launch': False,
            'ask_skip_tags_on_launch': False, 'ask_job_type_on_launch': False, 'ask_verbosity_on_launch': False,
            'ask_variables_on_launch': True, 'ask_inventory_on_launch': False, 'ask_limit_on_launch': True,
            'ask_credential_on_launch': False, 'ask_execution_environment_on_launch': False,
            'ask_labels_on_launch': False, 'ask_forks_on_launch': False, 'ask_job_slice_count_on_launch': False,
            'ask_timeout_on_launch': False, 'ask_instance_groups_on_launch': False,
            'extra_vars': {'region': 'us-east-1', 'retries': 3, 'flags': {'debug': False}, 'hosts': ['a', 'b: c'],
                           'msg': JINJA},
            'job_tags': '', 'force_handlers': False, 'skip_tags': '', 'start_at_task': '', 'timeout': 0,
            'execution_environment': 'EE', 'host_config_key': '', 'labels': ['deploy: prod'],
            'notification_templates_error': ['slack: "ops"'], 'survey_enabled': True,
            'survey_spec': {'name': '', 'description': '', 'spec': [
                {'question_name': 'Target env?', 'question_description': 'Pick one: "prod" or dev', 'required': True,
                 'type': 'multiplechoice', 'variable': 'env', 'default': 'dev', 'choices': ['dev', 'prod: main', JINJA],
                 'new_question': True},
                {'question_name': 'Password', 'required': False, 'type': 'password', 'variable': 'pw', 'min': 0,
                 'max': 32, 'default': '', 'new_question': True}]},
            'become_enabled': True, 'diff_mode': False, 'webhook_service': '',
            'prevent_instance_group_fallback': False}]},
    ),
    'labels': dict(
        template='current_labels.j2',
        vars={'current_labels_asset_value': {'name': HOSTILE, 'summary_fields': {'organization': {'name': 'Default'}}}},
        expected={'controller_labels': [{'name': HOSTILE, 'organization': 'Default'}]},
    ),
    'notification_templates': dict(
        template='current_notification_templates.j2',
        vars={'current_notification_templates_asset_value': {
            'name': 'slack: ops', 'description': '', 'summary_fields': {'organization': {'name': 'Default'}},
            'notification_type': 'slack',
            'notification_configuration': {'channels': ['#ops', '#alerts'], 'token': '$encrypted$', 'hex_color': '',
                                           'port': 443, 'use_ssl': True, 'url': 'https://hooks.example.com/x?a=1&b=2'},
            'messages': {'started': {'message': '{{ job_friendly_name }} started', 'body': None}, 'success': None,
                         'error': {'message': 'Failed: "{{ job.id }}"', 'body': 'line1\nline2'}}}},
        expected={'controller_notifications': [{
            'name': 'slack: ops', 'description': '', 'organization': 'Default', 'notification_type': 'slack',
            'notification_configuration': {'channels': ['#ops', '#alerts'], 'token': '$encrypted$', 'hex_color': '',
                                           'port': 443, 'use_ssl': True, 'url': 'https://hooks.example.com/x?a=1&b=2'},
            'messages': {'started': {'message': '{{ job_friendly_name }} started', 'body': None}, 'success': None,
                         'error': {'message': 'Failed: "{{ job.id }}"', 'body': 'line1\nline2'}}}]},
    ),
    'organizations': dict(
        template='current_organizations.j2',
        vars=dict(NO_NOTIFICATIONS, query_notification_approvals=[{'name': 'approvals: "mail"'}], current_organization={
            'name': 'Default', 'description': 'R&D: "core"', 'max_hosts': 0,
            'summary_fields': {'default_environment': {'name': 'EE'}},
            'related': {'instance_groups': '/org/ig/', 'galaxy_credentials': '/org/gc/'}}),
        api={'/org/ig/': [{'name': 'default'}], '/org/gc/': [{'name': 'Ansible Galaxy'}]},
        expected={'controller_organizations': [{
            'name': 'Default', 'description': 'R&D: "core"', 'max_hosts': 0, 'default_environment': 'EE',
            'instance_groups': ['default'], 'galaxy_credentials': ['Ansible Galaxy'],
            'notification_templates_approvals': ['approvals: "mail"']}]},
    ),
    'projects': dict(
        template='current_projects.j2',
        vars=dict(NO_NOTIFICATIONS, current_projects_asset_value={
            'name': 'playbooks', 'description': COLON,
            'summary_fields': {'organization': {'name': 'Default'}, 'credential': {'name': 'git key'}},
            'scm_type': 'git', 'scm_url': 'git@github.com:example/playbooks.git', 'scm_track_submodules': False,
            'scm_branch': 'main', 'scm_clean': True, 'scm_delete_on_update': False, 'scm_update_on_launch': True,
            'webhook_service': '', 'webhook_ref_filter': '', 'scm_update_cache_timeout': 0,
            'scm_refspec': 'refs/heads/*:refs/remotes/origin/*', 'local_path': '_6__playbooks',
            'allow_override': False, 'timeout': 0}),
        expected={'controller_projects': [{
            'name': 'playbooks', 'description': COLON, 'organization': 'Default', 'scm_type': 'git',
            'scm_url': 'git@github.com:example/playbooks.git', 'scm_track_submodules': False,
            'scm_credential': 'git key', 'scm_branch': 'main', 'scm_clean': True, 'scm_delete_on_update': False,
            'scm_update_on_launch': True, 'scm_update_cache_timeout': 0,
            'scm_refspec': 'refs/heads/*:refs/remotes/origin/*', 'allow_override': False, 'update_project': False,
            'timeout': 0}]},
    ),
    'schedules': dict(
        template='current_schedules.j2',
        vars={'query_instance_groups': [], 'query_credentials': [{'name': 'vault: "prod"'}], 'query_labels': [],
              'current_schedules_asset_value': {
                  'name': 'nightly: "full"', 'description': '', 'enabled': True,
                  'summary_fields': {'unified_job_template': {'name': 'Deploy "app"'}, 'inventory': {'name': 'Prod'}},
                  'dtstart': '2026-01-01T02:00:00Z', 'dtend': None, 'timezone': 'America/Los_Angeles',
                  'rrule': 'DTSTART;TZID=America/Los_Angeles:20260101T020000 RRULE:FREQ=DAILY;INTERVAL=1',
                  'extra_data': {'env': 'prod', 'pw': '$encrypted$', 'nested': {'list': [1, 'two: 2', JINJA]}},
                  'scm_branch': '', 'forks': 0, 'job_slice_count': 1, 'timeout': 0, 'job_type': None, 'job_tags': '',
                  'skip_tags': '', 'limit': '', 'diff_mode': None, 'verbosity': None}},
        expected={'controller_schedules': [{
            'name': 'nightly: "full"', 'description': '', 'enabled': True, 'unified_job_template': 'Deploy "app"',
            'inventory': 'Prod', 'dtstart': '2026-01-01T02:00:00Z', 'dtend': None, 'timezone': 'America/Los_Angeles',
            'rrule': 'DTSTART;TZID=America/Los_Angeles:20260101T020000 RRULE:FREQ=DAILY;INTERVAL=1',
            'extra_data': {'env': 'prod', 'pw': '', 'nested': {'list': [1, 'two: 2', JINJA]}},
            'credentials': ['vault: "prod"'], 'scm_branch': '', 'forks': 0, 'job_slice_count': 1, 'timeout': 0,
            'job_type': None, 'job_tags': '', 'skip_tags': '', 'limit': '', 'verbosity': 0}]},
    ),
    'settings': dict(
        template='current_settings.j2',
        vars={'all_settings': [{
            'AWX_ISOLATION_SHOW_PATHS': ['/srv', '/opt'], 'LOG_AGGREGATOR_LEVEL': 'INFO', 'MAX_FORKS': 200,
            'ALLOW_OAUTH2_FOR_EXTERNAL_USERS': True, 'CUSTOM_LOGIN_INFO': 'Welcome: "ops"\nsecond line ' + JINJA,
            'NULL_ONE': None, 'SOCIAL_AUTH_GITHUB_SECRET': '$encrypted$',
            'SOCIAL_AUTH_ORGANIZATION_MAP': {'Default': {'users': True, 'admins': ['a@example.com']}},
            'AUTOMATION_ANALYTICS_URL': 'https://None.example.com'}]},
        expected={'controller_settings': [{'settings': {
            'AWX_ISOLATION_SHOW_PATHS': ['/srv', '/opt'], 'LOG_AGGREGATOR_LEVEL': 'INFO', 'MAX_FORKS': 200,
            'ALLOW_OAUTH2_FOR_EXTERNAL_USERS': True, 'CUSTOM_LOGIN_INFO': 'Welcome: "ops"\nsecond line ' + JINJA,
            'NULL_ONE': None, 'SOCIAL_AUTH_GITHUB_SECRET': '',
            'SOCIAL_AUTH_ORGANIZATION_MAP': {'Default': {'users': True, 'admins': ['a@example.com']}},
            'AUTOMATION_ANALYTICS_URL': 'https://None.example.com'}}]},
    ),
    'team_roles': dict(
        template='current_team_roles.j2',
        vars={'team_name': 'ops: team', 'object_roles': [
            {'Admin': {'resource_type': 'organization', 'resource_names': ['Default']}},
            {'Execute': {'resource_type': 'job_template', 'resource_names': ['Deploy "app"', JINJA]}},
            {'Approve': {'resource_type': 'workflow_job_template', 'resource_names': ['Release: "train"']}}]},
        expected={'controller_roles': [
            {'team': 'ops: team', 'organizations': ['Default'], 'role': 'admin'},
            {'team': 'ops: team', 'job_templates': ['Deploy "app"', JINJA], 'role': 'execute'},
            {'team': 'ops: team', 'workflows': ['Release: "train"'], 'role': 'approval'}]},
    ),
    'teams': dict(
        template='current_teams.j2',
        vars={'current_teams_asset_value': {'name': 'ops: team', 'description': HOSTILE,
                                            'summary_fields': {'organization': {'name': 'Default'}}}},
        expected={'controller_teams': [{'name': 'ops: team', 'description': HOSTILE, 'organization': 'Default'}]},
    ),
    'user_roles': dict(
        template='current_user_roles.j2',
        vars={'username': 'jdoe', 'object_roles': [
            {'Read': {'resource_type': 'inventory', 'resource_names': ['Prod: "east"']}},
            {'Use': {'resource_type': 'credential', 'resource_names': [JINJA]}}]},
        expected={'controller_roles': [
            {'user': 'jdoe', 'inventories': ['Prod: "east"'], 'role': 'read'},
            {'user': 'jdoe', 'credentials': [JINJA], 'role': 'use'}]},
    ),
    'users': dict(
        template='current_users.j2',
        vars={'current_users_asset_value': {
            'username': 'jdoe', 'email': 'j.doe+ops@example.com', 'first_name': JINJA, 'last_name': "O'Brien: Jr",
            'is_system_auditor': False, 'is_superuser': False, 'preferred_language': ''}},
        expected={'controller_user_accounts': [{
            'username': 'jdoe', 'password': 'INITIAL', 'email': 'j.doe+ops@example.com', 'first_name': JINJA,
            'last_name': "O'Brien: Jr", 'auditor': False, 'superuser': False,
            'update_secrets': False}]},
    ),
    'workflow_job_templates': dict(
        template='current_workflow_job_templates.j2',
        vars=dict(NO_NOTIFICATIONS, query_labels=[], query_notification_success=[{'name': 'mail: "team"'}],
                  current_workflow_job_templates_asset_value={
                      'id': 7, 'name': 'Release: "train"', 'description': NEWLINES,
                      'summary_fields': {'organization': {'name': 'Default'}},
                      'ask_variables_on_launch': True, 'allow_simultaneous': False,
                      'scm_branch': '', 'limit': '',
                      'ask_limit_on_launch': False, 'ask_inventory_on_launch': False, 'webhook_service': '',
                      'job_tags': 'deploy', 'skip_tags': '', 'ask_tags_on_launch': False, 'ask_skip_tags_on_launch': False,
                      'ask_labels_on_launch': False, 'ask_scm_branch_on_launch': False,
                      'extra_vars': json.dumps({'release': '1.2', 'notify': ['a', 'b'], 'blank': '', 'msg': JINJA}),
                      'survey_enabled': False, 'related': {'survey_spec': '/wf/survey/'}}),
        api={'/wf/survey/': {},
             'api/v2/workflow_job_template_nodes/': [
                 {'id': 11, 'identifier': 'start: "a"', 'verbosity': 1, 'limit': '', 'job_type': None,
                  'all_parents_must_converge': False, 'max_retries': 0,
                  'extra_data': {'region': 'us-east-1', 'empty': '', 'n': 2, 'msg': JINJA},
                  'success_nodes': [12], 'always_nodes': [], 'failure_nodes': [],
                  'condition_edges': [{'id': 12, 'trigger': 'artifact', 'artifact_key': 'status', 'operator': '==',
                                       'expected_value': 'ok'}],
                  'summary_fields': {'workflow_job_template': {'name': 'Release: "train"'}, 'inventory': {'name': 'Prod'},
                                     'unified_job_template': {'name': 'Deploy "app"', 'unified_job_type': 'job'}}},
                 {'id': 12, 'identifier': 'approve', 'verbosity': None, 'limit': '', 'job_type': '',
                  'all_parents_must_converge': True, 'max_retries': 0, 'extra_data': {},
                  'success_nodes': [], 'always_nodes': [], 'failure_nodes': [],
                  'summary_fields': {'workflow_job_template': {'name': 'Release: "train"'},
                                     'unified_job_template': {'name': 'Approve: "prod"', 'description': JINJA,
                                                              'unified_job_type': 'workflow_approval', 'timeout': 3600}}}],
             'workflow_job_template_nodes/12': [{'identifier': 'approve'}]},
        expected={'controller_workflows': [{
            'name': 'Release: "train"', 'description': NEWLINES, 'organization': 'Default',
            'simplified_workflow_nodes': [
                {'identifier': 'start: "a"', 'inventory': 'Prod', 'workflow_job_template': 'Release: "train"',
                 'unified_job_template': 'Deploy "app"', 'verbosity': 1, 'limit': '',
                 'all_parents_must_converge': False, 'organization': 'Default',
                 'extra_data': {'region': 'us-east-1', 'n': 2, 'msg': JINJA}, 'success_nodes': ['approve'],
                 'condition_nodes': [{'identifier': 'approve', 'trigger': 'artifact', 'artifact_key': 'status',
                                      'operator': '==', 'expected_value': 'ok'}]},
                {'identifier': 'approve', 'workflow_job_template': 'Release: "train"', 'limit': '',
                 'approval_node': {'description': JINJA, 'name': 'Approve: "prod"', 'timeout': 3600},
                 'organization': 'Default', 'all_parents_must_converge': True}],
            'ask_variables_on_launch': True, 'allow_simultaneous': False,
            'scm_branch': '', 'limit': '',
            'ask_limit_on_launch': False, 'ask_inventory_on_launch': False, 'webhook_service': '', 'job_tags': 'deploy',
            'ask_tags_on_launch': False, 'ask_skip_tags_on_launch': False, 'ask_labels_on_launch': False,
            'ask_scm_branch_on_launch': False,
            'extra_vars': {'release': '1.2', 'notify': ['a', 'b'], 'msg': JINJA},
            'notification_templates_success': ['mail: "team"'], 'survey_enabled': False}]},
    ),
}

# Controllers older than v4 export custom_virtualenv instead of execution_environment.
CASES['job_templates_v3'] = copy.deepcopy(CASES['job_templates'])
CASES['job_templates_v3']['vars']['is_aap'] = False
CASES['job_templates_v3']['vars']['current_job_templates_asset_value']['custom_virtualenv'] = '/var/lib/awx/venv/ops: "x"/'
_jt_v3 = CASES['job_templates_v3']['expected']['controller_templates'][0]
del _jt_v3['execution_environment']
_jt_v3['custom_virtualenv'] = '/var/lib/awx/venv/ops: "x"/'

# Strings a template writes itself rather than copying from the controller.
TEMPLATE_LITERALS = {'INITIAL', '', 'ToDo: The node is pointing to a deleted Job Template'}


def _ansible_playbook():
    exe = pathlib.Path(sys.executable).parent / 'ansible-playbook'
    return str(exe) if exe.exists() else shutil.which('ansible-playbook')


@pytest.fixture(scope='module')
def exported():
    """Render every case in one playbook run. Returns {case: (rendered text, loaded data)}."""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        coll = d / 'collections/ansible_collections/ctrliq/ascender'
        (coll / 'plugins/filter').mkdir(parents=True)
        (coll / 'galaxy.yml').write_text('namespace: ctrliq\nname: ascender\nversion: 0.0.0\n')
        if FILTER_SRC.exists():
            shutil.copy(FILTER_SRC, coll / 'plugins/filter/export_yaml.py')
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
            data.update(spec.get('api', {}))
            out = str(d / ('%s.yml' % case))
            # One block per case, so a case that fails does not stop the others.
            tasks.append({'name': case, 'rescue': [{'ansible.builtin.debug': {'msg': 'failed: %s' % case}}], 'block': [
                {'ansible.builtin.template': {'src': str(TEMPLATES / spec['template']), 'dest': out}, 'vars': task_vars},
                {'ansible.builtin.include_vars': {'file': out, 'name': 'loaded'}},
                {'ansible.builtin.copy': {'content': '{{ loaded | to_json }}', 'dest': out + '.json'}},
            ]})
        (d / 'data.json').write_text(json.dumps(data))
        play = [{'hosts': 'localhost', 'gather_facts': False, 'vars': BASE_VARS, 'tasks': tasks}]
        (d / 'play.yml').write_text(json.dumps(play))

        env = dict(os.environ, ANSIBLE_CONFIG=str(d / 'ansible.cfg'), ANSIBLE_COLLECTIONS_PATH=str(d / 'collections'),
                   FAKE_API_DATA=str(d / 'data.json'), ANSIBLE_NOCOLOR='1')
        proc = subprocess.run([_ansible_playbook(), '-i', 'localhost,', '-c', 'local', str(d / 'play.yml')],
                              cwd=str(d), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True, check=False)
        result = {}
        for case in CASES:
            out = d / ('%s.yml' % case)
            text = out.read_text() if out.exists() else None
            loaded = json.loads((d / ('%s.yml.json' % case)).read_text()) if text is not None and \
                (d / ('%s.yml.json' % case)).exists() else None
            result[case] = (text, loaded)
        result['_log'] = proc.stdout
        yield result


@pytest.mark.parametrize('case', sorted(CASES))
def test_export_round_trips(exported, case):
    text, loaded = exported[case]
    assert loaded is not None, 'export or re-import failed:\n%s\n%s' % (text, exported['_log'][-4000:])
    assert loaded == CASES[case]['expected'], text


class _Unsafe(str):
    pass


class _Loader(yaml.SafeLoader):
    pass


# A reader that uses plain PyYAML instead of include_vars needs this constructor.
_Loader.add_constructor('!unsafe', lambda loader, node: _Unsafe(loader.construct_scalar(node)))


def _strings(value):
    """Yield (string, is_key) for every string in `value`."""
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                yield k, True
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)
    elif isinstance(value, str):
        yield value, False


def _resolves_to_str(s):
    return yaml.SafeLoader('').resolve(yaml.ScalarNode, s, (True, False)) == 'tag:yaml.org,2002:str'


@pytest.mark.parametrize('case', sorted(CASES))
def test_every_exported_string_is_unsafe(exported, case):
    """Every controller-supplied string value is tagged !unsafe, and no untagged string anywhere,
    key or value, carries Jinja delimiters. Strings that YAML would read as another type (numbers,
    booleans, timestamps, empty) are written untagged on purpose."""
    text = exported[case][0]
    assert text is not None, exported['_log'][-4000:]
    for s, is_key in _strings(yaml.load(text, Loader=_Loader)):
        if isinstance(s, _Unsafe):
            continue
        assert '{' not in s, '%s: untagged %r\n%s' % (case, s, text)
        if not is_key:
            assert s in TEMPLATE_LITERALS or not _resolves_to_str(s), '%s: %r is not !unsafe\n%s' % (case, s, text)


@pytest.mark.parametrize('case', ['labels', 'teams'])
def test_newline_and_quote_do_not_add_keys(exported, case):
    text = exported[case][0]
    assert text is not None, exported['_log'][-4000:]
    assert 'injected_marker' not in yaml.load(text, Loader=_Loader)[next(iter(CASES[case]['expected']))][0], text


EXPORT_FILTER = 'ctrliq.ascender.export_yaml'
# The one name a template may print directly. It is only ever assigned a concatenation of
# export_yaml output and literal text (the survey spec loop), which the gate also checks.
ALLOWED_NAME = 'current_content'


def _is_export(node):
    return isinstance(node, jinja2.nodes.Filter) and node.name == EXPORT_FILTER


# Constructs that pull in or reshape output the gate cannot see.
FORBIDDEN_NODES = (jinja2.nodes.FilterBlock, jinja2.nodes.Include, jinja2.nodes.Import,
                   jinja2.nodes.FromImport, jinja2.nodes.Extends)


def _gate_offenders(path):
    """Return the printed expressions in `path` that are not export_yaml output.

    Works on Jinja's parse tree, so precedence is Jinja's own: in ``a if b else c | f`` the
    filter binds to ``c`` only, and the expression is rejected."""
    text = path.read_text()
    bad = []
    if text.startswith('#jinja2:'):
        # Ansible honors a #jinja2: header that changes the delimiters this parse uses.
        bad.append('%s:1: #jinja2: header' % path.name)
    tree = jinja2.Environment().parse(text)
    for node in tree.find_all(FORBIDDEN_NODES):
        bad.append('%s:%s: %s' % (path.name, node.lineno, type(node).__name__))
    for output in tree.find_all(jinja2.nodes.Output):
        for node in output.nodes:
            if isinstance(node, jinja2.nodes.TemplateData) or _is_export(node):
                continue
            if isinstance(node, jinja2.nodes.Name) and node.name == ALLOWED_NAME:
                continue
            bad.append('%s:%s: %s' % (path.name, node.lineno, type(node).__name__))
    checked_targets = set()
    for assign in tree.find_all(jinja2.nodes.Assign):
        if not (isinstance(assign.target, jinja2.nodes.Name) and assign.target.name == ALLOWED_NAME):
            continue
        parts = assign.node.nodes if isinstance(assign.node, jinja2.nodes.Concat) else [assign.node]
        if all(_is_export(part) or isinstance(part, jinja2.nodes.Const) for part in parts):
            checked_targets.add(id(assign.target))
        else:
            bad.append('%s:%s: %s assigned something other than export_yaml output' % (
                path.name, assign.lineno, ALLOWED_NAME))
    # Any other way of binding the name (for, with, macro parameters, tuple targets, set blocks).
    for name in tree.find_all(jinja2.nodes.Name):
        if name.name == ALLOWED_NAME and name.ctx in ('store', 'param') and id(name) not in checked_targets:
            bad.append('%s:%s: %s bound outside a checked set' % (path.name, name.lineno, ALLOWED_NAME))
    return bad


def test_every_template_expression_goes_through_export_yaml():
    """Gate: every printed expression in filetree_create's templates is a top-level export_yaml call."""
    offenders = [o for p in sorted(TEMPLATES.glob('*.j2')) for o in _gate_offenders(p)]
    assert not offenders, 'unescaped interpolation:\n  ' + '\n  '.join(offenders)


def test_vaulted_value_is_exported_as_its_text():
    """A !vault value reaches the filter as AnsibleVaultEncryptedUnicode on 2.16 (not a str
    subclass) and as an encrypted string on 2.19+; both must export as one tagged string."""
    from ansible.parsing.vault import VaultLib, VaultSecret

    plaintext = 'vaulted: "value"\nline two'
    vault = VaultLib([('default', VaultSecret(b'test-password'))])
    blob = vault.encrypt(plaintext).decode()
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        coll = d / 'collections/ansible_collections/ctrliq/ascender'
        (coll / 'plugins/filter').mkdir(parents=True)
        (coll / 'galaxy.yml').write_text('namespace: ctrliq\nname: ascender\nversion: 0.0.0\n')
        shutil.copy(FILTER_SRC, coll / 'plugins/filter/export_yaml.py')
        (d / 'ansible.cfg').write_text('[defaults]\n')
        (d / 'pw').write_text('test-password\n')
        (d / 'vars.yml').write_text('secret: !vault |\n' + ''.join('  %s\n' % line for line in blob.splitlines()))
        (d / 'play.yml').write_text(json.dumps([{
            'hosts': 'localhost', 'gather_facts': False, 'vars_files': ['vars.yml'],
            'tasks': [{'ansible.builtin.copy': {'content': '{{ secret | ctrliq.ascender.export_yaml }}',
                                                'dest': str(d / 'out')}}]}]))
        env = dict(os.environ, ANSIBLE_CONFIG=str(d / 'ansible.cfg'), ANSIBLE_COLLECTIONS_PATH=str(d / 'collections'),
                   ANSIBLE_NOCOLOR='1')
        proc = subprocess.run([_ansible_playbook(), '-i', 'localhost,', '-c', 'local', '--vault-password-file',
                               str(d / 'pw'), str(d / 'play.yml')], cwd=str(d), env=env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, universal_newlines=True, check=False)
        assert proc.returncode == 0, proc.stdout[-3000:]
        out = (d / 'out').read_text()
    assert out == '!unsafe "vaulted: \\"value\\"\\nline two"', out
    assert yaml.load(out, Loader=_Loader) == plaintext


def _filter_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location('export_yaml_under_test', str(FILTER_SRC))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_undefined_values():
    """Strict undefined keeps raising its own error; lenient undefined exports '' as main did."""
    export_yaml = _filter_module().export_yaml
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    with pytest.raises(jinja2.UndefinedError, match="'missing' is undefined"):
        export_yaml(env.undefined(name='missing'))
    assert export_yaml(jinja2.Undefined(name='missing')) == '""'


def test_dict_views_and_range():
    export_yaml = _filter_module().export_yaml
    d = {'a: b': 1, 'c': JINJA}
    assert export_yaml(d.keys()) == '[!unsafe "a: b", !unsafe "c"]'
    assert export_yaml(d.values()) == '[1, !unsafe "ops{{ 6 * 7 }}"]'
    assert export_yaml(d.items()) == '[[!unsafe "a: b", 1], [!unsafe "c", !unsafe "ops{{ 6 * 7 }}"]]'
    assert export_yaml(range(3)) == '[0, 1, 2]'


def test_undefined_and_views_through_ansible():
    """The same inputs as ansible-core hands them to the filter from a template."""
    with tempfile.TemporaryDirectory() as d:
        d = pathlib.Path(d)
        coll = d / 'collections/ansible_collections/ctrliq/ascender'
        (coll / 'plugins/filter').mkdir(parents=True)
        (coll / 'galaxy.yml').write_text('namespace: ctrliq\nname: ascender\nversion: 0.0.0\n')
        shutil.copy(FILTER_SRC, coll / 'plugins/filter/export_yaml.py')
        (d / 'ansible.cfg').write_text('[defaults]\n')
        (d / 't.j2').write_text('keys: {{ d.keys() | ctrliq.ascender.export_yaml }}\n'
                                'values: {{ d.values() | ctrliq.ascender.export_yaml }}\n'
                                'range: {{ range(2) | ctrliq.ascender.export_yaml }}\n')
        (d / 'u.j2').write_text('x: {{ missing | ctrliq.ascender.export_yaml }}\n')
        (d / 'play.yml').write_text(json.dumps([{
            'hosts': 'localhost', 'gather_facts': False, 'vars': {'d': {'a': 1, 'b': 'two'}},
            'tasks': [{'ansible.builtin.template': {'src': str(d / 't.j2'), 'dest': str(d / 'out')}},
                      {'ansible.builtin.template': {'src': str(d / 'u.j2'), 'dest': str(d / 'uout')},
                       'register': 'u', 'ignore_errors': True},
                      {'ansible.builtin.copy': {'content': '{{ u.msg }}', 'dest': str(d / 'umsg')}}]}]))
        env = dict(os.environ, ANSIBLE_CONFIG=str(d / 'ansible.cfg'), ANSIBLE_COLLECTIONS_PATH=str(d / 'collections'),
                   ANSIBLE_NOCOLOR='1')
        proc = subprocess.run([_ansible_playbook(), '-i', 'localhost,', '-c', 'local', str(d / 'play.yml')],
                              cwd=str(d), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True, check=False)
        assert proc.returncode == 0, proc.stdout[-3000:]
        expected = {'keys': ['a', 'b'], 'values': [1, 'two'], 'range': [0, 1]}
        assert yaml.load((d / 'out').read_text(), Loader=_Loader) == expected
        assert not (d / 'uout').exists()
        assert "'missing' is undefined" in (d / 'umsg').read_text()
