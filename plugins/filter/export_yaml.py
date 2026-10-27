# Copyright: Contributors to the Ascender project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = """
name: export_yaml
author: Ascender contributors
short_description: Render controller data as one line of YAML that is loaded back literally
description:
  - Used by the filetree_create templates to write values returned by the controller API.
  - Every string, including mapping keys, is double-quoted and tagged C(!unsafe), so a value that
    contains a quote, a newline or Jinja syntax is loaded back by C(include_vars) as the same literal
    text and is never templated.
  - Booleans, numbers and null are written as native YAML and are not tagged.
  - Mappings and lists are written in flow style on a single line, so the result can follow C(key:)
    or C(- ) in a template without any indentation handling.
  - Readers that use plain C(yaml.safe_load) need a constructor for the C(!unsafe) tag.
options:
  _input:
    description: The value to render.
    type: raw
    required: true
"""

EXAMPLES = """
- name: "{{ team.name | ctrliq.ascender.export_yaml }}"
"""

RETURN = """
_value:
  description: YAML text.
  type: str
"""

import datetime
import types
from collections.abc import ItemsView, KeysView, Mapping, ValuesView

import jinja2
import yaml

from ansible.errors import AnsibleFilterError
from ansible.module_utils.common.text.converters import to_text


# Generators come from Jinja's map/select; dict views and range from ansible-core 2.16 templating.
_SEQUENCES = (list, tuple, set, frozenset, range, types.GeneratorType, KeysView, ValuesView, ItemsView)


class _ExportDumper(yaml.SafeDumper):
    pass


_STR_TAG = 'tag:yaml.org,2002:str'


def _represent_str(dumper, data):
    # ansible-core 2.19+ resolves an !unsafe scalar as if it were unquoted, so `!unsafe "1.0"` loads
    # as a float and `!unsafe ""` as null. Strings that would resolve to another type (empty, numbers,
    # booleans, null, timestamps) contain no Jinja delimiters, so they are written untagged.
    if dumper.resolve(yaml.ScalarNode, data, (True, False)) != _STR_TAG:
        return dumper.represent_scalar(_STR_TAG, data, style='"')
    return dumper.represent_scalar('!unsafe', data, style='"')


# str subclasses too: str() of ansible-core 2.16's AnsibleUnsafeText still returns AnsibleUnsafeText.
_ExportDumper.add_representer(str, _represent_str)
_ExportDumper.add_multi_representer(str, _represent_str)


def _plain(value):
    """Copy `value` into plain dict/list/str/int/float/bool/None.

    ansible-core hands filters subclasses of the builtin types (unsafe text, and on 2.19+ lazy
    and tagged containers and scalars); the dumper only knows the exact builtin types.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return _checked(str(value))
    if isinstance(value, bytes):
        return _checked(to_text(value, errors='surrogate_or_strict'))
    # ansible-core 2.16's vaulted string is not a str subclass; take its decrypted text.
    if type(value).__name__ == 'AnsibleVaultEncryptedUnicode':
        return _checked(to_text(value))
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return dict((_plain(k), _plain(v)) for k, v in value.items())
    if isinstance(value, _SEQUENCES):
        return [_plain(v) for v in value]
    # StrictUndefined raises its own "'x' is undefined" here; a lenient Undefined renders ''.
    if isinstance(value, jinja2.Undefined):
        return _checked(str(value))
    raise AnsibleFilterError('export_yaml cannot represent a value of type %s' % type(value).__name__)


def _checked(text):
    try:
        text.encode('utf-8')
    except UnicodeEncodeError:
        raise AnsibleFilterError('export_yaml cannot represent a string that is not valid UTF-8 (lone surrogate)')
    return text


def export_yaml(value):
    text = yaml.dump(_plain(value), Dumper=_ExportDumper, default_flow_style=True, width=float('inf'),
                     allow_unicode=True, sort_keys=False)
    # A document holding a single scalar ends with '...'; it carries no data.
    if text.endswith('\n...\n'):
        text = text[:-len('\n...\n')]
    text = text.rstrip('\n')
    if '\n' in text:
        raise AnsibleFilterError('export_yaml produced more than one line')
    return text


class FilterModule(object):
    def filters(self):
        return {'export_yaml': export_yaml}
