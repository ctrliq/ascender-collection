# Ascender Ansible Collection

The `ctrliq.ascender` collection lets you manage an Ascender controller from Ansible playbooks: organizations, inventories, projects, job templates, credentials, schedules, workflows, and the rest of the controller API are all exposed as modules, alongside a dynamic inventory plugin and a set of lookup plugins.

This collection traces back to the modules that once shipped in Ansible core
under `lib/ansible/modules/web_infrastructure/ansible_tower`, plus the inventory
plugin, module utilities, and doc fragments that lived elsewhere in that repo.

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

- **44 modules** covering controller resources (organizations, teams,
  users, inventories, hosts, groups, projects, credentials, job/workflow
  templates, schedules, notifications, settings, tokens, and more), plus
  `export`/`import` for bulk configuration.
- **Inventory plugin:** `ctrliq.ascender.controller`.
- **Lookup plugins:** `controller_api`, `schedule_rrule`, and `schedule_rruleset`.

Per-plugin documentation is available with `ansible-doc`, e.g.
`ansible-doc ctrliq.ascender.job_launch`.

## Release and upgrade notes

Notable points in the history of the `ctrliq.ascender` collection:

- It descends from the `awx.awx` collection; every module previously named
  `tower_*` is now unprefixed (for example, `tower_inventory` is `inventory`).
- All modules support named URLs anywhere a name or id is accepted.
- The version in `galaxy.yml` is bumped with each release and follows a
  `YY.M.PATCH` calendar scheme (e.g. `25.4.0`).

Behaviours worth knowing when writing playbooks:

- `credential`: `kind` is no longer a parameter; supply the credential's fields
  under `inputs` (for example, `become_method`).
- `job_wait`: use `interval` instead of the removed `min_interval`/`max_interval`.
- `notification_template`: notification settings go in the
  `notification_configuration` dict; use a `lookup` to load one from a file.
- `inventory_source`: when `source_project` is given, it is looked up within the
  same organization as the inventory.
- `project`: creation waits for the initial sync by default; set `wait: false`
  to skip it.
- `extra_vars` is always a dict. Launching with `extra_vars` requires
  `ask_extra_vars` or `survey_enabled` to be enabled on the job template.
- `variables` on `group`, `host`, and `inventory` must be a dict; the `@file`
  syntax is no longer supported (use a `lookup`).
- `inputs`/`injectors` on `credential_type`, and `schema` on
  `workflow_job_template`, are structured data (dict / list of dicts), not
  strings.
- Config files must be INI, YAML, or JSON — single-line `k=v` content is no
  longer accepted.
- Removed: "scan" job templates, the `TOWER_CERTIFICATE` env var, the HipChat
  notification type, `extra_vars_path` on `job_template`, and passing a filename
  to `ssh_key_data` on `credential`.

## Testing

The collection is verified three ways:

- **Sanity** — from an installed copy of the collection:
  `ansible-test sanity`.
- **Unit** — compatibility tests against the current controller code live in
  `test/ascender` and require a checkout of the
  [Ascender](https://github.com/ctrliq/ascender) repo for the Django models.
  To run them, use a dedicated virtualenv:

  ```bash
  mkvirtualenv my_new_venv
  pip install -r requirements.txt
  pip install -e <path to your ascender checkout>
  pip install -e <path to your ascender checkout>/awxkit
  py.test test/ascender/
  ```

- **Integration** — require a virtualenv with `ansible-core >= 2.16` and
  `awxkit`, a running controller, and an installed collection
  plus a config file as described under
  [Authentication](#authentication):

  ```bash
  # ansible-test must run from where the collection is installed
  cd ~/.ansible/collections/ansible_collections/ctrliq/ascender/
  ansible-test integration
  ```

## Licensing

This collection is licensed under the **GNU General Public License v3.0 or
later**. See [COPYING](./COPYING) for the full text.
