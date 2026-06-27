# Ascender Ansible Collection

[![CI](https://github.com/ctrliq/ascender-collection/actions/workflows/ci.yml/badge.svg)](https://github.com/ctrliq/ascender-collection/actions/workflows/ci.yml)
[![Ansible Galaxy](https://img.shields.io/badge/galaxy-ctrliq.ascender-blue.svg)](https://galaxy.ansible.com/ui/repo/published/ctrliq/ascender/)
[![Ansible-core](https://img.shields.io/badge/ansible--core-%3E%3D2.16-blue.svg)](https://docs.ansible.com/ansible/latest/)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](https://www.python.org/)

The `ctrliq.ascender` collection lets you manage an [Ascender](https://ascender-automation.org) controller from Ansible playbooks: organizations, inventories, projects, job templates, credentials, schedules, workflows, and the rest of the controller API are all exposed as modules, alongside a dynamic inventory plugin and a set of lookup plugins.

## Requirements

- `ansible-core` >= 2.16
- Python 3.10+ on the controller node running the modules
- [awxkit](https://pypi.org/project/awxkit/) — only required by a handful of
  modules (notably `export` and `import`). The `DOCUMENTATION` block of each
  module states whether it needs awxkit; the rest have no extra Python
  dependencies.

## Installation

### From Galaxy

```bash
ansible-galaxy collection install ctrliq.ascender
```

### From source

Build the collection from a checkout of this repository:

```bash
ansible-galaxy collection build
ansible-galaxy collection install ctrliq-ascender-*.tar.gz
```

## Using the collection

Reference modules, the inventory plugin, and lookups by their fully qualified
collection name, `ctrliq.ascender.<name>`:

```yaml
- name: Create a project and launch a job
  hosts: localhost
  gather_facts: false
  tasks:
    - name: Add a project
      ctrliq.ascender.project:
        name: My Project
        organization: Default
        scm_type: git
        scm_url: https://github.com/ansible/test-playbooks.git

    - name: Launch a job template
      ctrliq.ascender.job_launch:
        job_template: My Job Template
      register: job

    - name: Wait for it to finish
      ctrliq.ascender.job_wait:
        job_id: "{{ job.id }}"
```

To use the dynamic inventory plugin, add a `*.controller.yml` (or
`*.controller.yaml`) inventory source:

```yaml
plugin: ctrliq.ascender.controller
host: https://controller.example.com
```

## Authentication

Every module accepts the same connection options. You can authenticate with
either:

- host, username, and password, or
- host and an OAuth2 token (preferred).

Connection settings are resolved from highest to lowest precedence:

1. Direct module parameters (`controller_host`, `controller_username`,
   `controller_password`, `controller_oauthtoken`, `controller_verify_ssl`).
2. Environment variables (`CONTROLLER_HOST`, `CONTROLLER_USERNAME`,
   `CONTROLLER_PASSWORD`, `CONTROLLER_OAUTH_TOKEN`, `CONTROLLER_VERIFY_SSL`) —
   most convenient when targeting `localhost`.
3. A config file passed via the `controller_config_file` parameter.

The config file may be written as INI, YAML, or JSON. INI form:

```ini
[general]
host = https://localhost:8043
verify_ssl = true
oauth_token = LEdCpKVKc4znzffcpQL5vLG8oyeku6
```

## Included content

- **45 modules** covering controller resources (organizations, inventories, credentials, etc.).
- **39 roles** for declarative controller configuration.
- **5 playbooks** for common configuration workflows.
- **Inventory plugin:** `ctrliq.ascender.controller`.
- **Lookup plugins:** `controller_api`, `schedule_rrule`, `schedule_rruleset`.

Per-plugin documentation is available with `ansible-doc`, e.g.
`ansible-doc ctrliq.ascender.job_launch`.

## Testing

See [TESTING.md](./TESTING.md) for full details.

- **Sanity** — `ansible-test sanity` from an installed copy.
- **Unit** — `py.test test/ascender/` against the
  [Ascender](https://github.com/ctrliq/ascender) Django models.
- **Integration** — `ansible-test integration` with a running controller.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md). Report bugs via
[GitHub Issues](https://github.com/ctrliq/ascender-collection/issues).
Release notes are in the [changelog](./changelogs/changelog.yaml).

## Licensing

This collection is licensed under the **GNU General Public License v3.0 or
later**. See [COPYING](./COPYING) for the full text.
