#!/usr/bin/python

# (c) 2017, Wayne Witzel III <wayne@riotousliving.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = '''
---
module: role
author: "Wayne Witzel III (@wwitzel3)"
short_description: grant or revoke an Ascender role.
description:
    - Roles are used for access control, this module is for managing user access to server resources.
    - Grant or revoke Ascender roles to users. See U(https://ascender-automation.org) for an overview.
options:
    users:
      description:
        - User names, IDs, or named URLs that receive the permissions specified by the role.
      type: list
      elements: str
    teams:
      description:
        - Team names, IDs, or named URLs that receive the permissions specified by the role.
      type: list
      elements: str
    role:
      description:
        - The role type to grant/revoke.
      required: True
      choices: ["admin", "read", "member", "execute", "adhoc", "update", "use", "approval", "auditor", "project_admin", "inventory_admin", "credential_admin",
                "workflow_admin", "notification_admin", "job_template_admin", "execution_environment_admin"]
      type: str
    target_teams:
      description:
        - Team names, IDs, or named URLs that the role acts on.
        - For example, make someone a member or an admin of a team.
        - Members of a team implicitly receive the permissions that the team has.
      type: list
      elements: str
    inventories:
      description:
        - Inventory names, IDs, or named URLs the role acts on.
      type: list
      elements: str
    job_templates:
      description:
        - The job template names, IDs, or named URLs the role acts on.
      type: list
      elements: str
    workflows:
      description:
        - The workflow job template names, IDs, or named URLs the role acts on.
      type: list
      elements: str
    credentials:
      description:
        - Credential names, IDs, or named URLs the role acts on.
      type: list
      elements: str
    organizations:
      description:
        - Organization names, IDs, or named URLs the role acts on.
      type: list
      elements: str
    lookup_organization:
      description:
        - Organization name, ID, or named URL the inventories, job templates, projects, or workflows the items exists in.
        - Used to help lookup the object, for organization roles see organizations.
        - If not provided, will lookup by name only, which does not work with duplicates.
      type: str
    projects:
      description:
        - Project names, IDs, or named URLs the role acts on.
      type: list
      elements: str
    instance_groups:
      description:
        - Instance Group names, IDs, or named URLs the role acts on.
      type: list
      elements: str
    state:
      description:
        - Desired state.
        - State of present indicates the user should have the role.
        - State of absent indicates the user should have the role taken away, if they have it.
      default: "present"
      choices: ["present", "absent"]
      type: str

extends_documentation_fragment: ctrliq.ascender.auth
'''

EXAMPLES = '''
- name: Add jdoe to the member role of My Team
  ctrliq.ascender.role:
    users:
      - jdoe
    target_teams:
      - "My Team"
    role: member
    state: present

- name: Add Joe to multiple job templates and a workflow
  ctrliq.ascender.role:
    users:
      - joe
    role: execute
    workflows:
      - test-role-workflow
    job_templates:
      - jt1
      - jt2
    state: present
'''

RETURN = '''
id:
    description: The numeric database ID of the role.
    returned: on successful create or update
    type: int
    sample: 42
'''

from ..module_utils.controller_api import ControllerAPIModule


def main():

    argument_spec = dict(
        users=dict(type='list', elements='str'),
        teams=dict(type='list', elements='str'),
        role=dict(
            choices=[
                "admin",
                "read",
                "member",
                "execute",
                "adhoc",
                "update",
                "use",
                "approval",
                "auditor",
                "project_admin",
                "inventory_admin",
                "credential_admin",
                "workflow_admin",
                "notification_admin",
                "job_template_admin",
                "execution_environment_admin",
            ],
            required=True,
        ),
        target_teams=dict(type='list', elements='str'),
        inventories=dict(type='list', elements='str'),
        job_templates=dict(type='list', elements='str'),
        workflows=dict(type='list', elements='str'),
        credentials=dict(type='list', elements='str'),
        organizations=dict(type='list', elements='str'),
        lookup_organization=dict(),
        projects=dict(type='list', elements='str'),
        instance_groups=dict(type='list', elements='str'),
        state=dict(choices=['present', 'absent'], default='present'),
    )

    module = ControllerAPIModule(argument_spec=argument_spec)

    role_type = module.params.pop('role')
    role_field = role_type + '_role'
    state = module.params.pop('state')

    module.json_output['role'] = role_type

    # Gather the resource list parameters
    resource_list_param_keys = (
        'credentials',
        'inventories',
        'job_templates',
        'organizations',
        'projects',
        'target_teams',
        'workflows',
        'users',
        'teams',
        'instance_groups',
    )

    resources = {}
    for resource_group in resource_list_param_keys:
        if module.params.get(resource_group) is not None:
            resources[resource_group] = list(module.params.get(resource_group))
    if module.params.get('lookup_organization') is not None:
        resources['lookup_organization'] = module.params.get('lookup_organization')
    # Change workflows to its endpoint name.
    if 'workflows' in resources:
        resources['workflow_job_templates'] = resources.pop('workflows')

    # Set lookup data to use
    lookup_data = {}
    if 'lookup_organization' in resources:
        lookup_data['organization'] = module.resolve_name_to_id('organizations', resources['lookup_organization'])
        resources.pop('lookup_organization')

    # Lookup actor data
    # separate actors from resources
    actor_data = {}
    missing_items = []
    # Lookup Resources
    resource_data = {}
    for key, value in resources.items():
        for resource in value:
            # Attempt to look up project based on the provided name, ID, or named URL and lookup data
            lookup_key = key
            # These endpoints have no organization field, so the lookup_organization filter cannot be applied
            if key in ('organizations', 'users', 'teams', 'instance_groups'):
                lookup_data_populated = {}
            else:
                lookup_data_populated = lookup_data
            if key == 'target_teams':
                lookup_key = 'teams'
            data = module.get_one(lookup_key, name_or_id=resource, data=lookup_data_populated)
            if data is None:
                missing_items.append(resource)
            else:
                if key == 'users' or key == 'teams':
                    actor_data.setdefault(key, []).append(data)
                elif key == 'target_teams':
                    resource_data.setdefault('teams', []).append(data)
                else:
                    resource_data.setdefault(key, []).append(data)
    if len(missing_items) > 0:
        module.fail_json(
            msg=f'There were {len(missing_items)} missing items, missing items: {missing_items}', changed=False
        )

    # build association agenda
    associations = {}
    for actor_type, actors in actor_data.items():
        for key, value in resource_data.items():
            for resource in value:
                resource_roles = resource['summary_fields']['object_roles']
                if role_field not in resource_roles:
                    available_roles = ', '.join(list(resource_roles.keys()))
                    module.fail_json(
                        msg=f'Resource {resource["url"]} has no role {role_field}, available roles: {available_roles}', changed=False
                    )
                role_data = resource_roles[role_field]
                endpoint = f'/roles/{role_data["id"]}/{actor_type}/'
                associations.setdefault(endpoint, [])
                for actor in actors:
                    associations[endpoint].append(actor['id'])

    # perform associations
    for association_endpoint, new_association_list in associations.items():
        response = module.get_all_endpoint(association_endpoint)
        existing_associated_ids = [association['id'] for association in response['json']['results']]

        if state == 'present':
            for an_id in list(set(new_association_list) - set(existing_associated_ids)):
                response = module.post_endpoint(association_endpoint, **{'data': {'id': int(an_id)}})
                if response['status_code'] == 204:
                    module.json_output['changed'] = True
                else:
                    module.fail_json(msg=f"Failed to grant role. {response['json'].get('detail', response['json'].get('msg', 'unknown'))}")
        else:
            for an_id in list(set(existing_associated_ids) & set(new_association_list)):
                response = module.post_endpoint(association_endpoint, **{'data': {'id': int(an_id), 'disassociate': True}})
                if response['status_code'] == 204:
                    module.json_output['changed'] = True
                else:
                    module.fail_json(msg=f"Failed to revoke role. {response['json'].get('detail', response['json'].get('msg', 'unknown'))}")

    module.exit_json(**module.json_output)


if __name__ == '__main__':
    main()
