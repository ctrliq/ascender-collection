#!/usr/bin/python

# (c) 2017, Wayne Witzel III <wayne@riotousliving.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = '''
---
module: job_list
author: "Wayne Witzel III (@wwitzel3)"
short_description: List Ascender jobs.
description:
    - List Ascender jobs. See
      U(https://ascender-automation.org) for an overview.
options:
    status:
      description:
        - Only list jobs with this status.
      choices: ['pending', 'waiting', 'running', 'error', 'failed', 'canceled', 'successful']
      type: str
    page:
      description:
        - Page number of the results to fetch.
      type: int
    all_pages:
      description:
        - Fetch all the pages and return a single result.
      type: bool
      default: 'no'
    query:
      description:
        - Query used to further filter the list of jobs. C({"foo":"bar"}) will be passed at C(?foo=bar)
      type: dict
extends_documentation_fragment: ctrliq.ascender.auth
'''

EXAMPLES = '''
- name: List running jobs for the testing.yml playbook
  ctrliq.ascender.job_list:
    status: running
    query: {"playbook": "testing.yml"}
    controller_config_file: "~/controller.cfg"
  register: testing_jobs
'''

RETURN = '''
count:
    description: Total count of objects return
    returned: success
    type: int
    sample: 51
next:
    description: URL of the next page of results, if any
    returned: success
    type: str
    sample: /api/v2/jobs/?page=3
previous:
    description: URL of the previous page of results, if any
    returned: success
    type: str
    sample: /api/v2/jobs/?page=1
results:
    description: a list of job objects represented as dictionaries
    returned: success
    type: list
    sample: [{"allow_simultaneous": false, "artifacts": {}, "ask_credential_on_launch": false,
              "ask_inventory_on_launch": false, "ask_job_type_on_launch": false, "failed": false,
              "finished": "2017-02-22T15:09:05.633942Z", "force_handlers": false, "forks": 0, "id": 2,
              "inventory": 1, "job_explanation": "", "job_tags": "", "job_template": 5, "job_type": "run"}, ...]
'''

from ..module_utils.controller_api import ControllerAPIModule


def main():
    # Any additional arguments that are not fields of the item can be added here
    argument_spec = dict(
        status=dict(choices=['pending', 'waiting', 'running', 'error', 'failed', 'canceled', 'successful']),
        page=dict(type='int'),
        all_pages=dict(type='bool', default=False),
        query=dict(type='dict'),
    )

    # Create a module for ourselves
    module = ControllerAPIModule(
        argument_spec=argument_spec,
        mutually_exclusive=[
            ('page', 'all_pages'),
        ],
    )

    # Extract our parameters
    query = module.params.get('query')
    status = module.params.get('status')
    page = module.params.get('page')
    all_pages = module.params.get('all_pages')

    job_search_data = {}
    if page:
        job_search_data['page'] = page
    if status:
        job_search_data['status'] = status
    if query:
        job_search_data.update(query)
    if all_pages:
        job_list = module.get_all_endpoint('jobs', **{'data': job_search_data})
    else:
        job_list = module.get_endpoint('jobs', **{'data': job_search_data})
        if job_list['status_code'] != 200:
            module.fail_json(msg="Failed to list jobs, see response for details", response=job_list)

    # Attempt to look up jobs based on the status
    module.exit_json(**job_list['json'])


if __name__ == '__main__':
    main()
