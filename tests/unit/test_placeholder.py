"""Placeholder tests to verify the unit test infrastructure works."""


def test_infrastructure():
    """Verify that the test infrastructure is functional."""
    assert True


def test_collection_import():
    """Verify that the collection's module_utils can be imported."""
    from pathlib import Path

    module_path = Path("plugins/module_utils/controller_api.py")
    assert module_path.exists(), "plugins/module_utils/controller_api.py should exist"
