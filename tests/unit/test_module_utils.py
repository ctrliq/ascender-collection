from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import sys

import pytest
import yaml

from awx.main.models import Organization, Team, Project, Inventory
from requests.models import Response
from unittest import mock

awx_name = 'AWX'
controller_name = 'Red Hat Ansible Automation Platform'
ping_version = '1.2.3'


def getTowerheader(self, header_name, default):
    mock_headers = {'X-API-Product-Name': controller_name, 'X-API-Product-Version': ping_version}
    return mock_headers.get(header_name, default)


def getAWXheader(self, header_name, default):
    mock_headers = {'X-API-Product-Name': awx_name, 'X-API-Product-Version': ping_version}
    return mock_headers.get(header_name, default)


def getNoheader(self, header_name, default):
    mock_headers = {}
    return mock_headers.get(header_name, default)


def read(self):
    return json.dumps({})


def status(self):
    return 200


def mock_controller_ping_response(self, method, url, **kwargs):
    r = Response()
    r.getheader = getTowerheader.__get__(r)
    r.read = read.__get__(r)
    r.status = status.__get__(r)
    return r


def mock_awx_ping_response(self, method, url, **kwargs):
    r = Response()
    r.getheader = getAWXheader.__get__(r)
    r.read = read.__get__(r)
    r.status = status.__get__(r)
    return r


def mock_no_ping_response(self, method, url, **kwargs):
    r = Response()
    r.getheader = getNoheader.__get__(r)
    r.read = read.__get__(r)
    r.status = status.__get__(r)
    return r


def test_version_warning(collection_import, silence_warning):
    ControllerAPIModule = collection_import('plugins.module_utils.controller_api').ControllerAPIModule
    cli_data = {'ANSIBLE_MODULE_ARGS': {}}
    testargs = ['module_file2.py', json.dumps(cli_data)]
    with mock.patch.object(sys, 'argv', testargs):
        with mock.patch('ansible.module_utils.urls.Request.open', new=mock_awx_ping_response):
            my_module = ControllerAPIModule(argument_spec=dict())
            my_module._COLLECTION_VERSION = "2.0.0"
            my_module._COLLECTION_TYPE = "awx"
            my_module.get_endpoint('ping')
    silence_warning.assert_called_once_with(
        'You are running collection version {0} but connecting to {1} version {2}'.format(my_module._COLLECTION_VERSION, awx_name, ping_version)
    )


def test_version_warning_strictness_awx(collection_import, silence_warning):
    ControllerAPIModule = collection_import('plugins.module_utils.controller_api').ControllerAPIModule
    cli_data = {'ANSIBLE_MODULE_ARGS': {}}
    testargs = ['module_file2.py', json.dumps(cli_data)]
    # Compare 1.0.0 to 1.2.3 (major matches)
    with mock.patch.object(sys, 'argv', testargs):
        with mock.patch('ansible.module_utils.urls.Request.open', new=mock_awx_ping_response):
            my_module = ControllerAPIModule(argument_spec=dict())
            my_module._COLLECTION_VERSION = "1.0.0"
            my_module._COLLECTION_TYPE = "awx"
            my_module.get_endpoint('ping')
    silence_warning.assert_not_called()

    # Compare 1.2.0 to 1.2.3 (major matches minor does not count)
    with mock.patch.object(sys, 'argv', testargs):
        with mock.patch('ansible.module_utils.urls.Request.open', new=mock_awx_ping_response):
            my_module = ControllerAPIModule(argument_spec=dict())
            my_module._COLLECTION_VERSION = "1.2.0"
            my_module._COLLECTION_TYPE = "awx"
            my_module.get_endpoint('ping')
    silence_warning.assert_not_called()


def test_version_warning_strictness_controller(collection_import, silence_warning):
    ControllerAPIModule = collection_import('plugins.module_utils.controller_api').ControllerAPIModule
    cli_data = {'ANSIBLE_MODULE_ARGS': {}}
    testargs = ['module_file2.py', json.dumps(cli_data)]
    # Compare 1.2.0 to 1.2.3 (major/minor matches)
    with mock.patch.object(sys, 'argv', testargs):
        with mock.patch('ansible.module_utils.urls.Request.open', new=mock_controller_ping_response):
            my_module = ControllerAPIModule(argument_spec=dict())
            my_module._COLLECTION_VERSION = "1.2.0"
            my_module._COLLECTION_TYPE = "controller"
            my_module.get_endpoint('ping')
    silence_warning.assert_not_called()

    # Compare 1.0.0 to 1.2.3 (major/minor fail to match)
    with mock.patch.object(sys, 'argv', testargs):
        with mock.patch('ansible.module_utils.urls.Request.open', new=mock_controller_ping_response):
            my_module = ControllerAPIModule(argument_spec=dict())
            my_module._COLLECTION_VERSION = "1.0.0"
            my_module._COLLECTION_TYPE = "controller"
            my_module.get_endpoint('ping')
    silence_warning.assert_called_once_with(
        'You are running collection version {0} but connecting to {1} version {2}'.format(my_module._COLLECTION_VERSION, controller_name, ping_version)
    )


def test_type_warning(collection_import, silence_warning):
    ControllerAPIModule = collection_import('plugins.module_utils.controller_api').ControllerAPIModule
    cli_data = {'ANSIBLE_MODULE_ARGS': {}}
    testargs = ['module_file2.py', json.dumps(cli_data)]
    with mock.patch.object(sys, 'argv', testargs):
        with mock.patch('ansible.module_utils.urls.Request.open', new=mock_awx_ping_response):
            my_module = ControllerAPIModule(argument_spec={})
            my_module._COLLECTION_VERSION = ping_version
            my_module._COLLECTION_TYPE = "controller"
            my_module.get_endpoint('ping')
    silence_warning.assert_called_once_with(
        'You are using the {0} version of this collection but connecting to {1}'.format(my_module._COLLECTION_TYPE, awx_name)
    )


def test_duplicate_config(collection_import, silence_warning):
    # imports done here because of PATH issues unique to this test suite
    ControllerAPIModule = collection_import('plugins.module_utils.controller_api').ControllerAPIModule
    data = {'name': 'zigzoom', 'zig': 'zoom', 'controller_username': 'bob', 'controller_config_file': 'my_config'}

    with mock.patch.object(ControllerAPIModule, 'load_config') as mock_load:
        argument_spec = dict(
            name=dict(required=True),
            zig=dict(type='str'),
        )
        ControllerAPIModule(argument_spec=argument_spec, direct_params=data)
        assert mock_load.mock_calls[-1] == mock.call('my_config')

    silence_warning.assert_called_once_with(
        'The parameter(s) controller_username were provided at the same time as '
        'controller_config_file. Precedence may be unstable, '
        'we suggest either using config file or params.'
    )


def test_collection_version_matches_galaxy_yml(collection_import):
    # The hardcoded _COLLECTION_VERSION is what powers the collection-vs-server
    # version compatibility warning, so it must be bumped in lockstep with
    # galaxy.yml. A release that only updates one of the two would leave the
    # shipped collection permanently warning about a stale version mismatch.
    ControllerAPIModule = collection_import('plugins.module_utils.controller_api').ControllerAPIModule
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    with open(os.path.join(repo_root, 'galaxy.yml')) as f:
        galaxy_version = yaml.safe_load(f)['version']
    assert ControllerAPIModule._COLLECTION_VERSION == galaxy_version, (
        '_COLLECTION_VERSION in plugins/module_utils/controller_api.py ({0}) does not match the version in '
        'galaxy.yml ({1}); a release must bump both together.'.format(ControllerAPIModule._COLLECTION_VERSION, galaxy_version)
    )


def test_wait_on_url_timeout_zero_waits_for_the_job(collection_import, mocker):
    """A timeout of 0 means no client side limit, the way the project module documents it and the way the
    projects role relies on it, since it sends a literal 0 for every project that sets a timeout or has
    enforce_defaults on. Testing ``is not None`` instead made 0 abort on the first poll (#296).
    """
    controller_api = collection_import('plugins.module_utils.controller_api')
    mocker.patch.object(controller_api.time, 'sleep')

    module = mocker.Mock()
    module.json_output = {}
    module.fail_json.side_effect = SystemExit
    running = {'json': {'status': 'running', 'failed': False, 'finished': None}}
    finished = {'json': {'status': 'successful', 'failed': False, 'finished': '2026-09-07T15:23:49.557738Z'}}
    module.get_endpoint.side_effect = [running, running, finished]

    result = controller_api.ControllerAPIModule.wait_on_url(module, url='/project_updates/1347/', object_name='foo', object_type='Project Update', timeout=0)

    assert result is finished
    module.fail_json.assert_not_called()
    assert module.get_endpoint.call_count == 3


def test_wait_on_url_timeout_message_names_the_field_and_the_status(collection_import, mocker):
    """When the budget does run out, the message says how long the wait was, which field it was waiting on
    and where the job had got to, so the next timeout can be diagnosed from the log alone.
    """
    controller_api = collection_import('plugins.module_utils.controller_api')
    mocker.patch.object(controller_api.time, 'sleep')
    # start, first check (0.2s in, under budget), second check (3.5s in, over budget)
    mocker.patch.object(controller_api.time, 'time', side_effect=[100.0, 100.2, 103.5, 103.5, 103.5])

    module = mocker.Mock()
    module.json_output = {}
    module.fail_json.side_effect = SystemExit
    module.get_endpoint.return_value = {'json': {'status': 'running', 'failed': False, 'event_processing_finished': False}}

    with pytest.raises(SystemExit):
        controller_api.ControllerAPIModule.wait_on_url(module, url='/project_updates/1347/', object_name='foo', object_type='Project Update', timeout=1)

    module.fail_json.assert_called_once()
    assert module.fail_json.call_args.kwargs['msg'] == (
        'Monitoring of Project Update - foo aborted due to timeout (waited 3.5s for event_processing_finished, last status: running)'
    )


def test_conflicting_name_and_id(run_module, admin_user):
    """In the event that 2 related items match our search criteria in this way:
    one item has an id that matches input
    one item has a name that matches input
    We should preference the id over the name.
    Otherwise, the universality of the controller_api lookup plugin is compromised.
    """
    org_by_id = Organization.objects.create(name='foo')
    slug = str(org_by_id.id)
    Organization.objects.create(name=slug)
    result = run_module('team', {'name': 'foo_team', 'description': 'fooin around', 'organization': slug}, admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    team = Team.objects.filter(name='foo_team').first()
    assert str(team.organization_id) == slug, 'Lookup by id should be preferenced over name in cases of conflict.'
    assert team.organization.name == 'foo'


def test_multiple_lookup(run_module, admin_user):
    org1 = Organization.objects.create(name='foo')
    org2 = Organization.objects.create(name='bar')
    inv = Inventory.objects.create(name='Foo Inv')
    proj1 = Project.objects.create(
        name='foo',
        organization=org1,
        scm_type='git',
        scm_url="https://github.com/ansible/ansible-tower-samples",
    )
    Project.objects.create(
        name='foo',
        organization=org2,
        scm_type='git',
        scm_url="https://github.com/ansible/ansible-tower-samples",
    )
    result = run_module('job_template', {'name': 'Demo Job Template', 'project': proj1.name, 'inventory': inv.id, 'playbook': 'hello_world.yml'}, admin_user)
    assert result.get('failed', False)
    assert 'projects' in result['msg']
    assert 'foo' in result['msg']
    assert 'returned 2 items, expected 1' in result['msg']
    assert 'query' in result


def test_wait_output_leaves_started_and_finished_out_of_an_unfinished_job(collection_import, mocker):
    """Ansible's async_status decides whether an async task is done from the ``started`` and ``finished`` keys
    of the module's own result. A job that was still running used to be reported as started=<timestamp>,
    finished=null, which async_status read as "still running", so collect_async_status polled a module that had
    already exited for every one of its retries (#296). Neither key may appear until the job has finished.
    """
    controller_api = collection_import('plugins.module_utils.controller_api')
    module = mocker.Mock()
    module.json_output = {'started': 'stale', 'finished': 'stale'}

    controller_api.ControllerAPIModule.wait_output(
        module, {'json': {'id': 1347, 'status': 'running', 'elapsed': 0.203697, 'started': '2026-09-07T15:23:30.073389Z', 'finished': None}}
    )

    assert module.json_output == {'id': 1347, 'status': 'running', 'elapsed': 0.203697}


def test_wait_output_reports_started_and_finished_once_the_job_has_finished(collection_import, mocker):
    """On a finished job the two keys come back as the RETURN blocks document them, timestamps and all."""
    controller_api = collection_import('plugins.module_utils.controller_api')
    module = mocker.Mock()
    module.json_output = {}

    controller_api.ControllerAPIModule.wait_output(
        module,
        {'json': {'id': 1347, 'status': 'successful', 'elapsed': 19.484, 'started': '2026-09-07T15:23:30.073389Z', 'finished': '2026-09-07T15:23:49.557738Z'}},
    )

    assert module.json_output == {
        'id': 1347,
        'status': 'successful',
        'elapsed': 19.484,
        'started': '2026-09-07T15:23:30.073389Z',
        'finished': '2026-09-07T15:23:49.557738Z',
    }
