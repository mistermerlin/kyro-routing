"""Decorators combined with @route."""

import pytest
from django.core.exceptions import ImproperlyConfigured

from tests import hidden_views


def test_function_route_hidden_by_a_decorator_is_rejected():
    """Serving the undecorated function would skip the decorator, a guard for instance."""
    with pytest.raises(ImproperlyConfigured, match="does not use functools.wraps"):
        hidden_views.function_router.urlpatterns()


def test_method_route_hidden_by_a_decorator_is_rejected():
    with pytest.raises(ImproperlyConfigured, match="does not use functools.wraps"):
        hidden_views.method_router.urlpatterns()


def test_route_above_a_decorator_without_wraps(mount, client):
    mount(hidden_views.outermost_router)
    assert client.get("/guarded").status_code == 403
