from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from unittest import mock

from ascender.main.models import User


@pytest.fixture
def mock_auth_stuff():
    """Some really specific session-related stuff is done for changing or setting
    passwords, so we will just avoid that here.

    ctrliq/ascender 9b678968e1 split awx/api/serializers.py into a package, and its
    __init__ re-exports the serializer classes rather than every name the module held.
    update_session_auth_hash is not one of them, so it is reachable only in the module
    that calls it, which is the name UserSerializer._update_password binds anyway.
    """
    with mock.patch('awx.api.serializers.user.update_session_auth_hash'):
        yield


@pytest.mark.django_db
def test_create_user(run_module, admin_user, mock_auth_stuff):
    result = run_module('user', dict(username='Bob', password='pass4word'), admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    assert result.get('changed'), result

    user = User.objects.get(id=result['id'])
    assert user.username == 'Bob'


@pytest.mark.django_db
def test_password_no_op_warning(run_module, admin_user, mock_auth_stuff, silence_warning):
    for i in range(2):
        result = run_module('user', dict(username='Bob', password='pass4word'), admin_user)
        assert not result.get('failed', False), result.get('msg', result)

    assert result.get('changed')  # not actually desired, but assert for sanity

    silence_warning.assert_called_once_with(
        "The field password of user {0} has encrypted data and " "may inaccurately report task is changed.".format(result['id'])
    )


@pytest.mark.django_db
def test_update_password_on_create(run_module, admin_user, mock_auth_stuff):
    for i in range(2):
        result = run_module('user', dict(username='Bob', password='pass4word', update_secrets=False), admin_user)
        assert not result.get('failed', False), result.get('msg', result)

    assert not result.get('changed')


@pytest.mark.django_db
def test_update_user(run_module, admin_user, mock_auth_stuff):
    result = run_module('user', dict(username='Bob', password='pass4word', is_system_auditor=True), admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    assert result.get('changed'), result

    update_result = run_module('user', dict(username='Bob', is_system_auditor=False), admin_user)

    assert update_result.get('changed')
    user = User.objects.get(id=result['id'])
    assert not user.is_system_auditor


@pytest.mark.django_db
def test_set_preferred_theme(run_module, admin_user, mock_auth_stuff):
    """The theme is stored on the profile rather than the user row, so a value
    that reaches the API still has to be read back through the relation.
    """
    result = run_module('user', dict(username='Bob', password='pass4word', preferred_theme='dark'), admin_user)
    assert not result.get('failed', False), result.get('msg', result)
    assert result.get('changed'), result

    user = User.objects.get(id=result['id'])
    assert user.profile.theme == 'dark'


@pytest.mark.django_db
def test_update_preferred_theme(run_module, admin_user, mock_auth_stuff):
    """An empty string is a value here and not an absence, so it has to clear the
    preference rather than leave the previous theme in place.
    """
    result = run_module('user', dict(username='Bob', password='pass4word', preferred_theme='light'), admin_user)
    assert not result.get('failed', False), result.get('msg', result)

    update_result = run_module('user', dict(username='Bob', preferred_theme=''), admin_user)
    assert not update_result.get('failed', False), update_result.get('msg', update_result)
    assert update_result.get('changed'), update_result

    user = User.objects.get(id=result['id'])
    assert user.profile.theme == ''
