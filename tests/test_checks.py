import pytest
from django.core import checks
from django.http import HttpResponse
from django.urls import include, path

import kyro
from kyro import Router
from kyro.checks import check_routes


def view(request, **kwargs):
    return HttpResponse()


@pytest.fixture
def router():
    return Router()


@pytest.fixture(autouse=True)
def isolated_default_router(monkeypatch, router):
    """Keep W003 about the routes of each test, not those of the whole test suite."""
    monkeypatch.setattr("kyro.checks.default_router", router)


def ids(messages):
    return [message.id for message in messages]


def test_project_without_issues(monkeypatch):
    monkeypatch.setattr("kyro.checks.default_router", kyro.default_router)
    assert check_routes() == []


def test_shadowed_route(router, mount):
    router.route("/blog/{slug}", name="show")(view)

    @router.route("/blog/new", name="new")
    def new(request):
        return HttpResponse()

    mount(router)
    [message] = check_routes()
    assert message.id == "kyro.W001"
    assert message.msg == "Route 'new' is never reached: /blog/new is served by 'show'."
    assert message.obj.startswith("tests/test_checks.py:")


def test_priority_fixes_the_shadowing(router, mount):
    router.route("/blog/{slug}", name="show")(view)

    @router.route("/blog/new", name="new", priority=1)
    def new(request):
        return HttpResponse()

    mount(router)
    assert check_routes() == []


def test_partly_shadowed_route(router, mount):
    router.route("/blog/{slug}", name="show", methods="GET")(view)

    @router.route("/blog/new", name="new", methods=["GET", "POST"])
    def new(request):
        return HttpResponse()

    mount(router)
    [message] = check_routes()
    assert message.msg == "Route 'new' is not reached for GET: /blog/new is served by 'show'."


def test_routes_dispatched_by_method_are_not_shadowed(router, mount):
    router.route("/posts", name="list", methods="GET")(view)

    @router.route("/posts", name="create", methods="POST")
    def create(request):
        return HttpResponse()

    mount(router)
    assert check_routes() == []


def test_requirements_prevent_shadowing(router, mount):
    router.route(r"/items/{id<\d+>}", name="show")(view)

    @router.route("/items/new", name="new")
    def new(request):
        return HttpResponse()

    mount(router)
    assert check_routes() == []


def test_optional_parameter_shadows_a_static_route(router, mount):
    router.route("/blog/{page?1}", name="list")(view)

    @router.route("/blog", name="index")
    def index(request):
        return HttpResponse()

    mount(router)
    assert [m.msg for m in check_routes()] == [
        "Route 'index' is never reached: /blog is served by 'list'."
    ]


def test_route_shadowed_by_a_django_route(router, urlconf):
    @router.route("/about", name="about")
    def about(request):
        return HttpResponse()

    urlconf(
        [path("api/<slug:page>", view, name="page"), path("api/", include(router.urlpatterns()))]
    )
    [message] = check_routes()
    assert message.msg == "Route 'about' is never reached: /api/about is served by 'page'."
    # A Django route on another path does not shadow it.
    urlconf([path("about", view, name="page"), path("api/", include(router.urlpatterns()))])
    assert check_routes() == []


def test_shared_name(router, urlconf):
    router.route("/home", name="home")(view)
    urlconf([path("index", view, name="home"), *router.urlpatterns()])
    [message] = check_routes()
    assert message.id == "kyro.W002"
    assert message.msg == "Route name 'home' is used by 2 routes: /index, /home."


def test_shared_name_between_django_routes_only_is_ignored(urlconf):
    urlconf([path("a", view, name="same"), path("b", view, name="same")])
    assert check_routes() == []


def test_unmounted_routes(router, urlconf):
    router.route("/a", name="a")(view)

    @router.route("/b", name="b")
    def b(request):
        return HttpResponse()

    urlconf([path("", include(router.urlpatterns(["tests.nowhere"])))])
    [message] = check_routes()
    assert message.id == "kyro.W003"
    assert message.msg == "2 route(s) declared with @route are not in the URLconf: a, b."


def test_unmounted_routes_list_is_truncated(router, urlconf):
    for index in range(7):
        router.route(f"/{index}", name=f"r{index}")(lambda request: HttpResponse())
    urlconf([])
    [message] = check_routes()
    assert message.msg.endswith(": r0, r1, r2, r3, r4 and 2 more.")


def test_ignored_default(router, mount):
    router.route("/{page?1}/list", name="list")(view)
    mount(router)
    [message] = check_routes()
    assert message.id == "kyro.W004"
    assert "parameter 'page' has a default" in message.msg


def test_registered_with_the_check_framework(router, mount):
    router.route("/{page?1}/list", name="list")(view)
    mount(router)
    assert "kyro.W004" in ids(checks.run_checks(tags=[checks.Tags.urls]))
