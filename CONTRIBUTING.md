# Contributing to the Ascender Ansible Collection

Thanks for your interest in contributing to `ctrliq.ascender`. This document
covers the development setup, testing, and PR guidelines.

## Development setup

1. Fork and clone the repository:

   ```bash
   git clone https://github.com/<your-user>/ascender-collection.git
   cd ascender-collection
   ```

2. Install development dependencies:

   ```bash
   pip install ansible-core ruff yamllint ansible-lint antsibull-changelog
   ```

3. For unit tests, you also need a checkout of the
   [Ascender](https://github.com/ctrliq/ascender) main repo (the tests
   import Django models from `awx.main`):

   ```bash
   pip install -r requirements.txt
   pip install -e <path-to-ascender>
   pip install -e <path-to-ascender>/awxkit
   ```

4. Symlink the collection for `ansible-test`:

   ```bash
   mkdir -p ~/.ansible/collections/ansible_collections/ctrliq
   ln -s $(pwd) ~/.ansible/collections/ansible_collections/ctrliq/ascender
   ```

## Running tests

### Sanity tests

```bash
cd ~/.ansible/collections/ansible_collections/ctrliq/ascender
ansible-test sanity --docker
```

### Unit tests

```bash
DJANGO_SETTINGS_MODULE=awx.main.tests.settings_for_test \
  py.test test/ascender/ -v --timeout=120 --nomigrations --create-db
```

### Linting

```bash
ruff check plugins/
yamllint -d relaxed meta/ galaxy.yml
ansible-lint
```

## Making changes

### Branching

Create a feature branch from `main`:

```bash
git checkout -b my-feature main
```

### Code style

- Follow PEP 8 with a 200-character line limit (matching the existing codebase).
- Every module must have complete `DOCUMENTATION`, `EXAMPLES`, and `RETURN`
  blocks. Run `ansible-test sanity --test validate-modules` to check.
- Use the `ControllerAPIModule` base class from `plugins/module_utils/controller_api.py`
  for new modules.

### Changelog fragments

Every PR that changes user-facing behavior needs a changelog fragment in
`changelogs/fragments/`. Create a YAML file named after your change:

```bash
# changelogs/fragments/my-feature-description.yml
minor_changes:
  - module_name - short description of what changed.
```

Available categories:

| Category | When to use |
|---|---|
| `breaking_changes` | Backwards-incompatible changes |
| `major_changes` | Large new features |
| `minor_changes` | Small improvements, new options |
| `bugfixes` | Bug fixes |
| `deprecated_features` | Features marked for future removal |
| `removed_features` | Previously deprecated features now removed |

The description should start with the module or plugin name, followed by a
dash and a short sentence. See existing fragments in `changelogs/fragments/`
for examples.

### Commit messages

Write clear, concise commit messages:

```
Short summary (under 72 characters)

Longer description of what changed and why, if needed.
```

### Module documentation

Every module parameter and return value must be documented. The `DOCUMENTATION`
block uses standard Ansible format:

```python
DOCUMENTATION = r"""
---
module: my_module
short_description: Manage a resource on the controller
description:
  - Create, update, or delete a resource.
options:
  name:
    description: Name of the resource.
    required: true
    type: str
extends_documentation_fragment: ctrliq.ascender.auth
"""
```

## Submitting a PR

1. Make sure all tests pass locally (at minimum, sanity + lint).
2. Include a changelog fragment if the change is user-facing.
3. One logical change per PR — don't bundle unrelated fixes.
4. Target the `main` branch.
5. Fill in the PR template (summary, issue type, component, version).

CI runs automatically on every PR: sanity tests across ansible-core
2.16–devel, collection build + Galaxy import validation, linting, and
changelog format checks.

## Reporting issues

Open an issue at
[github.com/ctrliq/ascender-collection/issues](https://github.com/ctrliq/ascender-collection/issues).
Include the collection version (`ansible-galaxy collection list ctrliq.ascender`),
ansible-core version, and a minimal playbook that reproduces the problem.
