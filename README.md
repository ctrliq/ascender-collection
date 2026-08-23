# Ascender Ansible Collection

[![CI](https://github.com/ctrliq/ascender-collection/actions/workflows/ci.yml/badge.svg)](https://github.com/ctrliq/ascender-collection/actions/workflows/ci.yml)
[![Ansible Galaxy](https://img.shields.io/badge/galaxy-ctrliq.ascender-blue.svg)](https://galaxy.ansible.com/ui/repo/published/ctrliq/ascender/)
[![Ansible-core](https://img.shields.io/badge/ansible--core-%3E%3D2.16-blue.svg)](https://docs.ansible.com/ansible/latest/)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue.svg)](https://www.python.org/)

The `ctrliq.ascender` collection lets you manage an [Ascender](https://ascender-automation.org) controller from Ansible playbooks. Organizations, inventories, projects, job templates, credentials, schedules, workflows, and the rest of the controller API are exposed as modules, alongside a dynamic inventory plugin and a set of lookup plugins.

## Requirements

- `ansible-core` 2.16 or newer
- Python 3.10 or newer on the controller node running the modules
- [ascender-kit](https://pypi.org/project/ascender-kit/), for a few modules only
  - Needed by `export` and `import`, and it requires Python 3.11 or newer
  - Each module's `DOCUMENTATION` block states whether it needs ascender-kit
  - Every other module has no extra Python dependencies

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

Reference modules, the inventory plugin, and lookups by their fully qualified collection name, `ctrliq.ascender.<name>`:

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

To use the dynamic inventory plugin, add a `*.controller.yml` or `*.controller.yaml` inventory source:

```yaml
plugin: ctrliq.ascender.controller
host: https://controller.example.com
```

## Authentication

Every module accepts the same connection options: host with username and password, or host with an OAuth2 token, which is preferred.

Connection settings resolve from highest to lowest precedence:

| Precedence | Source | Values |
| ---------- | ------ | ------ |
| 1 | Module parameters | `controller_host`, `controller_username`, `controller_password` |
| 2 | Environment variables | `CONTROLLER_HOST`, `CONTROLLER_USERNAME`, `CONTROLLER_PASSWORD` |
| 3 | Config file | Passed via the `controller_config_file` parameter |

Modules also accept `controller_oauthtoken` and `controller_verify_ssl`, with the matching `CONTROLLER_OAUTH_TOKEN` and `CONTROLLER_VERIFY_SSL` variables. Environment variables are the most convenient form when targeting `localhost`.

The config file may be written as INI, YAML, or JSON. INI form:

```ini
[general]
host = https://localhost:8043
verify_ssl = true
oauth_token = LEdCpKVKc4znzffcpQL5vLG8oyeku6
```

## Included content

- **45 modules** covering controller resources such as organizations and credentials
- **39 roles** for declarative controller configuration
- **5 playbooks** for common configuration workflows
- **Inventory plugin**: `ctrliq.ascender.controller`
- **4 lookup plugins**:
  - `controller_api` and `controller_object_diff`
  - `schedule_rrule` and `schedule_rruleset`

Per-plugin documentation is available with `ansible-doc`, for example `ansible-doc ctrliq.ascender.job_launch`.

## Testing

See [TESTING.md](./docs/TESTING.md) for full details.

- **Sanity**: `ansible-test sanity` from an installed copy
- **Unit**: `py.test tests/unit/` against the Ascender Django models
- **Integration**: `ansible-test integration` with a running controller

## The Ascender ecosystem

| Repository | Description |
| ---------- | ----------- |
| [ascender](https://github.com/ctrliq/ascender) | The platform itself: web UI, REST API, and task engine |
| [ascender-install](https://github.com/ctrliq/ascender-install) | Installer for Ascender and Ledger, with Galaxy Proxy support |
| [ascender-k8s-install](https://github.com/ctrliq/ascender-k8s-install) | Kubernetes installer for Ascender, Ledger, and React |
| [ascender-pro-install](https://github.com/ctrliq/ascender-pro-install) | Enhanced installer adding Reaqt, Registry, and Galaxy Proxy |
| [ascender-operator](https://github.com/ctrliq/ascender-operator) | Kubernetes operator that deploys and manages Ascender |
| [ascender-ee](https://github.com/ctrliq/ascender-ee) | Default execution environment image for Ascender jobs |
| [ascender-kit](https://github.com/ctrliq/ascender-kit) | The `ascender` command line client and Python API library |
| [ascender-collection](https://github.com/ctrliq/ascender-collection) | The `ctrliq.ascender` Ansible collection for a controller |
| [ascender-ledger](https://github.com/ctrliq/ascender-ledger) | Reporting tool for host facts and playbook changes |
| [ascender-galaxy-proxy](https://github.com/ctrliq/ascender-galaxy-proxy) | Caching proxy for Ansible Galaxy collection downloads |
| [ascender-playbooks](https://github.com/ctrliq/ascender-playbooks) | Example playbooks for use with Ascender |
## Contributing

- See [CONTRIBUTING.md](./CONTRIBUTING.md) for development setup, testing, and pull requests.
- Report bugs and feature ideas via [GitHub Issues](https://github.com/ctrliq/ascender-collection/issues).
- For security vulnerabilities, follow [SECURITY.md](./SECURITY.md) rather than opening an issue.
- Release notes are in the [changelog](./changelogs/changelog.yaml).
- Join the [Ascender forum](https://forum.ascender-automation.org) to discuss development topics.

## License

Licensed under the **GNU General Public License v3.0 or later**. See [COPYING](./COPYING) for the full text.
