
# Copyright: (c) 2017, Wayne Witzel III <wayne@riotousliving.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

class ModuleDocFragment:

    # Ascender controller documentation fragment
    DOCUMENTATION = r'''
options:
  controller_host:
    description:
    - URL to your Ascender controller instance.
    - If value not set, will try environment variable C(CONTROLLER_HOST) and then config files
    - If value not specified by any means, the value of C(127.0.0.1) will be used
    type: str
  controller_username:
    description:
    - Username for your controller instance.
    - If value not set, will try environment variable C(CONTROLLER_USERNAME) and then config files
    type: str
  controller_password:
    description:
    - Password for your controller instance.
    - If value not set, will try environment variable C(CONTROLLER_PASSWORD) and then config files
    type: str
  controller_oauthtoken:
    description:
    - The OAuth token to use.
    - This value can be in one of two formats.
    - A string which is the token itself. (i.e. bqV5txm97wqJqtkxlMkhQz0pKhRMMX)
    - A dictionary structure as returned by the token module.
    - If value not set, will try environment variable C(CONTROLLER_OAUTH_TOKEN) and then config files
    type: raw
    version_added: "3.7.0"
  validate_certs:
    description:
    - Whether to allow insecure connections to Ascender.
    - If C(no), SSL certificates will not be validated.
    - This should only be used on personally controlled sites using self-signed certificates.
    - If value not set, will try environment variable C(CONTROLLER_VERIFY_SSL) and then config files
    type: bool
  request_timeout:
    description:
    - Specify the timeout Ansible should use in requests to the controller host.
    - Defaults to 10s, but this is handled by the shared module_utils code
    - If value not set, will try environment variable C(CONTROLLER_REQUEST_TIMEOUT) and then config files
    type: float
  controller_config_file:
    description:
    - Path to the controller config file.
    - If provided, the other locations for config files will not be considered.
    type: path

notes:
- If no I(controller_config_file) is provided we will attempt to find a config file in standard locations
  (./controller_cli.cfg, ~/.controller_cli.cfg, /etc/controller/controller_cli.cfg).
- I(controller_config_file) should be in the following format
    host=hostname
    username=username
    password=password
'''
