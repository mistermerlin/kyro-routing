"""Routes hidden by a decorator that does not use functools.wraps.

Each router holds one problem, as the first one found stops the URL patterns build.
"""

from django.http import HttpResponse, HttpResponseForbidden

from kyro import Router

function_router = Router()
method_router = Router()
outermost_router = Router()


def deny_all(view):
    """A guard that does not use functools.wraps, like Django REST Framework's @api_view."""

    def guarded(request, *args, **kwargs):
        return HttpResponseForbidden()

    return guarded


@deny_all
@function_router.route("/guarded", name="guarded")
def guarded(request):
    return HttpResponse("secret")


class Controller:
    @deny_all
    @method_router.route("/guarded", name="guarded_method")
    def guarded(self, request):
        return HttpResponse("secret")


@outermost_router.route("/guarded", name="guarded_outermost")
@deny_all
def guarded_outermost(request):
    return HttpResponse("secret")
