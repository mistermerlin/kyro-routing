import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from kyro.inspection import collect_routes

URLCONF = "tests.urls_debug"


def run(*args):
    out = StringIO()
    call_command("debug_router", *args, "--urlconf", URLCONF, stdout=out, no_color=True)
    return out.getvalue()


@pytest.fixture
def routes():
    return {route.name: route for route in collect_routes(URLCONF)}


def test_kyro_route_under_a_namespaced_include(routes):
    route = routes["api:post_show"]
    assert route.path == "/api/posts/{post}"
    assert route.django_routes == ("/api/posts/<post>",)
    assert route.view == "tests.testapp.views.PostController.show"
    assert route.source.startswith("tests/testapp/views.py:")
    assert route.is_kyro


def test_route_with_optional_parameter_is_listed_once(routes):
    route = routes["api:archive"]
    assert route.path == r"/api/archive/{page<\d+>?1}"
    assert len(route.django_routes) == 2
    assert route.django_routes[1] == "/api/archive"
    assert route.requirements == {"page": r"\d+"}
    assert route.defaults == {"page": "1", "format": "html"}


def test_methods(routes):
    assert routes["api:post_index"].methods == ("GET", "HEAD")
    assert routes["api:post_create"].methods == ("POST",)
    assert routes["api:hello"].methods == ()
    assert routes["api:about"].methods == ("GET", "HEAD", "OPTIONS")


def test_django_routes_are_listed(routes):
    legacy = routes["legacy"]
    assert legacy.path == "/legacy/<int:id>/"
    assert legacy.view == "tests.urls_debug.legacy"
    assert not legacy.is_kyro
    assert routes[None].path == r"/old/(?P<slug>[-\w]+)/"


def test_list():
    output = run()
    assert "Name" in output and "Method" in output and "View" not in output
    assert "api:post_create" in output
    assert "POST" in output
    assert "/api/posts/{post}" in output
    assert "legacy" in output


def test_list_with_views():
    assert "tests.testapp.views.PostController.index" in run("--show-views")


def test_detail():
    output = run("api:archive")
    assert "Requirements    page: \\d+" in output
    assert "Defaults        page: 1, format: html" in output
    assert "Declared with   kyro" in output


def test_partial_name_lists_the_matches():
    output = run("post_")
    assert "api:post_index" in output and "api:post_show" in output
    assert "api:hello" not in output


def test_partial_name_with_one_match_shows_the_detail():
    assert "Defined in" in run("archiv")


def test_unknown_name():
    with pytest.raises(CommandError, match="No route matches 'nope'"):
        run("nope")


def test_json():
    data = json.loads(run("--format", "json"))
    assert {"name": "legacy", "kyro": False}.items() <= data[-2].items()
    detail = json.loads(run("api:archive", "--format", "json"))
    assert detail["priority"] == 0
    assert detail["methods"] == []


def test_runs_even_when_system_checks_fail():
    from kyro.management.commands.debug_router import Command

    assert Command.requires_system_checks == []


def test_default_urlconf():
    out = StringIO()
    call_command("debug_router", stdout=out)
    assert "/posts/{post}" in out.getvalue()
