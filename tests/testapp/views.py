import functools

from django.http import HttpResponse
from django.views import View

from kyro import route
from tests.testapp.models import Post


def add_header(view):
    @functools.wraps(view)
    def wrapper(request, *args, **kwargs):
        response = view(request, *args, **kwargs)
        response["X-Decorated"] = "yes"
        return response

    return wrapper


@route("/hello/{name}", name="hello")
def hello(request, name):
    return HttpResponse(f"hello {name}")


@add_header
@route("/decorated", name="decorated")
def decorated(request):
    return HttpResponse("decorated")


class ArticleController:
    """Not decorated itself: kyro finds it from its methods."""

    @route("/articles/{slug}", name="article_show", methods="GET")
    def show(self, request, post: Post):
        return HttpResponse(post.title)


@route("/posts", name="post_")
class PostController:
    @route("", name="index", methods=["GET"])
    def index(self, request):
        return HttpResponse("index")

    @route("", name="create", methods=["POST"])
    def create(self, request):
        return HttpResponse("created", status=201)

    @route("/{post}", name="show")
    def show(self, request, post: Post):
        return HttpResponse(post.title)


@route("/about", name="about")
class AboutView(View):
    def get(self, request):
        return HttpResponse("about")
