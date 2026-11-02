"""Routed methods on a Django View subclass that has no class @route."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import HttpResponse
from django.views import View

from kyro import Router

router = Router()


class PrivateView(LoginRequiredMixin, View):
    @router.route("/private", name="private_index")
    def index(self, request):
        return HttpResponse("secret")
