from django.http import HttpResponse
from django.urls import include, path, re_path

import kyro


def legacy(request, **kwargs):
    return HttpResponse()


urlpatterns = [
    path("api/", include((kyro.discover(["tests.testapp"]), "api"), namespace="api")),
    path("legacy/<int:id>/", legacy, name="legacy"),
    re_path(r"^old/(?P<slug>[-\w]+)/$", legacy),
]
