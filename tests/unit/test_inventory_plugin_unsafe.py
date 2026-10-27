# Copyright: Contributors to the Ascender project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)
"""The controller inventory plugin must not let controller data be templated on the control node.

Host and group names and variables come from the controller API, where anyone who can edit an
inventory, host or group (or feed one through an inventory source) controls the text. The plugin
has to mark that data unsafe so Jinja in it stays literal.

Runs without the ascender server: ``pytest --noconftest tests/unit/test_inventory_plugin_unsafe.py``.
"""
from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import sys

import pytest

from ansible.inventory.data import InventoryData
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import init_plugin_loader, inventory_loader
from ansible.template import Templar

JINJA = '{{ 6 * 7 }}'
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

FAKE_INVENTORY = {
    'all': {'hosts': [], 'children': ['web'], 'vars': {'all_note': 'a' + JINJA}},
    'web': {'hosts': ['web1'], 'children': [], 'vars': {'group_note': 'g' + JINJA, 'nested': {'k': ['n' + JINJA]}}},
    '_meta': {'hostvars': {'web1': {'host_note': 'h' + JINJA, 'port': 22}}},
}
FAKE_CONFIG = {'version': 'v' + JINJA, 'ansible_version': '2.16', 'license_info': {'license_type': 'open'}}


@pytest.fixture(scope='module')
def controller_module(tmp_path_factory):
    coll = tmp_path_factory.mktemp('collections')
    ns = coll / 'ansible_collections' / 'ctrliq'
    ns.mkdir(parents=True)
    os.symlink(REPO, str(ns / 'ascender'))
    init_plugin_loader([str(coll)])
    plugin = inventory_loader.get('ctrliq.ascender.controller')
    return sys.modules[type(plugin).__module__]


@pytest.fixture
def parsed(controller_module, monkeypatch):
    class FakeAPI(object):
        short_params = controller_module.ControllerAPIModule.short_params

        def __init__(self, *args, **kwargs):
            pass

        def get_endpoint(self, url, **kwargs):
            return {'json': FAKE_CONFIG if url.startswith('/api/v2/config') else FAKE_INVENTORY}

        def logout(self):
            pass

    monkeypatch.setattr(controller_module, 'ControllerAPIModule', FakeAPI)
    plugin = inventory_loader.get('ctrliq.ascender.controller')
    plugin.no_config_file_supplied = True
    plugin.set_options(direct={'host': 'https://controller.example', 'inventory_id': 1, 'include_metadata': True})
    inventory = InventoryData()
    loader = DataLoader()
    plugin.parse(inventory, loader, '@controller_inventory', cache=False)
    return inventory, loader


def _resolve(loader, value):
    return Templar(loader=loader, variables={'v': value}).template('{{ v }}')


def test_host_var_is_not_templated(parsed):
    inventory, loader = parsed
    host_vars = inventory.get_host('web1').get_vars()
    assert _resolve(loader, host_vars['host_note']) == 'h' + JINJA
    assert host_vars['port'] == 22


def test_group_vars_are_not_templated(parsed):
    inventory, loader = parsed
    group_vars = inventory.groups['web'].get_vars()
    assert _resolve(loader, group_vars['group_note']) == 'g' + JINJA
    assert _resolve(loader, group_vars['nested']['k'][0]) == 'n' + JINJA
    assert _resolve(loader, inventory.groups['all'].get_vars()['all_note']) == 'a' + JINJA


def test_metadata_is_not_templated(parsed):
    inventory, loader = parsed
    meta = inventory.groups['all'].get_vars()['controller_metadata']
    assert _resolve(loader, meta['version']) == 'v' + JINJA


def test_structure_is_unchanged(parsed):
    inventory, _loader = parsed
    assert 'web1' in [h.name for h in inventory.groups['web'].get_hosts()]
    assert 'web' in [g.name for g in inventory.groups['all'].child_groups]
