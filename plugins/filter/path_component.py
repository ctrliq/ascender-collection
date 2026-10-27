# Copyright: Contributors to the Ascender project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = """
name: path_component
author: Ascender contributors
short_description: Turn a controller object name into a single file or directory name
description:
  - Used by the filetree_create tasks to build the output directory and file names from
    organization, inventory and other object names returned by the controller API.
  - C(/) and NUL are replaced with C(_), as filetree_create has always done for C(/).
  - A name that is empty, C(.) or C(..) has each character replaced with C(_)
    (C(_), C(_) and C(__)), so it cannot name the current or parent directory.
  - A name longer than 230 bytes in UTF-8 is cut to 221 bytes and given a C(-) and the first
    8 hex digits of the SHA-256 of the original name. With the longest prefix and suffix
    filetree_create adds (a 19-digit id, C(_) and C(.yaml)), every file name stays within the
    255-byte limit of common filesystems.
  - Any other name is returned unchanged.
  - Distinct names can map to the same result, as C(a/b) and C(a_b) already do. This also holds
    for C(..) and C(__), for C(.), an empty name and C(_), and for a name equal to another name's
    shortened form.
options:
  _input:
    description: The name to convert.
    type: str
    required: true
"""

EXAMPLES = """
- name: Create the organization directory
  ansible.builtin.file:
    path: "{{ output_path }}/{{ org.name | ctrliq.ascender.path_component }}"
    state: directory
    mode: "0755"
"""

RETURN = """
_value:
  description: A name with no path separator that is not C(.) or C(..).
  type: str
"""

import hashlib

from ansible.module_utils.common.text.converters import to_text

# 255-byte name limit minus the longest prefix and suffix the tasks add: "<19-digit id>_" + ".yaml".
MAX_BYTES = 230
_HASH_CHARS = 8


def path_component(value):
    name = to_text(value, errors='surrogate_or_strict')
    safe = name.replace('/', '_').replace('\x00', '_')
    if safe in ('', '.', '..'):
        return safe.replace('.', '_') or '_'
    encoded = safe.encode('utf-8', 'surrogatepass')
    if len(encoded) <= MAX_BYTES:
        return safe
    digest = hashlib.sha256(name.encode('utf-8', 'surrogatepass')).hexdigest()[:_HASH_CHARS]
    head = encoded[:MAX_BYTES - _HASH_CHARS - 1].decode('utf-8', 'ignore')
    return '%s-%s' % (head, digest)


class FilterModule(object):
    def filters(self):
        return {'path_component': path_component}
