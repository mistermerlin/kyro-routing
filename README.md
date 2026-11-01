# kyro

Symfony-style attribute routing for Django: declare routes with decorators directly on
your views and controllers instead of maintaining a long `urls.py`.

> Status: pre-alpha, under active development.

## Quick start

```python
# blog/views.py
from django.http import HttpResponse
from kyro import route

from blog.models import Post


@route("/hello/{name}", name="hello")
def hello(request, name):
    return HttpResponse(f"Hello {name}")


@route("/blog", name="blog_")
class BlogController:
    @route("", name="index", methods="GET")
    def index(self, request): ...

    @route("", name="create", methods="POST")
    def create(self, request): ...

    @route("/{slug}", name="show")
    def show(self, request, post: Post):  # fetched by slug, 404 if missing
        ...

    @route(r"/page/{page<\d+>?1}", name="list")
    def list(self, request, page: int): ...
```

```python
# project/urls.py
import kyro

urlpatterns = kyro.discover()  # imports the `views` module of every installed app
```

Routes are plain Django URL patterns: `reverse("blog_show", kwargs={"slug": "hello"})` and
`{% url "blog_index" %}` work as usual, and so do `include()` and namespaces.

## Paths

Both syntaxes are accepted, even in the same path:

| Syntax | Meaning |
|---|---|
| `<name>`, `<int:id>` | Django parameter and converter |
| `{name}` | parameter (anything but `/`) |
| `{id<\d+>}` | parameter with a regex requirement |
| `{page?1}` | optional parameter with default `"1"` |
| `{page?}` | optional parameter with default `None` |

Trailing parameters with a default (inline or in `defaults=`) are optional:
`/blog/{page?1}` matches `/blog` and `/blog/2`.

## `@route` arguments

| Argument | |
|---|---|
| `path` | the path, relative to the class prefix if any |
| `name` | route name, appended to the class `name` prefix; generated when omitted |
| `methods` | `"GET"` or `["GET", "POST"]`; others get a 405. `GET` also allows `HEAD` |
| `requirements` | `{"id": r"\d+"}` |
| `defaults` | defaults of optional parameters and extra kwargs passed to the view |
| `priority` | higher priority routes are matched first; otherwise declaration order |

Several routes may share a path with different `methods`: kyro dispatches each request to
the right view. `@route` can be stacked to give a view several routes.

## What can be routed

- Functions, sync or async. Put `@route` above or below other decorators.
- Methods of any class: the class is instantiated for each request. A `@route` on the class
  is a prefix (path, name, requirements, defaults, methods) for its methods. Classes defined
  inside a function must be decorated (`@route()` for no prefix).
- A class with `__call__` and no routed method, or a Django `View`: the class route is the
  route of the class itself.

## Parameter conversion

Annotated view arguments are converted from the URL:

- `int`, `float`, `Decimal`, `bool`, `UUID`, `date`, `datetime`, `Enum`: an invalid value
  is a 404.
- Django models, fetched like Symfony's entity resolver:
  - `{post}` for `post: Post`: lookup by primary key;
  - `{slug}` for `post: Post`: lookup by fields named like URL parameters (the parameter is
    only passed to the view if its signature accepts it);
  - `post: Annotated[Post, MapModel(slug="post_slug")]`: explicit mapping.

  A missing object is a 404, or `None` when the annotation is optional (`Post | None`).

## Settings

- `KYRO_DISCOVER` (default `["views"]`): app submodules imported by `kyro.discover()`.

`kyro.discover(["blog.views"])` imports the given modules and returns only their routes, to
mount them under a prefix: `path("blog/", include(kyro.discover(["blog.views"])))`.

## Development

```bash
uv sync              # create .venv and install dependencies
uv run pytest        # run the test suite
uv run ruff check .  # lint
uv run ruff format . # format
```
