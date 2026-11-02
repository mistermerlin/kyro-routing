import pytest
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.urls import reverse
from django.views import View

from kyro import Router


@pytest.fixture
def router():
    return Router()


def test_function_route(router, mount, client):
    @router.route("/hello/{name}", name="hello")
    def hello(request, name):
        return HttpResponse(f"hello {name}")

    mount(router)
    assert client.get("/hello/world").content == b"hello world"
    assert reverse("hello", kwargs={"name": "bob"}) == "/hello/bob"


def test_generated_name(router, mount):
    @router.route("/hello")
    def hello(request):
        return HttpResponse()

    [pattern] = mount(router)
    assert pattern.name == "tests_test_routing_hello"


def test_class_prefix(router, mount, client):
    @router.route("/blog", name="blog_")
    class BlogController:
        @router.route("", name="index")
        def index(self, request):
            return HttpResponse("index")

        @router.route("/{slug}", name="show")
        def show(self, request, slug):
            return HttpResponse(slug)

        @router.route("/{slug}/edit")
        def edit(self, request, slug):
            return HttpResponse()

    mount(router)
    assert reverse("blog_index") == "/blog"
    assert reverse("blog_show", kwargs={"slug": "first"}) == "/blog/first"
    assert reverse("blog_edit", kwargs={"slug": "first"}) == "/blog/first/edit"
    assert client.get("/blog").content == b"index"
    assert client.get("/blog/first").content == b"first"


def test_class_prefix_requirements_defaults_and_methods(router, mount, client):
    @router.route("/{id}", requirements={"id": r"\d+"}, defaults={"source": "web"}, methods="POST")
    class Controller:
        @router.route("/save", name="save")
        def save(self, request, id, source):
            return HttpResponse(f"{id} {source}")

    mount(router)
    assert client.post("/12/save").content == b"12 web"
    assert client.post("/abc/save").status_code == 404
    assert client.get("/12/save").status_code == 405


def test_controller_is_instantiated_per_request(router, mount, client):
    @router.route()
    class Counter:
        def __init__(self):
            self.calls = 0

        @router.route("/count")
        def count(self, request):
            self.calls += 1
            return HttpResponse(str(self.calls))

    mount(router)
    assert client.get("/count").content == b"1"
    assert client.get("/count").content == b"1"


def test_method_of_undecorated_local_class_is_rejected(router):
    class Controller:
        @router.route("/x")
        def x(self, request):
            return HttpResponse()

    with pytest.raises(ImproperlyConfigured, match="decorate the class"):
        router.urlpatterns()


def test_invokable_class(router, mount, client):
    @router.route("/ping", name="ping")
    class Ping:
        def __call__(self, request):
            return HttpResponse("pong")

    mount(router)
    assert client.get(reverse("ping")).content == b"pong"


def test_django_class_based_view(router, mount, client):
    @router.route("/about", name="about")
    class About(View):
        def get(self, request):
            return HttpResponse("about")

    mount(router)
    assert client.get("/about").content == b"about"
    assert client.post("/about").status_code == 405


def test_methods_of_a_django_view_are_rejected(router):
    """kyro would call them without View.dispatch(): mixins and authentication skipped."""

    @router.route("/private", name="private_")
    class Private(LoginRequiredMixin, View):
        @router.route("", name="index")
        def index(self, request):
            return HttpResponse("secret")

    with pytest.raises(ImproperlyConfigured, match=r"View\.dispatch\(\)"):
        router.urlpatterns()


def test_methods_of_an_undecorated_django_view_are_rejected():
    from tests import view_methods

    with pytest.raises(ImproperlyConfigured, match=r"View\.dispatch\(\)"):
        view_methods.router.urlpatterns()


def test_class_without_routes_is_rejected(router):
    @router.route("/nothing")
    class Nothing:
        pass

    with pytest.raises(ImproperlyConfigured, match="no routed method"):
        router.urlpatterns()


def test_methods_are_enforced(router, mount, client):
    @router.route("/submit", methods=["post"])
    def submit(request):
        return HttpResponse("ok")

    mount(router)
    response = client.get("/submit")
    assert response.status_code == 405
    assert response["Allow"] == "POST"
    assert client.post("/submit").content == b"ok"


def test_get_allows_head(router, mount, client):
    @router.route("/page", methods="GET")
    def page(request):
        return HttpResponse("page")

    mount(router)
    assert client.head("/page").status_code == 200


def test_same_path_is_dispatched_by_method(router, mount, client):
    @router.route("/posts", name="post_list", methods="GET")
    def post_list(request):
        return HttpResponse("list")

    @router.route("/posts", name="post_create", methods="POST")
    def post_create(request):
        return HttpResponse("create", status=201)

    mount(router)
    assert reverse("post_list") == reverse("post_create") == "/posts"
    assert client.get("/posts").content == b"list"
    assert client.post("/posts").status_code == 201
    response = client.delete("/posts")
    assert response.status_code == 405
    assert response["Allow"] == "GET, HEAD, POST"


def test_dispatched_routes_keep_their_own_defaults(router, mount, client):
    @router.route("/feed", methods="GET", defaults={"format": "rss"})
    def read(request, format):
        return HttpResponse(format)

    @router.route("/feed", methods="POST")
    def write(request):
        return HttpResponse("written")

    mount(router)
    assert client.get("/feed").content == b"rss"
    assert client.post("/feed").content == b"written"


def test_declaration_order_wins_without_priority(router, mount, client):
    @router.route("/blog/{slug}")
    def show(request, slug):
        return HttpResponse("show")

    @router.route("/blog/new")
    def new(request):
        return HttpResponse("new")

    mount(router)
    assert client.get("/blog/new").content == b"show"


def test_priority(router, mount, client):
    @router.route("/blog/{slug}")
    def show(request, slug):
        return HttpResponse("show")

    @router.route("/blog/new", priority=1)
    def new(request):
        return HttpResponse("new")

    mount(router)
    assert client.get("/blog/new").content == b"new"
    assert client.get("/blog/other").content == b"show"


def test_defaults_are_passed_to_the_view(router, mount, client):
    @router.route("/feed", defaults={"format": "rss"})
    def feed(request, format):
        return HttpResponse(format)

    mount(router)
    assert client.get("/feed").content == b"rss"


def test_optional_parameter(router, mount, client):
    @router.route("/list/{page?1}", name="list")
    def listing(request, page):
        return HttpResponse(page)

    mount(router)
    assert client.get("/list").content == b"1"
    assert client.get("/list/3").content == b"3"
    assert reverse("list") == "/list"
    assert reverse("list", kwargs={"page": 3}) == "/list/3"


def test_inline_requirement(router, mount, client):
    @router.route(r"/item/{id<\d+>}", name="item")
    def item(request, id):
        return HttpResponse(id)

    mount(router)
    assert client.get("/item/12").content == b"12"
    assert client.get("/item/abc").status_code == 404
    assert reverse("item", kwargs={"id": 7}) == "/item/7"


def test_stacked_routes(router, mount, client):
    @router.route("/a", name="a")
    @router.route("/b", name="b")
    def view(request):
        return HttpResponse(request.path)

    @router.route("/c")
    @router.route("/d")
    def unnamed(request):
        return HttpResponse()

    patterns = mount(router)
    assert [(str(p.pattern), p.name) for p in patterns] == [
        ("a", "a"),
        ("b", "b"),
        ("c", "tests_test_routing_unnamed"),
        ("d", "tests_test_routing_unnamed_1"),
    ]
    assert client.get("/b").content == b"/b"


def test_duplicate_names_are_rejected(router):
    @router.route("/a", name="same")
    def a(request):
        return HttpResponse()

    @router.route("/b", name="same")
    def b(request):
        return HttpResponse()

    with pytest.raises(ImproperlyConfigured, match="'same' is used by both"):
        router.urlpatterns()


def test_async_views(router, mount, client):
    @router.route("/async/{name}")
    async def hello(request, name):
        return HttpResponse(f"async {name}")

    @router.route("/ctrl")
    class Controller:
        @router.route("/{n}", methods="GET")
        async def show(self, request, n: int):
            return HttpResponse(str(n * 2))

    mount(router)
    assert client.get("/async/kyro").content == b"async kyro"
    assert client.get("/ctrl/21").content == b"42"


def test_route_requires_a_path():
    router = Router()
    with pytest.raises(TypeError, match="parentheses"):

        @router.route
        def view(request):
            return HttpResponse()


def test_routers_are_independent(mount):
    first, second = Router(), Router()

    @first.route("/first")
    def a(request):
        return HttpResponse()

    assert second.urlpatterns() == []
    assert len(first.urlpatterns()) == 1
