#!/usr/bin/python

# (c) 2019, John Westcott IV <john.westcott.iv@redhat.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = '''
---
module: subscriptions
author: "John Westcott IV (@john-westcott-iv)"
short_description: Get subscription list
description:
    - Get subscriptions available to Ascender. See
      U(https://ascender-automation.org) for an overview.
options:
    username:
      description:
        - Red Hat or Red Hat Satellite username to get available subscriptions.
        - The credentials you use will be stored for future use in retrieving renewal or expanded subscriptions
      required: True
      type: str
    password:
      description:
        - Red Hat or Red Hat Satellite password to get available subscriptions.
        - The credentials you use will be stored for future use in retrieving renewal or expanded subscriptions
      required: True
      type: str
    filters:
      description:
        - Client side filters to apply to the subscriptions.
        - For any entries in this dict, if there is a corresponding entry in the subscription it must contain the value from this dict
        - Note This is a client side search, not an API side search
      required: False
      type: dict
      default: {}
extends_documentation_fragment: ctrliq.ascender.auth
'''

EXAMPLES = '''
- name: Get subscriptions
  ctrliq.ascender.subscriptions:
    username: "my_username"
    password: "My Password"

- name: Get subscriptions with a filter
  ctrliq.ascender.subscriptions:
    username: "my_username"
    password: "My Password"
    filters:
      product_name: "Red Hat Ansible Automation Platform"
      support_level: "Self-Support"
'''

RETURN = '''
subscriptions:
    description: dictionary containing information about the subscriptions
    returned: If login succeeded
    type: dict
'''

from ..module_utils.controller_api import ControllerAPIModule


def main():

    module = ControllerAPIModule(
        argument_spec=dict(
            username=dict(type='str', required=True),
            password=dict(type='str', no_log=True, required=True),
            filters=dict(type='dict', required=False, default={}),
        ),
    )

    json_output = {'changed': False}

    # Check if the controller is already licensed
    post_data = {
        'subscriptions_password': module.params.get('password'),
        'subscriptions_username': module.params.get('username'),
    }
    response = module.post_endpoint('config/subscriptions', data=post_data)
    if response['status_code'] >= 400:
        module.fail_json(msg="Failed to fetch subscriptions, see response for details", response=response)
    all_subscriptions = response['json']
    json_output['subscriptions'] = []
    for subscription in all_subscriptions:
        add = True
        for key in module.params.get('filters').keys():
            if subscription.get(key, None) and module.params.get('filters')[key] not in subscription.get(key):
                add = False
        if add:
            json_output['subscriptions'].append(subscription)

    module.exit_json(**json_output)


if __name__ == '__main__':
    main()
