import pytest
from django.urls import reverse

import kyro


def test_discovered_function(client):
    assert client.get("/hello/kyro").content == b"hello kyro"


def test_decorators_above_route_are_kept(client):
    response = client.get(reverse("decorated"))
    assert response.content == b"decorated"
    assert response["X-Decorated"] == "yes"


@pytest.mark.django_db
def test_undecorated_controller(client):
    from tests.testapp.models import Post

    Post.objects.create(title="Hello", slug="hello")
    assert reverse("article_show", kwargs={"slug": "hello"}) == "/articles/hello"
    assert client.get("/articles/hello").content == b"Hello"
    assert client.post("/articles/hello").status_code == 405


@pytest.mark.django_db
def test_decorated_controller(client):
    from tests.testapp.models import Post

    post = Post.objects.create(title="Hello", slug="hello")
    assert client.get(reverse("post_index")).content == b"index"
    assert client.post(reverse("post_create")).status_code == 201
    assert client.get(reverse("post_show", kwargs={"post": post.pk})).content == b"Hello"


def test_django_view(client):
    assert client.get(reverse("about")).content == b"about"


def test_discover_filters_by_module():
    names = {pattern.name for pattern in kyro.discover(["tests.testapp"])}
    assert {"hello", "decorated", "article_show", "post_index", "about"} <= names
    assert kyro.discover(["django.contrib.auth.views"]) == []
