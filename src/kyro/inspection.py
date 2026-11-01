"""Inspect the routes of a URLconf: list them, and find the one serving a request.

kyro routes are described as declared; other routes as Django sees them.
"""

from __future__ import annotations

import contextlib
import inspect
import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlsplit

from django.urls import Resolver404, ResolverMatch, URLPattern, URLResolver, get_resolver
from django.urls.resolvers import RegexPattern

from kyro.router import Route
from kyro.syntax import describe_path

MATCH = "match"
METHOD_NOT_ALLOWED = "method not allowed"
SHADOWED = "shadowed"
NO_MATCH = "no match"

# Characters ending the literal start of a route (parameters, regex syntax).
_NOT_LITERAL = re.compile(r"[<>()\[\]{}*+?|\\^$.]")


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

    def accepts(self, method: str) -> bool:
        return not self.methods or method in self.methods

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


@dataclass(frozen=True)
class MatchResult:
    path: str
    method: str
    status: str
    """``MATCH``, ``METHOD_NOT_ALLOWED`` or ``NO_MATCH``."""
    route: RouteInfo | None
    """The route serving the request, if any."""
    kwargs: dict[str, Any]
    """Kwargs the view receives, before kyro's parameter conversion."""
    allowed: tuple[str, ...]
    """For ``METHOD_NOT_ALLOWED``: the methods the matching routes accept."""
    _routes: list[RouteInfo] = field(repr=False)
    _statuses: dict[int, str] = field(repr=False)
    """Status of the routes matching the path, by index; the others are ``NO_MATCH``."""

    @property
    def trace(self) -> list[tuple[RouteInfo, str]]:
        """Every route with its status for this request, in matching order."""
        return [(info, self._statuses.get(i, NO_MATCH)) for i, info in enumerate(self._routes)]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "method": self.method,
            "status": self.status,
            "route": self.route.as_dict() if self.route else None,
            "kwargs": self.kwargs,
            "allowed": list(self.allowed),
            "trace": [{"name": info.name, "status": status} for info, status in self.trace],
        }


@dataclass(frozen=True)
class _Entry:
    """One URL pattern of the URLconf, with what is needed to resolve it alone."""

    chain: tuple[URLResolver, ...]
    pattern: URLPattern
    info: int
    """Index of its route in the route list."""
    resolver: URLResolver
    """Resolves paths against this pattern only, through the same include() prefixes."""
    literal: str
    """Literal start of the pattern: paths not starting with it cannot match."""


class RouteTable:
    """The routes of a URLconf (default ``ROOT_URLCONF``), in matching order."""

    def __init__(self, urlconf: str | None = None) -> None:
        self.routes, self._entries = _collect(urlconf)

    def declarations(self) -> Iterator[tuple[RouteInfo, Route]]:
        """Each kyro route of the URLconf with its declaration."""
        seen: set[int] = set()
        for entry in self._entries:
            route = getattr(entry.pattern, "kyro_route", None)
            if route is not None and entry.info not in seen:
                seen.add(entry.info)
                yield self.routes[entry.info], route

    def match(self, path: str, method: str = "GET") -> MatchResult:
        """Find the route serving a ``method`` request to ``path`` (a path or a full URL)."""
        return self.match_methods(path, [method])[method.upper()]

    def match_methods(self, path: str, methods: Iterable[str]) -> dict[str, MatchResult]:
        """``match()`` for several methods, resolving the path only once."""
        path = urlsplit(path).path or "/"
        if not path.startswith("/"):
            path = "/" + path
        matches: list[tuple[_Entry, ResolverMatch]] = []
        for entry in self._entries:
            if not path.startswith(entry.literal):
                continue
            with contextlib.suppress(Resolver404):
                matches.append((entry, entry.resolver.resolve(path)))
        return {m.upper(): self._decide(path, m.upper(), matches) for m in methods}

    def _decide(
        self, path: str, method: str, matches: list[tuple[_Entry, ResolverMatch]]
    ) -> MatchResult:
        infos = self.routes
        chosen: tuple[_Entry, ResolverMatch] | None = None
        allowed: tuple[str, ...] = ()
        if matches:
            first = matches[0][0]
            group = getattr(first.pattern, "kyro_group", None)
            if group is None:
                # Django calls the first matching view.
                members = [matches[0]]
                candidate: tuple[_Entry, ResolverMatch] | None = matches[0]
            else:
                # kyro dispatches to the first route of the group accepting the method.
                members = [
                    match
                    for match in matches
                    if match[0].chain == first.chain
                    and getattr(match[0].pattern, "kyro_group", None) is group
                ]
                candidate = next(
                    (
                        match
                        for route in group
                        if not route.methods or method in route.methods
                        for match in members
                        if match[0].pattern.kyro_route is route  # type: ignore[attr-defined]
                    ),
                    None,
                )
            if candidate is not None and infos[candidate[0].info].accepts(method):
                chosen = candidate
            else:
                methods = {m for entry, _ in members for m in infos[entry.info].methods}
                allowed = tuple(sorted(methods))

        statuses: dict[int, str] = {}
        for entry, _ in reversed(matches):
            accepts = infos[entry.info].accepts(method)
            statuses[entry.info] = SHADOWED if accepts else METHOD_NOT_ALLOWED
        if chosen is not None:
            statuses[chosen[0].info] = MATCH

        if chosen is not None:
            status, route, kwargs = MATCH, infos[chosen[0].info], dict(chosen[1].kwargs)
        else:
            status = METHOD_NOT_ALLOWED if matches else NO_MATCH
            route, kwargs = None, {}
        return MatchResult(
            path=path,
            method=method,
            status=status,
            route=route,
            kwargs=kwargs,
            allowed=allowed,
            _routes=infos,
            _statuses=statuses,
        )


def collect_routes(urlconf: str | None = None) -> list[RouteInfo]:
    """The routes of ``urlconf`` (default ``ROOT_URLCONF``), in matching order."""
    return RouteTable(urlconf).routes


def match_route(path: str, method: str = "GET", urlconf: str | None = None) -> MatchResult:
    """Find the route serving a ``method`` request to ``path`` (a path or a full URL)."""
    return RouteTable(urlconf).match(path, method)


def _collect(urlconf: str | None) -> tuple[list[RouteInfo], list[_Entry]]:
    infos: list[RouteInfo] = []
    entries: list[_Entry] = []
    seen: dict[tuple[int, str, str | None], int] = {}
    for chain, prefix, namespace, pattern in _walk(get_resolver(urlconf).url_patterns):
        django_route = "/" + prefix + _clean(str(pattern.pattern))
        name = f"{namespace}:{pattern.name}" if namespace and pattern.name else pattern.name
        route: Route | None = getattr(pattern, "kyro_route", None)
        if route is None:
            entries.append(_entry(chain, pattern, len(infos), django_route))
            infos.append(
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
            index = seen[key]
            info = infos[index]
            infos[index] = replace(info, django_routes=(*info.django_routes, django_route))
            entries.append(_entry(chain, pattern, index, django_route))
            continue
        seen[key] = len(infos)
        entries.append(_entry(chain, pattern, len(infos), django_route))
        requirements, defaults = describe_path(route.path, route.requirements, route.defaults)
        infos.append(
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
    return infos, entries


def _walk(
    patterns: list[Any],
    chain: tuple[URLResolver, ...] = (),
    prefix: str = "",
    namespace: str | None = None,
) -> Iterator[tuple[tuple[URLResolver, ...], str, str | None, URLPattern]]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            ns = pattern.namespace
            inner = f"{namespace}:{ns}" if namespace and ns else ns or namespace
            yield from _walk(
                pattern.url_patterns,
                (*chain, pattern),
                prefix + _clean(str(pattern.pattern)),
                inner,
            )
        elif isinstance(pattern, URLPattern):
            yield chain, prefix, namespace, pattern


def _entry(
    chain: tuple[URLResolver, ...], pattern: URLPattern, info: int, django_route: str
) -> _Entry:
    node: list[Any] = [pattern]
    for resolver in reversed(chain):
        node = [
            URLResolver(
                resolver.pattern,
                node,
                resolver.default_kwargs,
                resolver.app_name,
                resolver.namespace,
            )
        ]
    literal = _NOT_LITERAL.split(django_route, maxsplit=1)[0]
    return _Entry(chain, pattern, info, URLResolver(RegexPattern(r"^/"), node), literal)


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
