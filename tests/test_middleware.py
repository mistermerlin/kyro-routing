"""How Django middleware treats the views kyro builds."""

import django
import pytest
from django.http import HttpResponse
from django.test import Client
from django.views.decorators.csrf import csrf_exempt

from kyro import Router


@pytest.fixture
def router():
    return Router()


@pytest.fixture
def csrf_client():
    return Client(enforce_csrf_checks=True)


def test_csrf_exempt_view(router, mount, csrf_client):
    @router.route("/one", methods="POST")
    @csrf_exempt
    def one(request):
        return HttpResponse(status=201)

    mount(router)
    assert csrf_client.post("/one").status_code == 201


def test_csrf_exempt_views_sharing_a_path(router, mount, csrf_client):
    @router.route("/items", name="items_index", methods="GET")
    @csrf_exempt
    def index(request):
        return HttpResponse()

    @router.route("/items", name="items_create", methods="POST")
    @csrf_exempt
    def create(request):
        return HttpResponse(status=201)

    mount(router)
    assert csrf_client.post("/items").status_code == 201
    assert csrf_client.put("/items").status_code == 405


@pytest.mark.skipif(django.VERSION < (5, 0), reason="csrf_exempt supports async views since 5.0")
def test_async_csrf_exempt_views_sharing_a_path(router, mount, csrf_client):
    @router.route("/items", name="items_index", methods="GET")
    @csrf_exempt
    async def index(request):
        return HttpResponse()

    @router.route("/items", name="items_create", methods="POST")
    @csrf_exempt
    async def create(request):
        return HttpResponse(status=201)

    mount(router)
    assert csrf_client.post("/items").status_code == 201


def test_csrf_is_checked_when_one_view_of_the_path_is_not_exempt(router, mount, csrf_client):
    """A path is never less protected than its most protected view."""

    @router.route("/items", name="items_index", methods="GET")
    @csrf_exempt
    def index(request):
        return HttpResponse()

    @router.route("/items", name="items_create", methods="POST")
    def create(request):
        return HttpResponse(status=201)

    mount(router)
    assert csrf_client.post("/items").status_code == 403


def test_csrf_exempt_views_sharing_a_path_with_conversion(router, mount, csrf_client):
    @router.route("/items/{id}", name="item_show", methods="GET")
    @csrf_exempt
    def show(request, id: int):
        return HttpResponse()

    @router.route("/items/{id}", name="item_delete", methods="DELETE")
    @csrf_exempt
    def delete(request, id: int):
        return HttpResponse(status=204)

    mount(router)
    assert csrf_client.delete("/items/1").status_code == 204


@pytest.mark.skipif(django.VERSION < (5, 1), reason="LoginRequiredMiddleware is Django 5.1+")
def test_login_not_required_views_sharing_a_path(router, mount, client, settings):
    from django.contrib.auth.decorators import login_not_required

    settings.MIDDLEWARE = [
        *settings.MIDDLEWARE,
        "django.contrib.auth.middleware.LoginRequiredMiddleware",
    ]
    settings.LOGIN_URL = "/login"

    @router.route("/public", name="public_index", methods="GET")
    @login_not_required
    def index(request):
        return HttpResponse()

    @router.route("/public", name="public_create", methods="POST")
    @login_not_required
    def create(request):
        return HttpResponse(status=201)

    @router.route("/private", name="private_index", methods="GET")
    @login_not_required
    def private_index(request):
        return HttpResponse()

    @router.route("/private", name="private_create", methods="POST")
    def private_create(request):
        return HttpResponse(status=201)

    mount(router)
    assert client.get("/public").status_code == 200
    assert client.post("/public").status_code == 201
    assert client.get("/private").status_code == 302
