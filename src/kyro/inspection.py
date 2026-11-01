"""List the routes of a URLconf: kyro routes with their declaration, others as Django sees them."""

from __future__ import annotations

import inspect
import os
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from typing import Any

from django.urls import URLPattern, URLResolver, get_resolver

from kyro.router import Route
from kyro.syntax import describe_path


@dataclass(frozen=True)
class RouteInfo:
    name: str | None
    """Full name, namespaces included."""
    path: str
    """Path as declared (kyro syntax for kyro routes), include() prefixes included."""
    methods: tuple[str, ...]
    """Accepted HTTP methods; empty means any."""
    view: str
    django_routes: tuple[str, ...]
    """The Django URL patterns serving the route (several for optional parameters)."""
    requirements: dict[str, str] = field(default_factory=dict)
    defaults: dict[str, Any] = field(default_factory=dict)
    priority: int | None = None
    """``None`` for routes not declared with kyro."""
    source: str | None = None
    """``file:line`` of the declaration, when known."""

    @property
    def is_kyro(self) -> bool:
        return self.priority is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "methods": list(self.methods),
            "view": self.view,
            "django_routes": list(self.django_routes),
            "requirements": self.requirements,
            "defaults": self.defaults,
            "priority": self.priority,
            "source": self.source,
            "kyro": self.is_kyro,
        }


def collect_routes(urlconf: str | None = None) -> list[RouteInfo]:
    """The routes of ``urlconf`` (default ``ROOT_URLCONF``), in matching order."""
    routes: list[RouteInfo] = []
    seen: dict[tuple[int, str, str | None], int] = {}
    for prefix, namespace, pattern in _walk(get_resolver(urlconf).url_patterns):
        django_route = "/" + prefix + _clean(str(pattern.pattern))
        name = f"{namespace}:{pattern.name}" if namespace and pattern.name else pattern.name
        route: Route | None = getattr(pattern, "kyro_route", None)
        if route is None:
            routes.append(
                RouteInfo(
                    name=name,
                    path=django_route,
                    methods=_view_methods(pattern.callback),
                    view=_qualified(pattern.callback),
                    django_routes=(django_route,),
                    defaults=dict(pattern.default_args),
                    source=_source(pattern.callback),
                )
            )
            continue
        # The patterns of one route (optional parameters) are shown as one route.
        key = (id(route), prefix, namespace)
        if key in seen:
            info = routes[seen[key]]
            routes[seen[key]] = replace(info, django_routes=(*info.django_routes, django_route))
            continue
        seen[key] = len(routes)
        requirements, defaults = describe_path(route.path, route.requirements, route.defaults)
        routes.append(
            RouteInfo(
                name=name,
                path="/" + prefix + route.path.removeprefix("/"),
                methods=tuple(sorted(route.methods)) or _view_methods(route.view),
                view=_qualified(route.source),
                django_routes=(django_route,),
                requirements=requirements,
                defaults=defaults,
                priority=route.priority,
                source=_source(route.source),
            )
        )
    return routes


def _walk(
    patterns: list[Any], prefix: str = "", namespace: str | None = None
) -> Iterator[tuple[str, str | None, URLPattern]]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            ns = pattern.namespace
            inner = f"{namespace}:{ns}" if namespace and ns else ns or namespace
            yield from _walk(pattern.url_patterns, prefix + _clean(str(pattern.pattern)), inner)
        elif isinstance(pattern, URLPattern):
            yield prefix, namespace, pattern


def _clean(pattern: str) -> str:
    """Drop the anchors of regex patterns, which only add noise once concatenated."""
    pattern = pattern.removeprefix("^")
    for anchor in ("\\Z", "$"):
        pattern = pattern.removesuffix(anchor)
    return pattern


def _view_methods(view: Any) -> tuple[str, ...]:
    """The methods a class-based view implements; empty (any) for other views."""
    view_class = getattr(view, "view_class", None)
    if view_class is None:
        return ()
    methods = {m.upper() for m in view_class.http_method_names if hasattr(view_class, m)}
    if "GET" in methods:
        methods.add("HEAD")
    return tuple(sorted(methods))


def _qualified(obj: Any) -> str:
    obj = getattr(obj, "view_class", None) or inspect.unwrap(obj)
    module = getattr(obj, "__module__", None)
    qualname = getattr(obj, "__qualname__", None)
    if module is None or qualname is None:
        return repr(obj)
    return f"{module}.{qualname}"


def _source(obj: Any) -> str | None:
    obj = getattr(obj, "view_class", None) or inspect.unwrap(obj)
    try:
        filename = inspect.getsourcefile(obj)
        _, line = inspect.getsourcelines(obj)
    except (TypeError, OSError):
        return None
    if filename is None:
        return None
    relative = os.path.relpath(filename)
    if not relative.startswith(".."):
        filename = relative
    return f"{filename}:{line}"
