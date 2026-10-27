"""The controller inventory plugin must not template what it reads from the controller.

Host and group names and variables come from the controller API, where anyone who can edit an
inventory, host or group (or feed one through an inventory source) controls the text. The tests
serve such an inventory from a local fake controller, load it with ansible-playbook, and check
that Jinja in the data comes back as literal text instead of being evaluated on the node.

These tests do not need the ascender server, so run them with ``pytest --noconftest``.
"""
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

PAYLOAD = '{{ 7 * 7 }}'
HOST = 'web' + PAYLOAD
GROUP = 'grp' + PAYLOAD

INVENTORY = {
    'all': {'children': [GROUP], 'vars': {'all_var': PAYLOAD}},
    GROUP: {'hosts': [HOST], 'children': [], 'vars': {'group_var': PAYLOAD}},
    '_meta': {'hostvars': {HOST: {'host_var': PAYLOAD, 'nested': {'list': [PAYLOAD]}, 'plain': 'ok'}}},
}
CONFIG = {'version': PAYLOAD, 'ansible_version': '2.16.0', 'license_info': {'license_type': 'open'}}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/v2/inventories/1/script/':
            body = INVENTORY
        elif path == '/api/v2/config/':
            body = CONFIG
        else:
            self.send_error(404)
            return
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope='module')
def controller():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_address[1]}'
    server.shutdown()
    server.server_close()


def _ansible_playbook():
    exe = pathlib.Path(sys.executable).parent / 'ansible-playbook'
    return str(exe) if exe.exists() else shutil.which('ansible-playbook')


@pytest.fixture(scope='module')
def results(controller):
    """Run a playbook over the fake controller's inventory. Returns {check name: rendered value} for the host."""
    d = pathlib.Path(tempfile.mkdtemp())
    try:
        coll = d / 'collections/ansible_collections/ctrliq/ascender'
        coll.mkdir(parents=True)
        for name in ('galaxy.yml', 'meta', 'plugins'):
            src = ROOT / name
            (shutil.copytree if src.is_dir() else shutil.copy)(str(src), str(coll / name))
        (d / 'ansible.cfg').write_text('[defaults]\n')
        (d / 'inventory.controller.yml').write_text(json.dumps({
            'plugin': 'ctrliq.ascender.controller', 'host': controller, 'oauth_token': 'x',
            'verify_ssl': False, 'inventory_id': 1, 'include_metadata': True,
        }))
        checks = {
            'host_var': 'host_var',
            'nested': 'nested.list[0]',
            'group_var': 'group_var',
            'all_var': 'all_var',
            'metadata': 'controller_metadata.version',
            'hostname': 'inventory_hostname',
            'group_names': 'group_names | first',
            'plain': 'plain',
        }
        expr = '{{ {' + ', '.join(f'{k!r}: ({v})' for k, v in checks.items()) + '} | to_json }}'
        play = [{'hosts': 'all', 'gather_facts': False, 'connection': 'local',
                 'tasks': [{'ansible.builtin.copy': {'content': expr, 'dest': str(d / 'results.json'), 'mode': '0644'}}]}]
        (d / 'play.yml').write_text(json.dumps(play))
        env = dict(os.environ, ANSIBLE_CONFIG=str(d / 'ansible.cfg'), ANSIBLE_COLLECTIONS_PATH=str(d / 'collections'),
                   ANSIBLE_INVENTORY_ENABLED='ctrliq.ascender.controller', ANSIBLE_NOCOLOR='1',
                   ANSIBLE_INVENTORY_UNPARSED_FAILED='1',
                   PATH=os.pathsep.join([str(pathlib.Path(sys.executable).parent), os.environ.get('PATH', '')]))
        proc = subprocess.run([_ansible_playbook(), '-i', str(d / 'inventory.controller.yml'), str(d / 'play.yml')],
                              cwd=str(d), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True, check=False)
        assert proc.returncode == 0, proc.stdout
        return json.loads((d / 'results.json').read_text())
    finally:
        shutil.rmtree(str(d), ignore_errors=True)


@pytest.mark.parametrize('name', ['host_var', 'nested', 'group_var', 'all_var'])
def test_variables_stay_literal(results, name):
    assert results[name] == PAYLOAD


def test_metadata_stays_literal(results):
    assert results['metadata'] == PAYLOAD


def test_names_stay_literal(results):
    assert results['hostname'] == HOST
    assert results['group_names'] == GROUP


def test_plain_values_still_load(results):
    assert results['plain'] == 'ok'
