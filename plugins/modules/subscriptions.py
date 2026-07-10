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
changed:
    description: This module always performs a write (the given credentials are stored on the
        controller for future use), so this is always true.
    returned: always
    type: bool
    sample: true
subscriptions:
    description: dictionary containing information about the subscriptions
    returned: If login succeeded and not in check mode
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

    # This module always performs a write: the given username/password are stored on the
    # controller for future use in retrieving renewal or expanded subscriptions (see the
    # module docs). Handle check mode ourselves, before calling post_endpoint, so we can
    # avoid contacting the subscription service and still return a consistent result. Note
    # that subscriptions cannot be returned in check mode since fetching them requires
    # actually calling out to the subscription service.
    if module.check_mode:
        json_output['changed'] = True
        module.exit_json(**json_output)

    post_data = {
        'subscriptions_password': module.params.get('password'),
        'subscriptions_username': module.params.get('username'),
    }
    response = module.post_endpoint('config/subscriptions', data=post_data)
    if response['status_code'] >= 400:
        module.fail_json(msg="Failed to fetch subscriptions, see response for details", response=response)
    json_output['changed'] = True
    all_subscriptions = response['json']
    json_output['subscriptions'] = []
    for subscription in all_subscriptions:
        add = True
        for key in module.params.get('filters').keys():
            value = subscription.get(key, None)
            if isinstance(value, str):
                # Only string fields can be checked for containment against the filter value.
                if module.params.get('filters')[key] not in value:
                    add = False
            else:
                # The field is missing, None, or a non-string (e.g. int/bool) value, so the
                # filter value cannot be contained in it. Treat this as a non-match instead of
                # raising a TypeError or silently including the subscription.
                add = False
        if add:
            json_output['subscriptions'].append(subscription)

    module.exit_json(**json_output)


if __name__ == '__main__':
    main()
