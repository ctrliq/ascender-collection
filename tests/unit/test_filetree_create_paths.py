"""filetree_create must keep every file it writes inside output_path.

Directory and file names are built from controller object names. The end-to-end tests run the
role against a fake controller_api lookup with organization and inventory names such as ``..``
and ``../../escape``, and check where the files land. The gate checks that every path a task
builds sends controller data through the ctrliq.ascender.path_component filter.

These tests do not need the ascender server, so run them with ``pytest --noconftest``.
"""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import jinja2
import jinja2.nodes
import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[2]
TASKS = ROOT / 'roles/filetree_create/tasks'
FILTER_SRC = ROOT / 'plugins/filter/path_component.py'

FAKE_LOOKUP = '''
import json, os
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        with open(os.environ['FAKE_API_DATA']) as f:
            value = json.load(f).get(terms[0], [])
        return value if isinstance(value, list) else [value]
'''

LONG = 'L' * 300
# 120 three-byte characters: 360 bytes in UTF-8, so the cut must land on a character boundary.
LONG_UTF8 = 'é✓' * 60 + 'x'


def _org(oid, name):
    rel = {k: '/o/%d/%s/' % (oid, k) for k in (
        'instance_groups', 'galaxy_credentials', 'notification_templates_error', 'notification_templates_started',
        'notification_templates_success', 'notification_templates_approvals', 'notification_templates_changed')}
    return {'id': oid, 'name': name, 'description': '', 'max_hosts': 0, 'summary_fields': {}, 'related': rel}


def _credential(cid, name, org):
    return {'id': cid, 'name': name, 'description': '', 'organization': 1, 'inputs': {'username': 'u'},
            'summary_fields': {'organization': {'name': org}, 'credential_type': {'name': 'Machine'}}}


def _label(lid, name, org):
    return {'id': lid, 'name': name, 'summary_fields': {'organization': {'name': org}}}


def _inventory(iid, name, org):
    return {'id': iid, 'name': name, 'description': '', 'kind': '', 'host_filter': None, 'variables': '',
            'total_inventory_sources': 0, 'has_inventory_sources': False, 'total_groups': 0,
            'prevent_instance_group_fallback': False,
            'summary_fields': {'organization': {'name': org}},
            'related': {'hosts': '/i/%d/hosts/' % iid, 'groups': '/i/%d/groups/' % iid,
                        'inventory_sources': '/i/%d/sources/' % iid, 'instance_groups': '/i/%d/ig/' % iid,
                        'input_inventories': '/i/%d/inputs/' % iid}}


def _host(name, inventory):
    return {'name': name, 'description': '', 'enabled': True, 'variables': '', 'instance_id': '',
            'has_inventory_sources': False, 'summary_fields': {'inventory': {'name': inventory}}}


def _ansible_playbook():
    exe = pathlib.Path(sys.executable).parent / 'ansible-playbook'
    return str(exe) if exe.exists() else shutil.which('ansible-playbook')


def _export(api, input_tag, extra_vars=None):
    """Run filetree_create against `api`. Returns (root dir, output_path, playbook log); root is removed at exit."""
    d = pathlib.Path(tempfile.mkdtemp())
    coll = d / 'collections/ansible_collections/ctrliq/ascender'
    (coll / 'plugins/lookup').mkdir(parents=True)
    (coll / 'meta').mkdir()
    shutil.copy(ROOT / 'galaxy.yml', coll / 'galaxy.yml')
    shutil.copy(ROOT / 'meta/runtime.yml', coll / 'meta/runtime.yml')
    shutil.copytree(ROOT / 'roles', coll / 'roles')
    if (ROOT / 'plugins/filter').is_dir():
        shutil.copytree(str(ROOT / 'plugins/filter'), str(coll / 'plugins/filter'))
    (coll / 'plugins/lookup/controller_api.py').write_text(FAKE_LOOKUP)
    (d / 'ansible.cfg').write_text('[defaults]\n')
    api = dict(api, ping={'version': '4.6.0'})
    (d / 'data.json').write_text(json.dumps(api))
    out = d / 'work/export'
    play_vars = {'output_path': str(out), 'input_tag': input_tag, 'controller_hostname': 'controller.example.com',
                 'controller_oauthtoken': 'x', 'controller_validate_certs': False, 'controller_dependency_check': False,
                 'template_overrides_resources': {}, 'template_overrides_global': {}}
    play_vars.update(extra_vars or {})
    play = [{'hosts': 'localhost', 'gather_facts': False, 'vars': play_vars,
             'roles': ['ctrliq.ascender.filetree_create']}]
    (d / 'play.yml').write_text(json.dumps(play))
    env = dict(os.environ, ANSIBLE_CONFIG=str(d / 'ansible.cfg'), ANSIBLE_COLLECTIONS_PATH=str(d / 'collections'),
               FAKE_API_DATA=str(d / 'data.json'), ANSIBLE_NOCOLOR='1',
               PATH=os.pathsep.join([str(pathlib.Path(sys.executable).parent), os.environ.get('PATH', '')]))
    proc = subprocess.run([_ansible_playbook(), '-i', 'localhost,', '-c', 'local', str(d / 'play.yml')],
                          cwd=str(d), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True, check=False)
    return d, out, proc


@pytest.fixture
def export():
    roots = []

    def run(*args, **kwargs):
        d, out, proc = _export(*args, **kwargs)
        roots.append(d)
        return out, proc
    yield run
    for d in roots:
        shutil.rmtree(str(d), ignore_errors=True)


def _outside(out):
    """Everything under out's parent other than out itself, plus anything above it in the temp root."""
    work = out.parent
    found = sorted(str(p.relative_to(work)) for p in work.rglob('*') if p != out and out not in p.parents)
    harness = ('work', 'collections', 'ansible.cfg', 'data.json', 'play.yml')
    found += sorted(p.name for p in work.parent.iterdir() if p.name not in harness)
    return found


def _files(out):
    return sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.is_file())


def test_dotdot_organization_stays_inside_output_path(export):
    api = {
        'api/v2/organizations/': [_org(1, '..')],
        'api/v2/credentials/': [_credential(5, 'deploy key', '..')],
        'api/v2/labels/': [_label(7, 'prod', '..')],
        'api/v2/inventories/': [_inventory(9, 'web', '..'), _inventory(10, '..', 'Default')],
        '/i/9/hosts/': [_host('web1', 'web')],
        '/i/10/hosts/': [_host('db1', '..')],
    }
    out, proc = export(api, ['organizations', 'credentials', 'labels', 'inventory'],
                       {'skip_inventory_sources': True})
    assert proc.returncode == 0, proc.stdout[-4000:]
    assert _outside(out) == [], proc.stdout[-4000:]
    assert _files(out) == [
        'Default/inventories/__/10___.yaml',
        'Default/inventories/__/current_hosts.yaml',
        '__/credentials/5_deploy key.yaml',
        '__/current_organization.yaml',
        '__/inventories/web/9_web.yaml',
        '__/inventories/web/current_hosts.yaml',
        '__/labels/7_prod.yaml',
    ]


def test_credentials_directory_uses_the_sanitized_organization(export):
    # The directory task used the raw name: "Eng/Ops" made Eng/Ops/credentials and the file
    # task then failed on the missing Eng_Ops/credentials, and "../../escape" made a directory
    # two levels above output_path.
    api = {'api/v2/credentials/': [_credential(5, 'deploy key', 'Eng/Ops'), _credential(6, 'other', '../../escape')]}
    out, proc = export(api, ['credentials'])
    assert proc.returncode == 0, proc.stdout[-4000:]
    assert _outside(out) == [], proc.stdout[-4000:]
    assert _files(out) == ['.._.._escape/credentials/6_other.yaml', 'Eng_Ops/credentials/5_deploy key.yaml']


def test_long_names_are_shortened_to_fit_the_filesystem(export):
    api = {'api/v2/organizations/': [_org(1, LONG)], 'api/v2/labels/': [_label(7, LONG_UTF8, LONG)]}
    out, proc = export(api, ['organizations', 'labels'])
    assert proc.returncode == 0, proc.stdout[-4000:]
    files = _files(out)
    assert len(files) == 2, files
    for f in files:
        for part in f.split('/'):
            assert len(part.encode('utf-8')) <= 255, part


def test_names_up_to_230_bytes_keep_their_main_layout(export):
    # Names that exported on main keep their paths up to 230 bytes; longer ones are shortened.
    org, label = 'O' * 220, 'l' * 220
    api = {'api/v2/organizations/': [_org(1, org), _org(2, 'P' * 240)],
           'api/v2/labels/': [_label(7, label, org), _label(8, 'm' * 240, org)]}
    out, proc = export(api, ['organizations', 'labels'])
    assert proc.returncode == 0, proc.stdout[-4000:]
    files = _files(out)
    assert '%s/current_organization.yaml' % org in files
    assert '%s/labels/7_%s.yaml' % (org, label) in files
    assert 'P' * 240 + '/current_organization.yaml' not in files
    assert '%s/labels/8_%s.yaml' % (org, 'm' * 240) not in files
    assert len(files) == 4, files


def test_normal_names_keep_their_directories(export):
    api = {'api/v2/organizations/': [_org(1, 'Default'), _org(2, 'Eng/Ops'), _org(3, '.hidden'), _org(4, '-dash')],
           'api/v2/labels/': [_label(7, 'a/b', 'Eng/Ops'), _label(8, 'x..y', 'Default')]}
    out, proc = export(api, ['organizations', 'labels'])
    assert proc.returncode == 0, proc.stdout[-4000:]
    assert _files(out) == ['-dash/current_organization.yaml', '.hidden/current_organization.yaml',
                           'Default/current_organization.yaml', 'Default/labels/8_x..y.yaml',
                           'Eng_Ops/current_organization.yaml', 'Eng_Ops/labels/7_a_b.yaml']


def _filter():
    spec = importlib.util.spec_from_file_location('path_component', str(FILTER_SRC))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FilterModule().filters()['path_component']


@pytest.mark.parametrize('name', ['Default', 'Eng Ops', 'Équipe – ops ✓', '.hidden', '-leading', 'x..y',
                                  '...', 'back\\slash', 'a' * 230], ids=lambda n: n if len(n) < 20 else 'len%d' % len(n))
def test_filter_keeps_names_that_are_already_safe(name):
    assert _filter()(name) == name


@pytest.mark.parametrize('name, expected', [('a/b', 'a_b'), ('/', '_'), ('../x', '.._x'), ('.', '_'), ('..', '__'),
                                            ('', '_'), ('nul\x00byte', 'nul_byte')])
def test_filter_rewrites_separators_and_dot_names(name, expected):
    assert _filter()(name) == expected


@pytest.mark.parametrize('name', [LONG, LONG_UTF8, 'a' * 231], ids=['ascii300', 'utf8', 'ascii231'])
def test_filter_shortens_long_names(name):
    f = _filter()
    out = f(name)
    assert len(out.encode('utf-8')) <= 230
    out.encode('utf-8').decode('utf-8')
    assert out == f(name) == f(out)
    assert out != f(name[:-1] + 'z')


def test_filter_limit_is_230_bytes():
    # 230 + the longest prefix and suffix the tasks add ("<19-digit id>_" and ".yaml") = 255.
    f = _filter()
    assert f('a' * 230) == 'a' * 230
    assert f('é' * 115) == 'é' * 115
    short = f('a' * 231)
    assert len(short.encode('utf-8')) == 230 and short.startswith('a' * 221 + '-')


def test_filter_output_is_always_one_component():
    f = _filter()
    for name in ['..', '.', '', '../..', '/..', '..' + '/' * 300, 'é' * 300, '.' * 400]:
        out = f(name)
        assert '/' not in out and out not in ('', '.', '..'), (name, out)


# Names that are not controller data: the role's own settings and the path variables it builds.
GATE_ALLOWED = {'output_path', 'omit_id', 'flatten_output', '__path', '__dest', 'groups_output_path',
                'hosts_output_path', 'inventory_sources_output_path'}
# Set from the object's numeric `.id` in the same task's vars.
GATE_ID_VARS = {'application_id', 'credentials_id', 'job_template_id', 'label_id', 'project_id', 'team_id',
                'workflow_job_template_id'}
GATE_MODULES = {'file', 'copy', 'template', 'stat', 'find', 'assemble', 'fetch', 'slurp', 'blockinfile', 'lineinfile'}
PATH_KEYS = ('path', 'dest', 'name', 'paths', 'src')
FILTER = 'ctrliq.ascender.path_component'


def _gate_names(node, inside=False):
    """Yield each problem in `node`: a Name outside a path_component filter, or a filter applied after it."""
    if isinstance(node, jinja2.nodes.Filter):
        if isinstance(node.node, jinja2.nodes.Filter) and node.node.name == FILTER:
            yield '%s after %s' % (node.name, FILTER)
        if node.name == FILTER:
            inside = True
    if isinstance(node, jinja2.nodes.Test):
        return
    if isinstance(node, jinja2.nodes.Getattr) and node.attr == 'id':
        return
    if isinstance(node, jinja2.nodes.Name) and not inside and node.name not in GATE_ALLOWED | GATE_ID_VARS:
        yield node.name
    for child in node.iter_child_nodes():
        yield from _gate_names(child, inside)


def _module_args(task):
    """Yield the argument dict of each file-writing or -reading module in `task`, FQCN or short name."""
    from ansible.parsing.splitter import parse_kv
    for key, args in task.items():
        if key.rsplit('.', 1)[-1] in GATE_MODULES and (key.count('.') == 0 or key.startswith(('ansible.builtin.', 'ansible.legacy.'))):
            yield parse_kv(args) if isinstance(args, str) else (args or {})


def _gate_tasks(tasks, inherited, where, offenders):
    for task in tasks or []:
        scope = dict(inherited, **(task.get('vars') or {}))
        for key in ('block', 'rescue', 'always'):
            if key in task:
                _gate_tasks(task[key], scope, where, offenders)
        strings = [v for k, v in scope.items() if k in ('__path', '__dest') or k.endswith('_output_path')]
        for args in _module_args(task):
            for k in PATH_KEYS:
                value = args.get(k) if isinstance(args, dict) else None
                strings += value if isinstance(value, list) else [value]
        for s in strings:
            if not isinstance(s, str):
                continue
            for name in _gate_names(jinja2.Environment().parse(s)):
                offenders.add('%s: %s in %r' % (where, name, s))


def test_every_path_sends_controller_data_through_path_component():
    offenders = set()
    for f in sorted(TASKS.glob('*.yml')):
        _gate_tasks(yaml.safe_load(f.read_text()), {}, f.name, offenders)
    assert sorted(offenders) == []


RAW = '{{ output_path }}/{{ org.name }}'
GATE_BYPASSES = {
    'short_module': [{'file': {'path': RAW}}],
    'set_fact_path': [{'ansible.builtin.set_fact': {'p': RAW}}, {'ansible.builtin.file': {'path': '{{ p }}'}}],
    'filter_after': [{'ansible.builtin.file': {'path': '{{ output_path }}/{{ org.name | %s | replace("_", "/") }}' % FILTER}}],
    'stat': [{'ansible.builtin.stat': {'path': RAW}}],
    'assemble': [{'ansible.builtin.assemble': {'dest': RAW, 'src': 'x'}}],
    'vars_dest': [{'ansible.builtin.template': {'src': 'x', 'dest': '{{ __dest }}'}, 'vars': {'__dest': '{{ output_path }}/{{ needed_path }}'}}],
    'id_suffix': [{'ansible.builtin.file': {'path': '{{ output_path }}/{{ org_name_id }}'}}],
    'free_form': [{'ansible.builtin.copy': 'dest=%s content=x' % RAW}],
    'name_alias': [{'ansible.builtin.file': {'name': RAW}}],
    'loop_item': [{'ansible.builtin.file': {'path': '{{ output_path }}/{{ item }}'}, 'loop': ['a']}],
    'operator_var': [{'ansible.builtin.file': {'path': '{{ output_path }}/{{ organization_filter }}'}}],
    'find_paths': [{'ansible.builtin.find': {'paths': [RAW]}}],
}


@pytest.mark.parametrize('case', sorted(GATE_BYPASSES))
def test_gate_rejects_unsanitized_paths(case):
    offenders = set()
    _gate_tasks(GATE_BYPASSES[case], {}, case, offenders)
    assert offenders


def test_gate_accepts_a_sanitized_path():
    offenders = set()
    _gate_tasks([{'file': {'path': '{{ output_path }}/{{ org.name | %s }}/{{ (label_id ~ "_") }}x' % FILTER}}], {}, 'ok', offenders)
    assert offenders == set()
