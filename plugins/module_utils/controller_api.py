

from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible.module_utils.urls import Request, SSLValidationError, ConnectionError
from ansible.module_utils.parsing.convert_bool import boolean as strtobool
from io import StringIO
from urllib.error import HTTPError
from http.cookiejar import CookieJar
from urllib.parse import urlparse, urlencode, quote
from configparser import ConfigParser, NoOptionError
from socket import getaddrinfo, IPPROTO_TCP
import time
import re
from json import loads, dumps
from os.path import isfile, expanduser, split, join, exists, isdir
from os import access, R_OK, getcwd, environ

try:
    from ansible.module_utils.compat.version import LooseVersion as Version
except ImportError:
    try:
        from packaging.version import Version
    except ImportError:
        raise AssertionError('To use this plugin or module you need to use Python >= 3.12')

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False


class ConfigFileException(Exception):
    pass


class ItemNotDefined(Exception):
    pass


class ControllerModule(AnsibleModule):
    url = None
    AUTH_ARGSPEC = dict(
        controller_host=dict(
            required=False,
            fallback=(env_fallback, ['CONTROLLER_HOST']),
        ),
        controller_username=dict(
            required=False,
            fallback=(env_fallback, ['CONTROLLER_USERNAME']),
        ),
        controller_password=dict(
            no_log=True,
            required=False,
            fallback=(env_fallback, ['CONTROLLER_PASSWORD']),
        ),
        validate_certs=dict(
            type='bool',
            required=False,
            fallback=(env_fallback, ['CONTROLLER_VERIFY_SSL']),
        ),
        request_timeout=dict(type='float', required=False, fallback=(env_fallback, ['CONTROLLER_REQUEST_TIMEOUT'])),
        controller_oauthtoken=dict(
            type='raw',
            no_log=True,
            required=False,
            fallback=(env_fallback, ['CONTROLLER_OAUTH_TOKEN']),
        ),
        controller_config_file=dict(
            type='path',
            required=False,
            default=None,
        ),
    )
    # Associations of these types are ordered and have special consideration in the modified associations function
    ordered_associations = ['instance_groups', 'galaxy_credentials', 'input_inventories']
    short_params = {
        'host': 'controller_host',
        'username': 'controller_username',
        'password': 'controller_password',
        'verify_ssl': 'validate_certs',
        'request_timeout': 'request_timeout',
        'oauth_token': 'controller_oauthtoken',
    }
    host = '127.0.0.1'
    username = None
    password = None
    verify_ssl = True
    request_timeout = 10
    oauth_token = None
    oauth_token_id = None
    authenticated = False
    config_name = 'controller_cli.cfg'
    version_checked = False
    error_callback = None
    warn_callback = None

    def __init__(self, argument_spec=None, direct_params=None, error_callback=None, warn_callback=None, **kwargs):
        full_argspec = {}
        full_argspec.update(ControllerModule.AUTH_ARGSPEC)
        full_argspec.update(argument_spec)
        kwargs.setdefault('supports_check_mode', True)

        self.error_callback = error_callback
        self.warn_callback = warn_callback

        self.json_output = {'changed': False}

        if direct_params is not None:
            self.params = direct_params
        else:
            super().__init__(argument_spec=full_argspec, **kwargs)

        self.load_config_files()

        # Parameters specified on command line will override settings in any config
        for short_param, long_param in self.short_params.items():
            direct_value = self.params.get(long_param)
            if direct_value is not None:
                setattr(self, short_param, direct_value)

        # Perform magic depending on whether controller_oauthtoken is a string or a dict
        if self.params.get('controller_oauthtoken'):
            token_param = self.params.get('controller_oauthtoken')
            if isinstance(token_param, dict):
                if 'token' in token_param:
                    self.oauth_token = self.params.get('controller_oauthtoken')['token']
                else:
                    self.fail_json(msg="The provided dict in controller_oauthtoken did not properly contain the token entry")
            elif isinstance(token_param, str):
                self.oauth_token = self.params.get('controller_oauthtoken')
            else:
                error_msg = f"The provided controller_oauthtoken type was not valid ({type(token_param).__name__}). Valid options are str or dict."
                self.fail_json(msg=error_msg)

        # Perform some basic validation
        if not re.match('^https{0,1}://', self.host):
            self.host = f"https://{self.host}"

        # Try to parse the hostname as a url
        try:
            self.url = urlparse(self.host)
            # Store URL prefix for later use in build_url
            self.url_prefix = self.url.path
        except Exception as e:
            self.fail_json(msg=f"Unable to parse controller_host as a URL ({e}): {self.host}")

        # Try to resolve the hostname
        try:
            proxy_env_var_name = f"{self.url.scheme}_proxy"
            if not environ.get(proxy_env_var_name) and not environ.get(proxy_env_var_name.upper()):
                getaddrinfo(self.url.hostname, self.url.port, proto=IPPROTO_TCP)
        except Exception as e:
            self.fail_json(msg=f"Unable to resolve controller_host ({e}): {self.url.hostname}")

    def build_url(self, endpoint, query_params=None):
        # Make sure we start with /api/vX
        if not endpoint.startswith("/"):
            endpoint = f"/{endpoint}"
        prefix = self.url_prefix.rstrip("/")
        if not endpoint.startswith(prefix + "/api/"):
            endpoint = f"{prefix}/api/v2{endpoint}"
        if not endpoint.endswith('/') and '?' not in endpoint:
            endpoint = f"{endpoint}/"

        # Update the URL path with the endpoint
        url = self.url._replace(path=endpoint)

        if query_params:
            url = url._replace(query=urlencode(query_params))

        return url

    def load_config_files(self):
        # Load config files from least specific to most specific
        config_files = ['/etc/controller/controller_cli.cfg', join(expanduser("~"), f".{self.config_name}")]
        local_dir = getcwd()
        config_files.append(join(local_dir, self.config_name))
        while split(local_dir)[1]:
            local_dir = split(local_dir)[0]
            config_files.insert(2, join(local_dir, f".{self.config_name}"))

        # If we have a specified controller config, load it
        if self.params.get('controller_config_file'):
            duplicated_params = [fn for fn in self.AUTH_ARGSPEC if fn != 'controller_config_file' and self.params.get(fn) is not None]
            if duplicated_params:
                self.warn(
                    f"The parameter(s) {', '.join(duplicated_params)} were provided at the same time as controller_config_file. "
                    "Precedence may be unstable, we suggest either using config file or params."
                )
            try:
                self.load_config(self.params.get('controller_config_file'))
            except ConfigFileException as cfe:
                # Since we were told specifically to load this we want it to fail if we have an error
                self.fail_json(msg=str(cfe))
        else:
            for config_file in config_files:
                if exists(config_file) and not isdir(config_file):
                    # Only throw a formatting error if the file exists and is not a directory
                    try:
                        self.load_config(config_file)
                    except ConfigFileException:
                        self.fail_json(msg=f'The config file {config_file} is not properly formatted')

    def load_config(self, config_path):
        # Validate the config file is an actual file
        if not isfile(config_path):
            raise ConfigFileException('The specified config file does not exist')

        if not access(config_path, R_OK):
            raise ConfigFileException("The specified config file cannot be read")

        # Read in the file contents:
        with open(config_path, 'r', encoding='utf-8') as f:
            config_string = f.read()

        # First try to yaml load the content (which will also load json)
        try:
            try_config_parsing = True
            if HAS_YAML:
                try:
                    config_data = yaml.load(config_string, Loader=yaml.SafeLoader)
                    # If this is an actual ini file, yaml will return the whole thing as a string instead of a dict
                    if not isinstance(config_data, dict):
                        raise AssertionError("The yaml config file is not properly formatted as a dict.")
                    try_config_parsing = False

                except (AttributeError, yaml.YAMLError, AssertionError):
                    try_config_parsing = True

            if try_config_parsing:
                # Support config files with a missing [general] section by prepending it if missing
                if '[general]' not in config_string:
                    config_string = f'[general]\n{config_string}'

                config = ConfigParser()

                try:
                    placeholder_file = StringIO(config_string)
                    config.read_file(placeholder_file)

                    # If we made it here then we have values from reading the ini file, so let's pull them out into a dict
                    config_data = {}
                    for honored_setting in self.short_params:
                        try:
                            config_data[honored_setting] = config.get('general', honored_setting)
                        except NoOptionError:
                            pass

                except Exception as e:
                    raise ConfigFileException(f"An unknown exception occurred trying to load INI config file: {e}") from e

        except Exception as e:
            raise ConfigFileException(f"An unknown exception occurred trying to load config file: {e}") from e

        # If we made it here, we have a dict which has values in it from our config, any final settings logic can be performed here
        for honored_setting in self.short_params:
            if honored_setting in config_data:
                # Verify SSL must be a boolean
                if honored_setting == 'verify_ssl':
                    if isinstance(config_data[honored_setting], str):
                        setattr(self, honored_setting, strtobool(config_data[honored_setting]))
                    else:
                        setattr(self, honored_setting, bool(config_data[honored_setting]))
                # The request timeout needs to be a float; INI config files always produce strings
                elif honored_setting == 'request_timeout':
                    try:
                        setattr(self, honored_setting, float(config_data[honored_setting]))
                    except ValueError as e:
                        raise ConfigFileException(
                            f"The request_timeout setting in the config file must be a number, got: {config_data[honored_setting]}"
                        ) from e
                else:
                    setattr(self, honored_setting, config_data[honored_setting])

    def logout(self):
        # This method is intended to be overridden
        pass

    def fail_json(self, **kwargs):
        # Try to log out if we are authenticated
        self.logout()
        if self.error_callback:
            self.error_callback(**kwargs)
        else:
            super().fail_json(**kwargs)

    def exit_json(self, **kwargs):
        # Try to log out if we are authenticated
        self.logout()
        super().exit_json(**kwargs)

    def warn(self, warning):
        if self.warn_callback is not None:
            self.warn_callback(warning)
        else:
            super().warn(warning)


class ControllerAPIModule(ControllerModule):
    _COLLECTION_VERSION = "25.4.0"
    _COLLECTION_TYPE = "ascender"
    # This maps the collection type (awx/ascender/tower) to the X-API-Product-Name
    # value returned by the server (see server_product_name() in
    # awx/main/utils/licensing.py). Ascender runs on the open license, so its
    # server reports 'AWX'.
    collection_to_version = {
        'awx': 'AWX',
        'ascender': 'AWX',
        'controller': 'Red Hat Ansible Automation Platform',
    }
    session = None
    IDENTITY_FIELDS = {'users': 'username', 'workflow_job_template_nodes': 'identifier', 'instances': 'hostname'}
    ENCRYPTED_STRING = "$encrypted$"

    def __init__(self, argument_spec, direct_params=None, error_callback=None, warn_callback=None, **kwargs):
        kwargs.setdefault('supports_check_mode', True)

        super().__init__(argument_spec=argument_spec, direct_params=direct_params, error_callback=error_callback, warn_callback=warn_callback, **kwargs)
        self.session = Request(cookies=CookieJar(), timeout=self.request_timeout, validate_certs=self.verify_ssl)

        if 'update_secrets' in self.params:
            self.update_secrets = self.params.pop('update_secrets')
        else:
            self.update_secrets = True

    @staticmethod
    def get_name_field_from_endpoint(endpoint):
        return ControllerAPIModule.IDENTITY_FIELDS.get(endpoint, 'name')

    def get_item_name(self, item, allow_unknown=False):
        if item:
            if 'name' in item:
                return item['name']

            for field_name in ControllerAPIModule.IDENTITY_FIELDS.values():
                if field_name in item:
                    return item[field_name]

            if item.get('type', None) in ('o_auth2_access_token', 'credential_input_source'):
                return item['id']

        if allow_unknown:
            return 'unknown'

        if item:
            self.fail_json(msg=f"Cannot determine identity field for {item.get('type', 'unknown')} object.")
        else:
            self.fail_json(msg='Cannot determine identity field for Undefined object.')

    def head_endpoint(self, endpoint, **kwargs):
        return self.make_request('HEAD', endpoint, **kwargs)

    def get_endpoint(self, endpoint, **kwargs):
        return self.make_request('GET', endpoint, **kwargs)

    def patch_endpoint(self, endpoint, **kwargs):
        # Handle check mode
        if self.check_mode:
            self.json_output['changed'] = True
            self.exit_json(**self.json_output)

        return self.make_request('PATCH', endpoint, **kwargs)

    def post_endpoint(self, endpoint, **kwargs):
        # Handle check mode
        if self.check_mode:
            self.json_output['changed'] = True
            self.exit_json(**self.json_output)

        return self.make_request('POST', endpoint, **kwargs)

    def delete_endpoint(self, endpoint, **kwargs):
        # Handle check mode
        if self.check_mode:
            self.json_output['changed'] = True
            self.exit_json(**self.json_output)

        return self.make_request('DELETE', endpoint, **kwargs)

    def get_all_endpoint(self, endpoint, **kwargs):
        response = self.get_endpoint(endpoint, **kwargs)
        if response['status_code'] != 200:
            self.fail_json(msg=f"Got a {response['status_code']} response when trying to list {endpoint}", response=response)
        if 'next' not in response['json']:
            self.fail_json(msg=f'Expected list from API at {endpoint}, got unexpected response shape')
        next_page = response['json']['next']

        if response['json']['count'] > 10000:
            self.fail_json(msg='The number of items being queried for is higher than 10,000.')

        while next_page is not None:
            next_response = self.get_endpoint(next_page)
            if next_response['status_code'] != 200:
                self.fail_json(msg=f"Got a {next_response['status_code']} response when trying to paginate {endpoint}", response=next_response)
            response['json']['results'] = response['json']['results'] + next_response['json']['results']
            next_page = next_response['json']['next']
            response['json']['next'] = next_page
        return response

    def get_one(self, endpoint, name_or_id=None, allow_none=True, check_exists=False, **kwargs):
        new_kwargs = kwargs.copy()
        response = None

        # A named URL is pretty unique so if we have a ++ in the name then lets start by looking for that
        # This also needs to go first because if there was data passed in kwargs and we do the next lookup first there may be results
        if name_or_id is not None and '++' in name_or_id:
            # Maybe someone gave us a named URL so lets see if we get anything from that.
            url_quoted_name = quote(name_or_id, safe="+")
            named_endpoint = f'{endpoint}/{url_quoted_name}/'
            named_response = self.get_endpoint(named_endpoint, **{'return_none_on_404': True})

            if named_response is not None and named_response['status_code'] == 200 and 'json' in named_response:
                # We found a named item but we expect to deal with a list view so mock that up
                response = {
                    'json': {
                        'count': 1,
                        'results': [named_response['json']],
                    }
                }

        # Since we didn't have a named URL, lets try and find it with a general search
        if response is None:
            if name_or_id:
                name_field = self.get_name_field_from_endpoint(endpoint)
                new_data = kwargs.get('data', {}).copy()
                if name_field in new_data:
                    self.fail_json(msg=f"You can't specify the field {name_field} in your search data if using the name_or_id field")

                try:
                    new_data['or__id'] = int(name_or_id)
                    new_data[f'or__{name_field}'] = name_or_id
                except ValueError:
                    # If we get a value error, then we didn't have an integer so we can just pass and fall down to the fail
                    new_data[name_field] = name_or_id
                new_kwargs['data'] = new_data

            response = self.get_endpoint(endpoint, **new_kwargs)

            if response['status_code'] != 200:
                fail_msg = f"Got a {response['status_code']} response when trying to get one from {endpoint}"
                if 'detail' in response.get('json', {}):
                    fail_msg += f", detail: {response['json']['detail']}"
                self.fail_json(msg=fail_msg)

            if 'count' not in response['json'] or 'results' not in response['json']:
                self.fail_json(msg="The endpoint did not provide count and results")

        if response['json']['count'] == 0:
            if allow_none:
                return None
            else:
                self.fail_wanted_one(response, endpoint, new_kwargs.get('data'))
        elif response['json']['count'] > 1:
            if name_or_id:
                # Since we did a name or ID search and got > 1 return something if the id matches
                for asset in response['json']['results']:
                    if str(asset['id']) == name_or_id:
                        return asset
            # We got > 1 and either didn't find something by ID (which means multiple names)
            # Or we weren't running with a or search and just got back too many to begin with.
            self.fail_wanted_one(response, endpoint, new_kwargs.get('data'))

        if check_exists:
            self.json_output['id'] = response['json']['results'][0]['id']
            self.exit_json(**self.json_output)

        return response['json']['results'][0]

    def fail_wanted_one(self, response, endpoint, query_params):
        sample = response.copy()
        if len(sample['json']['results']) > 1:
            sample['json']['results'] = sample['json']['results'][:2] + ['...more results snipped...']
        url = self.build_url(endpoint, query_params)
        host_length = len(self.host)
        display_endpoint = url.geturl()[host_length:]  # truncate to not include the base URL
        self.fail_json(
            msg=f"Request to {display_endpoint} returned {response['json']['count']} items, expected 1",
            query=query_params,
            response=sample,
            total_results=response['json']['count'],
        )

    def get_exactly_one(self, endpoint, name_or_id=None, **kwargs):
        return self.get_one(endpoint, name_or_id=name_or_id, allow_none=False, **kwargs)

    def resolve_name_to_id(self, endpoint, name_or_id):
        return self.get_exactly_one(endpoint, name_or_id)['id']

    def make_request(self, method, endpoint, **kwargs):
        # In case someone is calling us directly; make sure we were given a method, let's not just assume a GET
        if not method:
            raise Exception("The HTTP method must be defined")

        if method in ['POST', 'PUT', 'PATCH']:
            url = self.build_url(endpoint)
        else:
            url = self.build_url(endpoint, query_params=kwargs.get('data'))

        # Extract the headers, this will be used in a couple of places
        headers = kwargs.get('headers', {})

        # Authenticate to AWX (if we don't have a token and if not already done so)
        if not self.oauth_token and not self.authenticated:
            # This method will set a cookie in the cookie jar for us and also an oauth_token
            self.authenticate(**kwargs)
        if self.oauth_token:
            # If we have a oauth token, we just use a bearer header
            headers['Authorization'] = f'Bearer {self.oauth_token}'

        if method in ['POST', 'PUT', 'PATCH']:
            headers.setdefault('Content-Type', 'application/json')
            kwargs['headers'] = headers

        data = None  # Important, if content type is not JSON, this should not be dict type
        if headers.get('Content-Type', '') == 'application/json':
            data = dumps(kwargs.get('data', {}))

        try:
            response = self.session.open(
                method, url.geturl(),
                headers=headers,
                timeout=self.request_timeout,
                validate_certs=self.verify_ssl,
                follow_redirects=True,
                data=data
            )
        except SSLValidationError as ssl_err:
            self.fail_json(msg=f"Could not establish a secure connection to your host ({ssl_err}): {url.netloc}.")
        except ConnectionError as con_err:
            self.fail_json(msg=f"There was a network error of some kind trying to connect to your host ({con_err}): {url.netloc}.")
        except HTTPError as he:
            # Sanity check: Did the server send back some kind of internal error?
            if he.code >= 500:
                self.fail_json(msg=f'The host sent back a server error ({he}): {url.path}. Please check the logs and try again later')
            # Sanity check: Did we fail to authenticate properly?  If so, fail out now; this is always a failure.
            elif he.code == 401:
                self.fail_json(msg=f'Invalid authentication credentials for {url.path} (HTTP 401).')
            # Sanity check: Did we get a forbidden response, which means that the user isn't allowed to do this? Report that.
            elif he.code == 403:
                self.fail_json(msg=f"You don't have permission to {method} to {url.path} (HTTP 403).")
            # Sanity check: Did we get a 404 response?
            # Requests with primary keys will return a 404 if there is no response, and we want to consistently trap these.
            elif he.code == 404:
                if kwargs.get('return_none_on_404', False):
                    return None
                self.fail_json(msg=f'The requested object could not be found at {url.path}.')
            # Sanity check: Did we get a 405 response?
            # A 405 means we used a method that isn't allowed. Usually this is a bad request, but it requires special treatment because the
            # API sends it as a logic error in a few situations (e.g. trying to cancel a job that isn't running).
            elif he.code == 405:
                self.fail_json(msg=f"Cannot make a request with the {method} method to this endpoint {url.path}")
            # Sanity check: Did we get some other kind of error?  If so, write an appropriate error message.
            elif he.code >= 400:
                # We are going to return a 400 so the module can decide what to do with it
                page_data = he.read()
                try:
                    return {'status_code': he.code, 'json': loads(page_data)}
                # JSONDecodeError only available on Python 3.5+
                except ValueError:
                    return {'status_code': he.code, 'text': page_data}
            else:
                self.fail_json(msg=f"Unexpected return code when calling {url.geturl()}: {he}")
        except Exception as e:
            self.fail_json(msg=f"There was an unknown error when trying to connect to {url.geturl()}: {type(e).__name__} {e}")

        if not self.version_checked:
            controller_type = response.getheader('X-API-Product-Name', None)
            controller_version = response.getheader('X-API-Product-Version', None)

            parsed_collection_version = Version(self._COLLECTION_VERSION).version
            if controller_version:
                parsed_controller_version = Version(controller_version).version
                if controller_type == 'AWX':
                    collection_compare_ver = parsed_collection_version[0]
                    controller_compare_ver = parsed_controller_version[0]
                else:
                    collection_compare_ver = f"{parsed_collection_version[0]}.{parsed_collection_version[1]}"
                    controller_compare_ver = f'{parsed_controller_version[0]}.{parsed_controller_version[1]}'

                if self._COLLECTION_TYPE not in self.collection_to_version or self.collection_to_version[self._COLLECTION_TYPE] != controller_type:
                    self.warn(f"You are using the {self._COLLECTION_TYPE} version of this collection but connecting to {controller_type}")
                elif collection_compare_ver != controller_compare_ver:
                    self.warn(f"You are running collection version {self._COLLECTION_VERSION} but connecting to {controller_type} version {controller_version}")

            self.version_checked = True

        response_body = ''
        try:
            response_body = response.read()
        except Exception as e:
            self.fail_json(msg=f"Failed to read response body: {e}")

        response_json = {}
        if response_body:
            try:
                response_json = loads(response_body)
            except Exception as e:
                self.fail_json(msg=f"Failed to parse the response json: {e}")

        status_code = response.status
        return {'status_code': status_code, 'json': response_json}

    def authenticate(self, **kwargs):
        if self.username and self.password:
            # Attempt to get a token from /api/v2/tokens/ by giving it our username/password combo
            # If we have a username and password, we need to get a session cookie
            login_data = {
                "description": "Automation Platform Controller Module Token",
                "application": None,
                "scope": "write",
            }
            # Preserve URL prefix
            endpoint = self.url_prefix.rstrip('/') + '/api/v2/tokens/'
            # Post to the tokens endpoint with basic auth to try and get a token
            api_token_url = (self.url._replace(path=endpoint)).geturl()

            try:
                response = self.session.open(
                    'POST',
                    api_token_url,
                    validate_certs=self.verify_ssl,
                    timeout=self.request_timeout,
                    follow_redirects=True,
                    force_basic_auth=True,
                    url_username=self.username,
                    url_password=self.password,
                    data=dumps(login_data),
                    headers={'Content-Type': 'application/json'},
                )
            except HTTPError as he:
                try:
                    resp = he.read()
                except Exception as e:
                    resp = f'unknown {e}'
                self.fail_json(msg=f'Failed to get token: {he}', response=resp)
            except Exception as e:
                # Sanity check: Did the server send back some kind of internal error?
                self.fail_json(msg=f'Failed to get token: {e}')

            token_response = None
            try:
                token_response = response.read()
                response_json = loads(token_response)
                self.oauth_token_id = response_json['id']
                self.oauth_token = response_json['token']
                self.authenticated = True
            except Exception as e:
                self.fail_json(msg=f"Failed to extract token information from login response: {e}", **{'response': token_response})

    def delete_if_needed(self, existing_item, on_delete=None, auto_exit=True):
        # This will exit from the module on its own.
        # If the method successfully deletes an item and on_delete param is defined,
        #   the on_delete parameter will be called as a method passing in this object and the json from the response
        # This will return one of two things:
        #   1. None if the existing_item is not defined (so no delete needs to happen)
        #   2. The response from AWX from calling the delete on the endpont. It's up to you to process the response and exit from the module
        # Note: common error codes from the AWX API can cause the module to fail
        if existing_item:
            # If we have an item, we can try to delete it
            try:
                item_url = existing_item['url']
                item_type = existing_item['type']
                item_id = existing_item['id']
                item_name = self.get_item_name(existing_item, allow_unknown=True)
            except KeyError as ke:
                self.fail_json(msg=f"Unable to process delete of item due to missing data {ke}")

            response = self.delete_endpoint(item_url)

            if response['status_code'] in [202, 204]:
                if on_delete:
                    on_delete(self, response['json'])
                self.json_output['changed'] = True
                self.json_output['id'] = item_id
                if auto_exit:
                    self.exit_json(**self.json_output)
                else:
                    return self.json_output
            else:
                if 'json' in response and '__all__' in response['json']:
                    self.fail_json(msg=f"Unable to delete {item_type} {item_name}: {response['json']['__all__'][0]}")
                elif 'json' in response:
                    # This is from a project delete (if there is an active job against it)
                    if 'error' in response['json']:
                        self.fail_json(msg=f"Unable to delete {item_type} {item_name}: {response['json']['error']}")
                    else:
                        self.fail_json(msg=f"Unable to delete {item_type} {item_name}: {response['json']}")
                else:
                    self.fail_json(msg=f"Unable to delete {item_type} {item_name}: {response['status_code']}")
        else:
            if auto_exit:
                self.exit_json(**self.json_output)
            else:
                return self.json_output

    def modify_associations(self, association_endpoint, new_association_list):
        # if we got None instead of [] we are not modifying the association_list
        if new_association_list is None:
            return

        # First get the existing associations
        response = self.get_all_endpoint(association_endpoint)
        existing_associated_ids = [association['id'] for association in response['json']['results']]

        # Some associations can be ordered (like galaxy credentials)
        if association_endpoint.strip('/').split('/')[-1] in self.ordered_associations:
            if existing_associated_ids == new_association_list:
                return  # If the current associations EXACTLY match the desired associations then we can return
            removal_list = existing_associated_ids  # because of ordering, we have to remove everything
            addition_list = new_association_list  # re-add everything back in-order
        else:
            if set(existing_associated_ids) == set(new_association_list):
                return
            removal_list = set(existing_associated_ids) - set(new_association_list)
            addition_list = set(new_association_list) - set(existing_associated_ids)

        for an_id in removal_list:
            response = self.post_endpoint(association_endpoint, **{'data': {'id': int(an_id), 'disassociate': True}})
            if response['status_code'] == 204:
                self.json_output['changed'] = True
            else:
                self.fail_json(msg=f"Failed to disassociate item {response['json'].get('detail', response['json'])}")

        for an_id in addition_list:
            response = self.post_endpoint(association_endpoint, **{'data': {'id': int(an_id)}})
            if response['status_code'] == 204:
                self.json_output['changed'] = True
            else:
                self.fail_json(msg=f"Failed to associate item {response['json'].get('detail', response['json'])}")

    def copy_item(self, existing_item, copy_from_name_or_id, new_item_name, endpoint=None, item_type='unknown', copy_lookup_data=None):

        if existing_item is not None:
            self.warn(f"A {item_type} with the name {new_item_name} already exists.")
            self.json_output['changed'] = False
            self.json_output['copied'] = False
            return existing_item

        # Lookup existing item to copy from
        copy_from_lookup = self.get_one(endpoint, name_or_id=copy_from_name_or_id, **{'data': copy_lookup_data})

        # Fail if the copy_from_lookup is empty
        if copy_from_lookup is None:
            self.fail_json(msg=f"A {item_type} with the name {copy_from_name_or_id} was not able to be found.")

        # Do checks for copy permissions if warranted
        if item_type == 'workflow_job_template':
            copy_get_check = self.get_endpoint(copy_from_lookup['related']['copy'])
            if copy_get_check['status_code'] in [200]:
                if (
                    copy_get_check['json']['can_copy']
                    and copy_get_check['json']['can_copy_without_user_input']
                    and not copy_get_check['json']['templates_unable_to_copy']
                    and not copy_get_check['json']['credentials_unable_to_copy']
                    and not copy_get_check['json']['inventories_unable_to_copy']
                ):
                    # Because checks have passed
                    self.json_output['copy_checks'] = 'passed'
                else:
                    self.fail_json(msg=f"Unable to copy {item_type} {copy_from_name_or_id} error: {copy_get_check}")
            else:
                self.fail_json(msg=f"Error accessing {item_type} {copy_from_name_or_id} error: {copy_get_check} ")

        response = self.post_endpoint(copy_from_lookup['related']['copy'], **{'data': {'name': new_item_name}})

        if response['status_code'] in [201]:
            self.json_output['id'] = response['json']['id']
            self.json_output['changed'] = True
            self.json_output['copied'] = True
            new_existing_item = response['json']
        else:
            if 'json' in response and '__all__' in response['json']:
                self.fail_json(msg=f"Unable to create {item_type} {new_item_name}: {response['json']['__all__'][0]}")
            elif 'json' in response:
                self.fail_json(msg=f"Unable to create {item_type} {new_item_name}: {response['json']}")
            else:
                self.fail_json(msg=f"Unable to create {item_type} {new_item_name}: {response['status_code']}")
        return new_existing_item

    def create_if_needed(self, existing_item, new_item, endpoint, on_create=None, auto_exit=True, item_type='unknown', associations=None):

        # This will exit from the module on its own
        # If the method successfully creates an item and on_create param is defined,
        #    the on_create parameter will be called as a method passing in this object and the json from the response
        # This will return one of two things:
        #    1. None if the existing_item is already defined (so no create needs to happen)
        #    2. The response from AWX from calling the patch on the endpont. It's up to you to process the response and exit from the module
        # Note: common error codes from the AWX API can cause the module to fail
        response = None
        if not endpoint:
            self.fail_json(msg=f"Unable to create new {item_type} due to missing endpoint")

        item_url = None
        if existing_item:
            try:
                item_url = existing_item['url']
            except KeyError as ke:
                self.fail_json(msg=f"Unable to process create of item due to missing data {ke}")
        else:
            # If we don't have an existing_item, we can try to create it

            # We have to rely on item_type being passed in since we don't have an existing item that declares its type
            # We will pull the item_name out from the new_item, if it exists
            item_name = self.get_item_name(new_item, allow_unknown=True)

            response = self.post_endpoint(endpoint, **{'data': new_item})

            # 200 is response from approval node creation on tower 3.7.3 or awx 15.0.0 or earlier.
            if response['status_code'] in [200, 201]:
                self.json_output['name'] = 'unknown'
                for key in ('name', 'username', 'identifier', 'hostname'):
                    if key in response['json']:
                        self.json_output['name'] = response['json'][key]
                self.json_output['id'] = response['json']['id']
                self.json_output['changed'] = True
                item_url = response['json']['url']
            else:
                if 'json' in response and '__all__' in response['json']:
                    self.fail_json(msg=f"Unable to create {item_type} {item_name}: {response['json']['__all__'][0]}")
                elif 'json' in response:
                    self.fail_json(msg=f"Unable to create {item_type} {item_name}: {response['json']}")
                else:
                    self.fail_json(msg=f"Unable to create {item_type} {item_name}: {response['status_code']}")

        # Process any associations with this item
        if associations is not None:
            for association_type in associations:
                sub_endpoint = f'{item_url}{association_type}/'
                self.modify_associations(sub_endpoint, associations[association_type])

        # If we have an on_create method and we actually changed something we can call on_create
        if on_create is not None and self.json_output['changed']:
            on_create(self, response['json'])
        elif auto_exit:
            self.exit_json(**self.json_output)
        else:
            if response is not None:
                last_data = response['json']
                return last_data
            else:
                return

    def _encrypted_changed_warning(self, field, old, warning=False):
        if not warning:
            return
        self.warn(
            f"The field {field} of {old.get('type', 'unknown')} {old.get('id', 'unknown')} has encrypted data and may inaccurately report task is changed."
        )

    @staticmethod
    def has_encrypted_values(obj):
        """Returns True if JSON-like python content in obj has $encrypted$
        anywhere in the data as a value
        """
        if isinstance(obj, dict):
            for val in obj.values():
                if ControllerAPIModule.has_encrypted_values(val):
                    return True
        elif isinstance(obj, list):
            for val in obj:
                if ControllerAPIModule.has_encrypted_values(val):
                    return True
        elif obj == ControllerAPIModule.ENCRYPTED_STRING:
            return True
        return False

    @staticmethod
    def fields_could_be_same(old_field, new_field):
        """Treating $encrypted$ as a wild card,
        return False if the two values are KNOWN to be different
        return True if the two values are the same, or could potentially be the same,
        depending on the unknown $encrypted$ value or sub-values
        """
        if isinstance(old_field, dict) and isinstance(new_field, dict):
            if set(old_field.keys()) != set(new_field.keys()):
                return False
            for key in new_field.keys():
                if not ControllerAPIModule.fields_could_be_same(old_field[key], new_field[key]):
                    return False
            return True  # all sub-fields are either equal or could be equal
        else:
            if old_field == ControllerAPIModule.ENCRYPTED_STRING:
                return True
            return bool(new_field == old_field)

    def objects_could_be_different(self, old, new, field_set=None, warning=False):
        if field_set is None:
            field_set = set(fd for fd in new.keys() if fd not in ('modified', 'related', 'summary_fields'))
        for field in field_set:
            new_field = new.get(field, None)
            old_field = old.get(field, None)
            if old_field != new_field:
                if self.update_secrets or (not self.fields_could_be_same(old_field, new_field)):
                    return True  # Something doesn't match, or something might not match
            elif self.has_encrypted_values(new_field) or field not in new:
                if self.update_secrets or (not self.fields_could_be_same(old_field, new_field)):
                    # case of 'field not in new' - user password write-only field that API will not display
                    self._encrypted_changed_warning(field, old, warning=warning)
                    return True
        return False

    def update_if_needed(self, existing_item, new_item, on_update=None, auto_exit=True, associations=None):
        # This will exit from the module on its own
        # If the method successfully updates an item and on_update param is defined,
        #   the on_update parameter will be called as a method passing in this object and the json from the response
        # This will return one of two things:
        #    1. None if the existing_item does not need to be updated
        #    2. The response from AWX from patching to the endpoint. It's up to you to process the response and exit from the module.
        # Note: common error codes from the AWX API can cause the module to fail
        response = None
        if existing_item:

            # If we have an item, we can see if it needs an update
            try:
                item_url = existing_item['url']
                item_type = existing_item['type']
                if item_type == 'user':
                    item_name = existing_item['username']
                elif item_type == 'workflow_job_template_node':
                    item_name = existing_item['identifier']
                elif item_type == 'credential_input_source':
                    item_name = existing_item['id']
                elif item_type == 'instance':
                    item_name = existing_item['hostname']
                else:
                    item_name = existing_item['name']
                item_id = existing_item['id']
            except KeyError as ke:
                self.fail_json(msg=f"Unable to process update of item due to missing data {ke}")

            # Check to see if anything within the item requires the item to be updated
            needs_patch = self.objects_could_be_different(existing_item, new_item)

            # If we decided the item needs to be updated, update it
            self.json_output['id'] = item_id
            if needs_patch:
                response = self.patch_endpoint(item_url, **{'data': new_item})
                if response['status_code'] == 200:
                    # compare apples-to-apples, old API data to new API data
                    # but do so considering the fields given in parameters
                    self.json_output['changed'] |= self.objects_could_be_different(existing_item, response['json'], field_set=new_item.keys(), warning=True)
                elif 'json' in response and '__all__' in response['json']:
                    self.fail_json(msg=response['json']['__all__'])
                else:
                    self.fail_json(**{'msg': f"Unable to update {item_type} {item_name}, see response", 'response': response})

        else:
            raise RuntimeError('update_if_needed called incorrectly without existing_item')

        # Process any associations with this item
        if associations is not None:
            for association_type, id_list in associations.items():
                endpoint = f'{item_url}{association_type}/'
                self.modify_associations(endpoint, id_list)

        # If we change something and have an on_change call it
        if on_update is not None and self.json_output['changed']:
            if response is None:
                last_data = existing_item
            else:
                last_data = response['json']
            on_update(self, last_data)
        elif auto_exit:
            self.exit_json(**self.json_output)
        else:
            if response is None:
                last_data = existing_item
            else:
                last_data = response['json']
            return last_data

    def create_or_update_if_needed(
        self, existing_item, new_item, endpoint=None, item_type='unknown', on_create=None, on_update=None, auto_exit=True, associations=None
    ):
        # Remove boolean values of certain specific types
        # this is needed so that boolean fields will not get a false value when not provided
        for key in list(new_item.keys()):
            if key in self.argument_spec:
                param_spec = self.argument_spec[key]
                if 'type' in param_spec and param_spec['type'] == 'bool':
                    if new_item[key] is None:
                        new_item.pop(key)

        if existing_item:
            return self.update_if_needed(existing_item, new_item, on_update=on_update, auto_exit=auto_exit, associations=associations)
        else:
            return self.create_if_needed(
                existing_item, new_item, endpoint, on_create=on_create, item_type=item_type, auto_exit=auto_exit, associations=associations
            )

    def update_survey_spec(self, survey_spec, survey_endpoint):
        if survey_spec == {}:
            response = self.delete_endpoint(survey_endpoint)
            if response['status_code'] != 200:
                self.fail_json(msg=f"Failed to delete survey: {response['json']}")
        else:
            response = self.post_endpoint(survey_endpoint, **{'data': survey_spec})
            if response['status_code'] != 200:
                self.fail_json(msg=f"Failed to update survey: {response['json']['error']}")

    def logout(self):
        if self.authenticated and self.oauth_token_id:
            # Attempt to delete our current token from /api/v2/tokens/
            # Post to the tokens endpoint with basic auth to try and get a token
            endpoint = self.url_prefix.rstrip('/') + f'/api/v2/tokens/{self.oauth_token_id}/'
            api_token_url = (self.url._replace(path=endpoint, query=None)).geturl()  # in error cases, fail_json exists before exception handling

            try:
                self.session.open(
                    'DELETE',
                    api_token_url,
                    validate_certs=self.verify_ssl,
                    timeout=self.request_timeout,
                    follow_redirects=True,
                    force_basic_auth=True,
                    url_username=self.username,
                    url_password=self.password,
                )
                self.oauth_token_id = None
                self.authenticated = False
            except HTTPError as he:
                try:
                    resp = he.read()
                except Exception as e:
                    resp = f'unknown {e}'
                self.warn(f'Failed to release token: {he}, response: {resp}')
            except Exception as e:
                # Sanity check: Did the server send back some kind of internal error?
                self.warn(f'Failed to release token {self.oauth_token_id}: {e}')

    def is_job_done(self, job_status):
        return job_status not in ['new', 'pending', 'waiting', 'running']

    def wait_on_url(self, url, object_name, object_type, timeout=30, interval=2):
        # Grab our start time to compare against for the timeout
        start = time.time()
        result = self.get_endpoint(url)
        wait_on_field = 'event_processing_finished'
        if wait_on_field not in result['json']:
            wait_on_field = 'finished'
        while not result['json'][wait_on_field]:
            # If we are past our time out fail with a message
            if timeout is not None and timeout < time.time() - start:
                # Account for Legacy messages
                if object_type == 'legacy_job_wait':
                    self.json_output['msg'] = f'Monitoring of Job - {object_name} aborted due to timeout'
                else:
                    self.json_output['msg'] = f'Monitoring of {object_type} - {object_name} aborted due to timeout'
                self.wait_output(result)
                self.fail_json(**self.json_output)

            # Put the process to sleep for our interval
            time.sleep(interval)

            result = self.get_endpoint(url)
            self.json_output['status'] = result['json']['status']

        # If the job has failed, we want to raise a task failure for that so we get a non-zero response.
        if result['json']['failed']:
            # Account for Legacy messages
            if object_type == 'legacy_job_wait':
                self.json_output['msg'] = f'Job with id {object_name} failed'
            else:
                self.json_output['msg'] = f'The {object_type} - {object_name}, failed'
                self.json_output["job_data"] = result["json"]
            self.wait_output(result)
            self.fail_json(**self.json_output)

        self.wait_output(result)

        return result

    def wait_output(self, response):
        for k in ('id', 'status', 'elapsed', 'started', 'finished'):
            self.json_output[k] = response['json'].get(k)

    def wait_on_workflow_node_url(self, url, object_name, object_type, timeout=30, interval=2, **kwargs):
        # Grab our start time to compare against for the timeout
        start = time.time()
        result = self.get_endpoint(url, **kwargs)

        while result["json"]["count"] == 0:
            # If we are past our time out fail with a message
            if timeout is not None and timeout < time.time() - start:
                # Account for Legacy messages
                self.json_output["msg"] = f"Monitoring of {object_type} - {object_name} aborted due to timeout, {url}"
                self.wait_output(result)
                self.fail_json(**self.json_output)

            # Put the process to sleep for our interval
            time.sleep(interval)
            result = self.get_endpoint(url, **kwargs)

        if object_type == "Workflow Approval":
            # Approval jobs have no elapsed time so return
            return result["json"]["results"][0]
        else:
            # Removed time so far from timeout.
            revised_timeout = timeout - (time.time() - start)
            # Now that Job has been found, wait for it to finish
            result = self.wait_on_url(
                url=result["json"]["results"][0]["related"]["job"],
                object_name=object_name,
                object_type=object_type,
                timeout=revised_timeout,
                interval=interval,
            )
        self.json_output["job_data"] = result["json"]
        return result
