## Collection tools

Tools used for building, maintaining, and testing the collection.

### Building

The standard way to build the collection is:

```bash
ansible-galaxy collection build
```

This reads the version from `galaxy.yml` and produces a
`ctrliq-ascender-<version>.tar.gz` artifact in the current directory.

### Template Galaxy (optional)

The `template_galaxy.yml` playbook copies the source into `build/` and
injects the version and namespace into the Python source code. This is
only needed when building a non-default namespace variant (e.g.
`ansible.controller`) or when you want `_COLLECTION_VERSION` in the
modules to reflect the release version instead of the `0.0.1-devel`
development placeholder:

```bash
ansible-playbook -i localhost, tools/template_galaxy.yml
ansible-galaxy collection build build/
```

The version defaults to whatever is in `galaxy.yml`. Override with
`-e collection_version=25.5.0`.

### Generate

This will template resource modules (like `group`, for groups in inventory) from a boilerplate template.
It is intended as a tool for writing new modules or enforcing consistency.

### Integration Testing

These instructions assume you have ansible-core and the collection installed.
To install the collection in-place (to pick up any local changes to source),
symlink the repo to the appropriate place under `~/.ansible/collections`:

```bash
mkdir -p ~/.ansible/collections/ansible_collections/ctrliq
ln -s $(pwd) ~/.ansible/collections/ansible_collections/ctrliq/ascender
```

This is a shortcut for quick validation of tests that bypasses `ansible-test`.
Configure authentication via environment variables:

```bash
export CONTROLLER_HOST=https://localhost:8043
export CONTROLLER_USERNAME=admin
export CONTROLLER_PASSWORD=password
export CONTROLLER_VERIFY_SSL=false
```

Or via a config file at `~/.controller_cli.cfg`:

```ini
[general]
host = https://localhost:8043
verify_ssl = false
username = admin
password = password
```

To run some sample modules:

```
ansible-playbook -i localhost, tools/integration_testing.yml
```

To run just one module (the most common use case), use the `-e test=<name>`.

```
ansible-playbook -i localhost, tools/integration_testing.yml -e test=host
```

If you want to run _all_ the tests, then you need to pass in the whole list.
This will take significant time and is not ideal from an error-handling perspective,
but this is a way to do it:

```
ansible-playbook -i localhost, tools/integration_testing.yml -e test=$(ls -1Am tests/integration/targets/ | tr -d '[:space:]')
```

Depending on the module, you may need special dependencies.
For instance, the rrule lookup plugins need `pytz`.
These will be satisfied if you install the requirements in `requirements.txt`.
