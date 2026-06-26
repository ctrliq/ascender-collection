"""Placeholder tests to verify the unit test infrastructure works."""


def test_infrastructure():
    """Verify that the test infrastructure is functional."""
    assert True


def test_collection_import():
    """Verify that the collection's module_utils can be imported."""
    import importlib

    spec = importlib.util.find_spec("plugins.module_utils.controller_api")
    # The module file should exist on disk even if we can't fully import it
    # without ansible-core wiring; finding the spec is sufficient.
    assert spec is not None, "plugins.module_utils.controller_api should be discoverable"
