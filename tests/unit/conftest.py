"""Shared fixtures for unit tests."""

import pytest


@pytest.fixture
def dummy_module_params():
    """Return a minimal set of module parameters for testing."""
    return {
        "controller_host": "https://ascender.example.com",
        "controller_username": "admin",
        "controller_password": "password",
        "validate_certs": False,
    }
