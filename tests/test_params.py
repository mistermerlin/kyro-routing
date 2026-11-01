import enum
from datetime import date
from decimal import Decimal
from typing import Annotated
from uuid import UUID

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse

from kyro import MapModel, Router
from tests.testapp.models import Post


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class Level(enum.IntEnum):
    LOW = 1
    HIGH = 2


def typed(**values):
    return HttpResponse(" ".join(f"{k}={type(v).__name__}:{v}" for k, v in values.items()))


@pytest.fixture
def router():
    return Router()


@pytest.fixture
def post(db):
    return Post.objects.create(title="Hello", slug="hello")


@pytest.mark.parametrize(
    ("annotation", "value", "expected"),
    [
        (int, "12", "int:12"),
        (float, "1.5", "float:1.5"),
        (Decimal, "1.50", "Decimal:1.50"),
        (bool, "true", "bool:True"),
        (bool, "0", "bool:False"),
        (UUID, "12345678-1234-5678-1234-567812345678", "UUID:12345678-1234-5678-1234-567812345678"),
        (date, "2026-11-01", "date:2026-11-01"),
        (Color, "blue", "Color:Color.BLUE"),
        (Level, "2", "Level:2"),
        (str, "abc", "str:abc"),
    ],
)
def test_scalar_conversion(router, mount, client, annotation, value, expected):
    def view(request, value):
        return typed(value=value)

    view.__annotations__ = {"value": annotation}
    router.route("/v/{value}")(view)
    mount(router)
    assert client.get(f"/v/{value}").content.decode() == f"value={expected}"


@pytest.mark.parametrize(
    ("annotation", "value"),
    [
        (int, "abc"),
        (Decimal, "x"),
        (bool, "maybe"),
        (UUID, "nope"),
        (date, "2026-13-01"),
        (Color, "green"),
    ],
)
def test_invalid_scalar_is_a_404(router, mount, client, annotation, value):
    def view(request, value):
        return HttpResponse()

    view.__annotations__ = {"value": annotation}
    router.route("/v/{value}")(view)
    mount(router)
    assert client.get(f"/v/{value}").status_code == 404


def test_value_converted_by_django_is_kept(router, mount, client):
    @router.route("/v/<int:value>")
    def view(request, value: int):
        return typed(value=value)

    mount(router)
    assert client.get("/v/3").content == b"value=int:3"


def test_optional_default_is_converted(router, mount, client):
    @router.route("/list/{page?1}")
    def listing(request, page: int):
        return typed(page=page)

    mount(router)
    assert client.get("/list").content == b"page=int:1"
    assert client.get("/list/4").content == b"page=int:4"


def test_optional_without_default_is_none(router, mount, client):
    @router.route("/list/{page?}")
    def listing(request, page: int | None):
        return typed(page=page)

    mount(router)
    assert client.get("/list").content == b"page=NoneType:None"


def test_model_by_argument_name(router, mount, client, post):
    @router.route("/posts/{post}")
    def show(request, post: Post):
        return HttpResponse(post.title)

    mount(router)
    assert client.get(f"/posts/{post.pk}").content == b"Hello"
    assert client.get("/posts/999").status_code == 404
    assert client.get("/posts/abc").status_code == 404


def test_model_by_field(router, mount, client, post):
    @router.route("/posts/{slug}")
    def show(request, post: Post):
        return HttpResponse(post.title)

    mount(router)
    assert client.get("/posts/hello").content == b"Hello"
    assert client.get("/posts/other").status_code == 404


def test_field_is_passed_when_the_view_accepts_it(router, mount, client, post):
    @router.route("/posts/{slug}")
    def show(request, post: Post, slug: str):
        return HttpResponse(f"{post.title} {slug}")

    mount(router)
    assert client.get("/posts/hello").content == b"Hello hello"


def test_map_model(router, mount, client, post):
    @router.route("/posts/{post_slug}")
    def show(request, post: Annotated[Post, MapModel(slug="post_slug")]):
        return HttpResponse(post.title)

    mount(router)
    assert client.get("/posts/hello").content == b"Hello"


def test_optional_model(router, mount, client, post):
    @router.route("/posts/{post?}")
    def show(request, post: Post | None):
        return HttpResponse(post.title if post else "none")

    mount(router)
    assert client.get("/posts").content == b"none"
    assert client.get("/posts/999").content == b"none"
    assert client.get(f"/posts/{post.pk}").content == b"Hello"


def test_model_on_controller_method(router, mount, client, post):
    @router.route("/posts")
    class Controller:
        @router.route("/{slug}")
        def show(self, request, post: Post):
            return HttpResponse(post.title)

    mount(router)
    assert client.get("/posts/hello").content == b"Hello"


def test_model_in_async_view(router, mount, client, post):
    @router.route("/posts/{post}")
    async def show(request, post: Post):
        return HttpResponse(post.title)

    mount(router)
    assert client.get(f"/posts/{post.pk}").content == b"Hello"


def test_model_without_url_parameter_is_rejected(router):
    @router.route("/posts")
    def show(request, post: Post):
        return HttpResponse()

    with pytest.raises(ImproperlyConfigured, match="no URL parameter to look up 'post'"):
        router.urlpatterns()


def test_ambiguous_field_lookup_is_rejected(router):
    @router.route("/posts/{slug}")
    def show(request, first: Post, second: Post):
        return HttpResponse()

    with pytest.raises(ImproperlyConfigured, match="could look up both"):
        router.urlpatterns()


def test_map_model_with_unknown_parameter_is_rejected(router):
    @router.route("/posts/{slug}")
    def show(request, post: Annotated[Post, MapModel(slug="nope")]):
        return HttpResponse()

    with pytest.raises(ImproperlyConfigured, match="unknown URL parameter"):
        router.urlpatterns()
