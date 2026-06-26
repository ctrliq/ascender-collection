#!/usr/bin/python

# (c) 2021, Sean Sullivan
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

DOCUMENTATION = """
---
module: workflow_node_wait
author: "Sean Sullivan (@sean-m-sullivan)"
short_description: Wait for a workflow node to finish.
description:
    - Approve an approval node in a workflow job. See
      U(https://ascender-automation.org) for an overview.
options:
    workflow_job_id:
      description:
        - ID of the workflow job to monitor for node.
      required: True
      type: int
    name:
      description:
        - Name of the workflow node to wait on.
      required: True
      type: str
    interval:
      description:
        - The interval in sections, to request an update from the controller.
      required: False
      default: 1
      type: float
    timeout:
      description:
        - Maximum time in seconds to wait for a workflow job to reach approval node.
      default: 10
      type: int
extends_documentation_fragment: ctrliq.ascender.auth
"""

EXAMPLES = """
- name: Launch a workflow with a timeout of 10 seconds
  workflow_launch:
    workflow_template: "Test Workflow"
    wait: False
  register: workflow

- name: Wait for a workflow node to finish
  workflow_node_wait:
    workflow_job_id: "{{ workflow.id }}"
    name: Approval Data Step
    timeout: 120
"""

RETURN = '''
id:
    description: ID of the workflow node job that was waited on
    returned: success
    type: int
    sample: 99
status:
    description: final status of the workflow node job
    returned: success
    type: str
    sample: successful
elapsed:
    description: total time in seconds the job took to run
    returned: success
    type: float
    sample: 10.879
started:
    description: timestamp of when the job started running
    returned: success
    type: str
    sample: "2017-03-01T17:03:53.200234Z"
finished:
    description: timestamp of when the job finished
    returned: success
    type: str
    sample: "2017-03-01T17:04:04.078782Z"
job_data:
    description: dictionary containing the full job data returned by the controller
    returned: success
    type: dict
'''

from ..module_utils.controller_api import ControllerAPIModule


def main():
    # Any additional arguments that are not fields of the item can be added here
    argument_spec = dict(
        workflow_job_id=dict(type="int", required=True),
        name=dict(required=True),
        timeout=dict(type="int", default=10),
        interval=dict(type="float", default=1),
    )

    # Create a module for ourselves
    module = ControllerAPIModule(argument_spec=argument_spec)

    # Extract our parameters
    workflow_job_id = module.params.get("workflow_job_id")
    name = module.params.get("name")
    timeout = module.params.get("timeout")
    interval = module.params.get("interval")

    module.wait_on_workflow_node_url(
        url="workflow_jobs/{0}/workflow_nodes/".format(workflow_job_id),
        object_name=name,
        object_type="Workflow Node",
        timeout=timeout,
        interval=interval,
        **{
            "data": {
                "job__name": name,
            }
        }
    )

    # Attempt to look up jobs based on the status
    module.exit_json(**module.json_output)


if __name__ == "__main__":
    main()
