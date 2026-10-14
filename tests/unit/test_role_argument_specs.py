from __future__ import absolute_import, division, print_function

__metaclass__ = type

# Checks each role's meta/argument_specs.yml against the role itself, without a controller:
# every documented option is read by the role, the role-scoped variables the tasks read are
# documented, and a documented default is the one the role actually applies.

import os
import re

import pytest

from ansible.module_utils.parsing.convert_bool import boolean
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

try:
    from ansible.template import trust_as_template
except ImportError:  # ansible-core < 2.19 templates any string
    def trust_as_template(value):
        return value

ROLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'roles')
ROLES = sorted(r for r in os.listdir(ROLES_DIR) if os.path.exists(os.path.join(ROLES_DIR, r, 'meta', 'argument_specs.yml')))

# Collection-wide variables every spec repeats, whether or not the role itself reads them.
SHARED = {
    'controller_state', 'controller_hostname', 'controller_validate_certs', 'controller_username',
    'controller_password', 'controller_oauthtoken', 'controller_configuration_secure_logging',
    'controller_configuration_async_retries', 'controller_configuration_async_delay',
}
GLOBAL_FALLBACKS = ('controller_configuration_async_retries', 'controller_configuration_async_delay')
# Role-scoped variable families the specs document.
SCOPED = re.compile(r'\b(?:controller_configuration_\w+?_(?:secure_logging|async_retries|async_delay)|filetree_controller_\w+)\b')
# Inputs the path defaults are built from.
RENDER_VARS = {'dir_orgs_vars': '/vars', 'orgs': 'Default', 'env': 'dev'}
# Documented as unset; the shipped literal default is being removed separately.
KNOWN_DEFAULT_DIFFERENCES = {('users', 'controller_user_default_password')}

loader = DataLoader()


def _options(role):
    spec = loader.load_from_file(os.path.join(ROLES_DIR, role, 'meta', 'argument_specs.yml'))
    return spec['argument_specs']['main']['options']


def _defaults(role):
    path = os.path.join(ROLES_DIR, role, 'defaults', 'main.yml')
    return (loader.load_from_file(path) or {}) if os.path.exists(path) else {}


def _consumers(role):
    """Text of everything that reads variables: tasks, handlers, templates, vars, meta/main.yml."""
    text = []
    for sub in ('tasks', 'handlers', 'templates', 'vars', 'meta'):
        for dirpath, dummy, filenames in os.walk(os.path.join(ROLES_DIR, role, sub)):
            for name in filenames:
                if name != 'argument_specs.yml':
                    with open(os.path.join(dirpath, name)) as f:
                        text.append(f.read())
    return '\n'.join(text)


def _render(value):
    templar = Templar(loader=loader, variables=RENDER_VARS)
    if isinstance(value, str):
        value = trust_as_template(value)
    return templar.template(value)


def _coerce(value, option):
    if option.get('type') == 'bool':
        return boolean(value, strict=False)
    if isinstance(value, str) and re.match(r'^\d+$', value):
        return int(value)
    return value


@pytest.mark.parametrize('role', ROLES)
def test_every_option_is_read(role):
    consumers = _consumers(role) + '\n' + repr(list(_defaults(role).values()))
    unread = [o for o in _options(role) if o not in SHARED and not re.search(r'\b%s\b' % re.escape(o), consumers)]
    assert not unread, 'roles/{0}/meta/argument_specs.yml documents variables the role never reads: {1}'.format(role, unread)


@pytest.mark.parametrize('role', ROLES)
def test_scoped_variables_are_documented(role):
    read = set(SCOPED.findall(_consumers(role))) - SHARED
    missing = sorted(read - set(_options(role)))
    assert not missing, 'roles/{0} reads variables its argument spec does not document: {1}'.format(role, missing)


@pytest.mark.parametrize('role', ROLES)
def test_documented_default_is_the_role_default(role):
    options, defaults = _options(role), _defaults(role)
    wrong = {}
    for name, value in defaults.items():
        if name in options and 'default' in options[name] and (role, name) not in KNOWN_DEFAULT_DIFFERENCES:
            documented, actual = _coerce(_render(options[name]['default']), options[name]), _coerce(_render(value), options[name])
            if documented != actual:
                wrong[name] = (documented, actual)
    assert not wrong, 'roles/{0}: documented default != defaults/main.yml (documented, actual): {1}'.format(role, wrong)


@pytest.mark.parametrize('role', ROLES)
def test_documented_global_default_is_the_role_fallback(role):
    # A role-scoped option such as "{{ controller_configuration_async_retries | default(50) }}" falls back to 50
    # when the global is unset, so that is the default the spec should give the global.
    options = _options(role)
    wrong = {}
    for name, option in options.items():
        match = re.match(r'^\{\{\s*(\w+)\s*\|\s*default\((\w+)\)\s*\}\}$', str(option.get('default', '')))
        if match and match.group(1) in GLOBAL_FALLBACKS and match.group(1) in options:
            documented = _coerce(str(options[match.group(1)].get('default')), {})
            if documented != _coerce(match.group(2), {}):
                wrong[match.group(1)] = (documented, name, match.group(2))
    assert not wrong, 'roles/{0}: global default != the fallback its role-scoped option uses: {1}'.format(role, wrong)
