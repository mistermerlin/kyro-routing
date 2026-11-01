import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.http import HttpResponse

from kyro import Router
from kyro.inspection import MATCH, METHOD_NOT_ALLOWED, NO_MATCH, SHADOWED, match_route

URLCONF = "tests.urls_debug"


def match(path, method="GET"):
    return match_route(path, method, URLCONF)


def statuses(result):
    return {info.name: status for info, status in result.trace if status != NO_MATCH}


def run(*args, verbosity=1):
    out = StringIO()
    call_command(
        "router_match", *args, "--urlconf", URLCONF, stdout=out, no_color=True, verbosity=verbosity
    )
    return out.getvalue()


def test_route_chosen_by_method():
    result = match("/api/posts", "post")
    assert result.status == MATCH
    assert result.route.name == "api:post_create"
    assert statuses(result) == {"api:post_index": METHOD_NOT_ALLOWED, "api:post_create": MATCH}


def test_method_not_allowed():
    result = match("/api/posts", "DELETE")
    assert result.status == METHOD_NOT_ALLOWED
    assert result.route is None
    assert result.allowed == ("GET", "HEAD", "POST")


def test_class_based_view_methods():
    assert match("/api/about", "POST").status == METHOD_NOT_ALLOWED
    assert match("/api/about").route.name == "api:about"


def test_kwargs_include_defaults():
    assert match("/api/archive").kwargs == {"page": "1", "format": "html"}
    assert match("/api/archive/3").kwargs == {"page": "3", "format": "html"}


def test_requirements_are_applied():
    assert match("/api/archive/abc").status == NO_MATCH


def test_django_route():
    result = match("/legacy/5/")
    assert result.route.name == "legacy"
    assert result.kwargs == {"id": 5}


def test_no_match():
    result = match("/nope")
    assert result.status == NO_MATCH
    assert result.route is None


def test_full_url():
    assert match("http://example.com/api/hello/kyro?x=1").kwargs == {"name": "kyro"}


def test_shadowed_route(mount):
    router = Router()

    @router.route("/blog/{slug}", name="show")
    def show(request, slug):
        return HttpResponse()

    @router.route("/blog/new", name="new")
    def new(request):
        return HttpResponse()

    mount(router)
    result = match_route("/blog/new")
    assert result.route.name == "show"
    assert statuses(result) == {"show": MATCH, "new": SHADOWED}


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "DELETE"])
@pytest.mark.parametrize("path", ["/items", "/items/3", "/items/x", "/elsewhere"])
def test_agrees_with_real_requests(mount, client, path, method):
    router = Router()

    @router.route("/items", name="list", methods="GET")
    def items(request):
        return HttpResponse("list")

    @router.route("/items", name="create", methods="POST")
    def create(request):
        return HttpResponse("create")

    @router.route(r"/items/{id<\d+>}", name="show", methods=["GET", "PUT"])
    def show(request, id):
        return HttpResponse("show")

    mount(router)
    result = match_route(path, method)
    response = client.generic(method, path)
    expected = {MATCH: 200, METHOD_NOT_ALLOWED: 405, NO_MATCH: 404}[result.status]
    assert response.status_code == expected
    if result.status == MATCH and method != "HEAD":
        assert response.content.decode() == result.route.name


def test_command_match():
    output = run("/api/posts", "--method", "POST")
    assert "Route 'api:post_create' matches." in output
    assert "method not allowed" in output
    assert "View kwargs     -" in output


def test_command_shows_kwargs():
    assert "View kwargs     format: html, page: 1" in run("/api/archive")


def test_command_verbose_lists_every_route():
    assert "no match" not in run("/api/hello/x")
    assert "no match" in run("/api/hello/x", verbosity=2)


def test_command_no_match():
    with pytest.raises(CommandError, match="None of the routes match the path '/nope'"):
        run("/nope")


def test_command_method_not_allowed():
    with pytest.raises(CommandError, match=r"not the method DELETE \(allowed: GET, HEAD, POST\)"):
        run("/api/posts", "--method", "DELETE")


def test_command_json():
    data = json.loads(run("/api/archive", "--format", "json"))
    assert data["status"] == MATCH
    assert data["route"]["name"] == "api:archive"
    assert data["kwargs"] == {"page": "1", "format": "html"}


def test_command_json_without_match_fails_after_output():
    out = StringIO()
    with pytest.raises(CommandError):
        call_command("router_match", "/nope", "--format", "json", "--urlconf", URLCONF, stdout=out)
    assert json.loads(out.getvalue())["status"] == NO_MATCH
