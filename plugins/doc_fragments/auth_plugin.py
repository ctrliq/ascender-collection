
# Copyright: (c) 2020, Ansible by Red Hat, Inc
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

class ModuleDocFragment:

    # Ascender controller documentation fragment
    DOCUMENTATION = r'''
options:
  host:
    description: The network address of your Ascender controller host.
    env:
    - name: CONTROLLER_HOST
  username:
    description: The user that you plan to use to access inventories on the controller.
    env:
    - name: CONTROLLER_USERNAME
  password:
    description: The password for your controller user.
    env:
    - name: CONTROLLER_PASSWORD
  oauth_token:
    description:
    - The OAuth token to use.
    env:
    - name: CONTROLLER_OAUTH_TOKEN
  verify_ssl:
    description:
    - Specify whether Ansible should verify the SSL certificate of the controller host.
    - Defaults to True, but this is handled by the shared module_utils code
    type: bool
    env:
    - name: CONTROLLER_VERIFY_SSL
    aliases: [ validate_certs ]
  request_timeout:
    description:
    - Specify the timeout Ansible should use in requests to the controller host.
    - Defaults to 10 seconds
    type: float
    env:
    - name: CONTROLLER_REQUEST_TIMEOUT

notes:
- We will attempt to find a config file in standard locations
  (./controller_cli.cfg, ~/.controller_cli.cfg, /etc/controller/controller_cli.cfg).
- The config file should be in the following format
    host=hostname
    username=username
    password=password
'''
