from __future__ import absolute_import, division, print_function

__metaclass__ = type

# Renders the module arguments the configuration roles build, without a controller:
# a field declared with an empty value has to reach the module, and a field that is
# not declared has to stay omitted (or take the role default under enforce_defaults).

import os

import pytest

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

try:
    from ansible.template import trust_as_template
except ImportError:  # ansible-core < 2.19 templates any string
    def trust_as_template(value):
        return value

COLLECTION_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OMIT = '__omit_place_holder__test'

# role: (module, loop variable, enforce_defaults variable)
ROLES = {
    'inventories': ('ctrliq.ascender.inventory', '__controller_inventory_item', 'controller_configuration_inventories_enforce_defaults'),
    'job_templates': ('ctrliq.ascender.job_template', '__controller_template_item', 'controller_configuration_job_templates_enforce_defaults'),
    'schedules': ('ctrliq.ascender.schedule', '__controller_schedule_item', 'controller_configuration_schedules_enforce_defaults'),
    'workflow_job_templates': ('ctrliq.ascender.workflow_job_template', '__workflow_loop_item', 'controller_configuration_workflows_enforce_defaults'),
}

# (role, field, declared empty value, what enforce_defaults fills in for an undeclared field)
EMPTY_FIELDS = [
    ('inventories', 'kind', '', ''),
    ('inventories', 'host_filter', '', ''),
    ('inventories', 'variables', {}, {}),
    ('job_templates', 'limit', '', ''),
    ('job_templates', 'job_tags', '', ''),
    ('job_templates', 'skip_tags', '', ''),
    ('schedules', 'job_tags', '', ''),
    ('schedules', 'skip_tags', '', ''),
    ('schedules', 'limit', '', OMIT),
    ('workflow_job_templates', 'limit', '', ''),
    ('workflow_job_templates', 'job_tags', '', ''),
    ('workflow_job_templates', 'skip_tags', '', ''),
]

NON_EMPTY = {'kind': 'smart', 'host_filter': 'name__icontains=web', 'variables': {'foo': 'bar'}}


def _find_module_args(tasks, module):
    for task in tasks:
        if module in task:
            return task[module]
        found = _find_module_args(task.get('block', []), module)
        if found is not None:
            return found
    return None


def _render(role, field, item, enforce_defaults):
    module, loop_var, enforce_var = ROLES[role]
    loader = DataLoader()
    tasks = loader.load_from_file(os.path.join(COLLECTION_ROOT, 'roles', role, 'tasks', 'main.yml'))
    args = _find_module_args(tasks, module)
    assert args is not None, 'no {0} task in roles/{1}'.format(module, role)
    templar = Templar(loader=loader, variables={loop_var: item, enforce_var: enforce_defaults, 'omit': OMIT})
    return templar.template(trust_as_template(args[field]))


def _empty(value):
    # variables goes through regex_replace in the role, so a declared {} arrives as its text form
    return value in ('', {}, '{}')


@pytest.mark.parametrize('enforce_defaults', [False, True])
@pytest.mark.parametrize('role, field, empty, enforced', EMPTY_FIELDS)
def test_declared_empty_value_is_sent(role, field, empty, enforced, enforce_defaults):
    rendered = _render(role, field, {'name': 'test', field: empty}, enforce_defaults)
    assert rendered != OMIT
    assert _empty(rendered), rendered


@pytest.mark.parametrize('role, field, empty, enforced', EMPTY_FIELDS)
def test_undeclared_field_is_omitted(role, field, empty, enforced):
    assert _render(role, field, {'name': 'test'}, False) == OMIT


@pytest.mark.parametrize('role, field, empty, enforced', EMPTY_FIELDS)
def test_undeclared_field_takes_enforced_default(role, field, empty, enforced):
    assert _render(role, field, {'name': 'test'}, True) == enforced


@pytest.mark.parametrize('role, field, empty, enforced', EMPTY_FIELDS)
def test_declared_value_passes_through(role, field, empty, enforced):
    value = NON_EMPTY.get(field, 'webservers')
    rendered = _render(role, field, {'name': 'test', field: value}, False)
    if isinstance(value, dict):
        assert (rendered if isinstance(rendered, dict) else DataLoader().load(rendered)) == value
    else:
        assert rendered == value
