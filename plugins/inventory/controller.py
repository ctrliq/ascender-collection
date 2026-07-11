# Copyright (c) 2018 Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = '''
name: controller
author:
  - Matthew Jones (@matburt)
  - Yunfan Zhang (@YunfanZhang42)
short_description: Ansible dynamic inventory plugin for Ascender.
description:
    - Reads inventories from Ascender.
    - Supports reading configuration from both YAML config file and environment variables.
    - If reading from the YAML file, the file name must end with controller.(yml|yaml) or controller_inventory.(yml|yaml),
      the path in the command would be /path/to/controller_inventory.(yml|yaml). If some arguments in the config file
      are missing, this plugin will try to fill in missing arguments by reading from environment variables.
    - If reading configurations from environment variables, the path in the command must be @controller_inventory.
options:
    inventory_id:
        description:
            - The ID of the inventory that you wish to import.
            - This is allowed to be either the inventory primary key or its named URL slug.
            - Primary key values will be accepted as strings or integers, and URL slugs must be strings.
            - Named URL slugs follow the syntax of "inventory_name++organization_name".
        type: raw
        env:
            - name: CONTROLLER_INVENTORY
        required: True
    include_metadata:
        description: Make extra requests to provide all group vars with metadata about the source host.
        type: bool
        default: False
extends_documentation_fragment:
- ctrliq.ascender.auth_plugin
- ansible.builtin.inventory_cache
'''

EXAMPLES = '''
# Before you execute the following commands, you should make sure this file is in your plugin path,
# and you enabled this plugin.

# Example for using controller_inventory.yml file

plugin: ctrliq.ascender.controller
host: your_automation_controller_server_network_address
username: your_automation_controller_username
password: your_automation_controller_password
inventory_id: the_ID_of_targeted_automation_controller_inventory
# Optionally cache the fetched inventory data (see the inventory_cache documentation fragment):
# cache: true
# cache_plugin: jsonfile
# cache_connection: /path/to/cache/directory
# Then you can run the following command.
# If some of the arguments are missing, Ansible will attempt to read them from environment variables.
# ansible-inventory -i /path/to/controller_inventory.yml --list

# Example for reading from environment variables:

# Set environment variables:
# export CONTROLLER_HOST=YOUR_AUTOMATION_PLATFORM_CONTROLLER_HOST_ADDRESS
# export CONTROLLER_USERNAME=YOUR_CONTROLLER_USERNAME
# export CONTROLLER_PASSWORD=YOUR_CONTROLLER_PASSWORD
# export CONTROLLER_INVENTORY=THE_ID_OF_TARGETED_INVENTORY
# Read the inventory specified in CONTROLLER_INVENTORY from the controller, and list them.
# The inventory path must always be @controller_inventory if you are reading all settings from environment variables.
# ansible-inventory -i @controller_inventory --list
'''

import os

from ansible.module_utils.common.text.converters import to_text, to_native
from ansible.errors import AnsibleParserError, AnsibleOptionsError
from ansible.plugins.inventory import BaseInventoryPlugin, Cacheable
from ansible.config.manager import ensure_type

from ..module_utils.controller_api import ControllerAPIModule


def handle_error(**kwargs):
    raise AnsibleParserError(to_native(kwargs.get('msg')))


class InventoryModule(BaseInventoryPlugin, Cacheable):
    NAME = 'ctrliq.ascender.controller'
    # Stays backward compatible with the inventory script.
    # If the user supplies '@controller_inventory' as path, the plugin will read from environment variables.
    no_config_file_supplied = False

    def verify_file(self, path):
        if path.endswith('@controller_inventory'):
            self.no_config_file_supplied = True
            return True
        elif super().verify_file(path):
            return path.endswith(
                (
                    'controller_inventory.yml',
                    'controller_inventory.yaml',
                    'controller.yml',
                    'controller.yaml',
                )
            )
        else:
            return False

    def warn_callback(self, warning):
        self.display.warning(warning)

    def parse(self, inventory, loader, path, cache=True):
        super().parse(inventory, loader, path)
        if not self.no_config_file_supplied and os.path.isfile(path):
            self._read_config_data(path)

        # Defer processing of params to logic shared with the modules
        module_params = {}
        for plugin_param, module_param in ControllerAPIModule.short_params.items():
            opt_val = self.get_option(plugin_param)
            if opt_val is not None:
                module_params[module_param] = opt_val

        # validate type of inventory_id because we allow two types as special case
        inventory_id = self.get_option('inventory_id')
        if isinstance(inventory_id, int):
            inventory_id = to_text(inventory_id, nonstring='simplerepr')
        else:
            try:
                inventory_id = ensure_type(inventory_id, 'str')
            except ValueError as e:
                raise AnsibleOptionsError(
                    f'Invalid type for configuration option inventory_id, not integer, and cannot convert to string: {to_native(e)}'
                ) from e
        inventory_id = inventory_id.replace('/', '')
        inventory_url = f'/api/v2/inventories/{inventory_id}/script/'

        # The cache plugin is normally loaded by _read_config_data(); load it explicitly to
        # also cover the case where all settings come from environment variables.
        self.load_cache_plugin()
        host = self.get_option('host') or ''
        include_metadata = self.get_option('include_metadata')
        cache_key = self.get_cache_key(f'{path}:{host}:{inventory_id}:{include_metadata}')

        # cache may be True or False at this point to indicate if the inventory is being refreshed
        # get the user's cache option too to see if we should save the cache if it is changing
        user_cache_setting = self.get_option('cache')
        # read if the user has caching enabled and the cache is not being refreshed
        attempt_to_read_cache = user_cache_setting and cache
        # update if the user has caching enabled and the cache is being refreshed;
        # this is also set to True below if the cache has expired or is missing
        cache_needs_update = user_cache_setting and not cache

        inventory_data = None
        if attempt_to_read_cache:
            try:
                inventory_data = self._cache[cache_key]
            except KeyError:
                # cache expired or no cache entry yet, fetch from the API and update it below
                cache_needs_update = True

        if inventory_data is None:
            module = ControllerAPIModule(argument_spec={}, direct_params=module_params, error_callback=handle_error, warn_callback=self.warn_callback)
            # Ensure any write-scope token created for username/password auth is always released,
            # even on the success path (module.exit_json/fail_json are never called from an inventory plugin).
            try:
                inventory_data = {
                    'inventory': module.get_endpoint(inventory_url, data={'hostvars': '1', 'towervars': '1', 'all': '1'})['json'],
                    'config': None,
                }
                if include_metadata:
                    inventory_data['config'] = module.get_endpoint('/api/v2/config/')['json']
            finally:
                module.logout()

        if cache_needs_update:
            self._cache[cache_key] = inventory_data

        inventory = inventory_data['inventory']

        # To start with, create all the groups.
        for group_name in inventory:
            if group_name != '_meta':
                self.inventory.add_group(group_name)

        # Then, create all hosts and add the host vars.
        all_hosts = inventory['_meta']['hostvars']
        for host_name, host_vars in all_hosts.items():
            self.inventory.add_host(host_name)
            for var_name, var_value in host_vars.items():
                self.inventory.set_variable(host_name, var_name, var_value)

        # Lastly, create to group-host and group-group relationships, and set group vars.
        for group_name, group_content in inventory.items():
            if group_name != 'all' and group_name != '_meta':
                # First add hosts to groups
                for host_name in group_content.get('hosts', []):
                    self.inventory.add_host(host_name, group_name)
                # Then add the parent-children group relationships.
                for child_group_name in group_content.get('children', []):
                    # add the child group to groups, if its already there it will just throw a warning
                    self.inventory.add_group(child_group_name)
                    self.inventory.add_child(group_name, child_group_name)
            # Set the group vars. Note we should set group var for 'all', but not '_meta'.
            if group_name != '_meta':
                for var_name, var_value in group_content.get('vars', {}).items():
                    self.inventory.set_variable(group_name, var_name, var_value)

        # Add extra variables if told to do so
        if include_metadata:

            config_data = inventory_data['config'] or {}

            server_data = {}
            server_data['license_type'] = config_data.get('license_info', {}).get('license_type', 'unknown')
            for key in ('version', 'ansible_version'):
                server_data[key] = config_data.get(key, 'unknown')
            self.inventory.set_variable('all', 'controller_metadata', server_data)

        # Clean up the inventory.
        self.inventory.reconcile_inventory()
