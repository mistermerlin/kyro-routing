"""Route declaration (``@route``) and conversion of the declared routes into URL patterns."""

from __future__ import annotations

import inspect
import re
import sys
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, TypeVar

from asgiref.sync import iscoroutinefunction
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern
from django.urls import path as django_path
from django.utils.module_loading import autodiscover_modules, module_has_submodule
from django.views import View

from kyro.dispatch import Handler, make_view
from kyro.params import with_conversion
from kyro.syntax import compile_path

ROUTES_ATTR = "__kyro_routes__"
CLASS_ROUTE_ATTR = "__kyro_route__"

T = TypeVar("T")


@dataclass(frozen=True)
class RouteSpec:
    """The arguments of one ``@route(...)``."""

    path: str = ""
    name: str | None = None
    methods: frozenset[str] = frozenset()
    requirements: Mapping[str, str] = field(default_factory=dict)
    defaults: Mapping[str, Any] = field(default_factory=dict)
    priority: int | None = None


class RouteSet:
    """Routes declared on a function.

    Stored as an attribute of the function, so ``functools.wraps`` shares it with wrappers.
    """

    __slots__ = ("entries", "owner", "attr")

    def __init__(self) -> None:
        self.entries: list[tuple[Router, RouteSpec]] = []
        self.owner: type | None = None
        self.attr: str | None = None


@dataclass
class Route:
    """A declared route, once merged with its class prefix.

    Each URL pattern built by kyro carries its route as ``pattern.kyro_route``.
    """

    path: str
    name: str
    methods: frozenset[str]
    requirements: Mapping[str, str]
    defaults: Mapping[str, Any]
    priority: int
    module: str
    view: Callable[..., Any]
    signature: Callable[..., Any] | None
    """Callable whose signature drives parameter conversion; ``None`` disables it."""
    source: Any
    """What ``@route`` was declared on: function, method or class."""


class Router:
    """A registry of routes. ``kyro.route`` and ``kyro.discover`` use the default one."""

    def __init__(self) -> None:
        self._targets: list[Any] = []

    def route(
        self,
        path: str = "",
        *,
        name: str | None = None,
        methods: str | Iterable[str] | None = None,
        requirements: Mapping[str, str] | None = None,
        defaults: Mapping[str, Any] | None = None,
        priority: int | None = None,
    ) -> Callable[[T], T]:
        """Declare a route on a function, a method or a class.

        On a class, the route is a prefix (path, name, requirements, defaults, methods) for
        its routed methods; on a Django ``View`` or a class defining ``__call__``, it is the
        route of the class itself.
        """
        if not isinstance(path, str):
            raise TypeError("@route needs parentheses and a path, e.g. @route('/blog').")
        spec = RouteSpec(
            path=path,
            name=name,
            methods=_normalize_methods(methods),
            requirements=dict(requirements or {}),
            defaults=dict(defaults or {}),
            priority=priority,
        )

        def decorator(target: T) -> T:
            if isinstance(target, type):
                self._route_class(target, spec)
            elif isinstance(target, (staticmethod, classmethod)):
                raise TypeError("Static and class methods cannot be routed.")
            elif inspect.isfunction(inspect.unwrap(target)):  # type: ignore[arg-type]
                self._route_function(target, spec)
            else:
                raise TypeError(f"@route cannot decorate {target!r}.")
            return target

        return decorator

    def discover(self, modules: Iterable[str] | None = None) -> list[URLPattern]:
        """Import the modules declaring routes and return their URL patterns.

        Without ``modules``, imports the ``KYRO_DISCOVER`` submodules (default ``["views"]``)
        of every installed app and returns all routes. With ``modules`` (dotted paths),
        imports them, and the ``KYRO_DISCOVER`` submodules of those that are packages, and
        returns only the routes they, or their submodules, declare.
        """
        submodules = getattr(settings, "KYRO_DISCOVER", ["views"])
        if modules is None:
            autodiscover_modules(*submodules)
            return self.urlpatterns()
        modules = list(modules)
        for name in modules:
            module = import_module(name)
            if hasattr(module, "__path__"):
                for submodule in submodules:
                    if module_has_submodule(module, submodule):
                        import_module(f"{name}.{submodule}")
        return self.urlpatterns(modules)

    def urlpatterns(self, modules: Iterable[str] | None = None) -> list[URLPattern]:
        """Build the URL patterns of the routes declared so far."""
        routes = list(self._collect())
        if modules is not None:
            prefixes = tuple(modules)
            routes = [r for r in routes if _in_modules(r.module, prefixes)]
        # Higher priority first; stable sort keeps declaration order otherwise.
        routes.sort(key=lambda r: -r.priority)
        _check_names(routes)

        groups: dict[str, list[tuple[Route, Any]]] = {}
        for route in routes:
            for compiled in compile_path(route.path, route.requirements, route.defaults):
                groups.setdefault(compiled.route, []).append((route, compiled))

        patterns = []
        for route_str, members in groups.items():
            handlers = [
                Handler(
                    view=with_conversion(route.view, route.signature, compiled.kwarg_names),
                    methods=route.methods,
                    defaults=compiled.defaults,
                )
                for route, compiled in members
            ]
            # Only the first pattern of a group is ever matched; the others exist so that
            # every route name can be reversed.
            for route, compiled in members:
                view = make_view(handlers, compiled.defaults)
                pattern = django_path(route_str, view, compiled.defaults, name=route.name)
                pattern.kyro_route = route  # type: ignore[attr-defined]
                patterns.append(pattern)
        return patterns

    def _route_function(self, func: Callable[..., Any], spec: RouteSpec) -> None:
        routes = getattr(func, ROUTES_ATTR, None)
        if not isinstance(routes, RouteSet):
            routes = RouteSet()
            setattr(func, ROUTES_ATTR, routes)
        if not any(router is self for router, _ in routes.entries):
            self._targets.append(func)
        # Decorators apply bottom-up: insert first to keep the routes in source order.
        routes.entries.insert(0, (self, spec))

    def _route_class(self, cls: type, spec: RouteSpec) -> None:
        if CLASS_ROUTE_ATTR in vars(cls):
            raise ImproperlyConfigured(f"{cls.__qualname__} has more than one class @route.")
        setattr(cls, CLASS_ROUTE_ATTR, (self, spec))
        for attr, value in vars(cls).items():
            routes = getattr(value, ROUTES_ATTR, None)
            if isinstance(routes, RouteSet):
                routes.owner, routes.attr = cls, attr
        self._targets.append(cls)

    def _collect(self) -> Iterator[Route]:
        for target in self._targets:
            if isinstance(target, type):
                yield from self._class_routes(target)
            else:
                yield from self._function_routes(target)

    def _function_routes(self, func: Callable[..., Any]) -> Iterator[Route]:
        routes: RouteSet = getattr(func, ROUTES_ATTR)
        owner, attr = _owner(func, routes)
        if owner is None or attr is None:
            view = signature = _live(func, routes)
            prefix = None
            module = func.__module__
            auto_name = _slug(f"{module}.{func.__name__}")
        else:
            view, signature = _method_view(owner, attr)
            prefix = self._prefix(owner)
            module = owner.__module__
            if prefix is not None and prefix.name:
                auto_name = prefix.name + _snake(attr)
            else:
                auto_name = _slug(f"{module}.{_snake(owner.__name__)}.{attr}")

        specs = [spec for router, spec in routes.entries if router is self]
        for index, spec in enumerate(specs):
            name = auto_name + (f"_{index}" if index else "")
            yield _make_route(spec, prefix, name, module, view, signature, signature)

    def _class_routes(self, cls: type) -> Iterator[Route]:
        _, spec = vars(cls)[CLASS_ROUTE_ATTR]
        auto_name = _slug(f"{cls.__module__}.{_snake(cls.__name__)}")
        if issubclass(cls, View):
            yield _make_route(spec, None, auto_name, cls.__module__, cls.as_view(), None, cls)
        elif _has_routed_methods(cls):
            return  # The class route is the prefix of its methods.
        elif any("__call__" in vars(klass) for klass in cls.__mro__[:-1]):
            view, signature = _method_view(cls, "__call__")
            yield _make_route(spec, None, auto_name, cls.__module__, view, signature, cls)
        else:
            raise ImproperlyConfigured(
                f"@route on {cls.__qualname__}: the class has no routed method, no __call__ "
                "and is not a Django View."
            )

    def _prefix(self, owner: type) -> RouteSpec | None:
        declared = vars(owner).get(CLASS_ROUTE_ATTR)
        if declared is not None and declared[0] is self:
            return declared[1]
        return None


def _make_route(
    spec: RouteSpec,
    prefix: RouteSpec | None,
    auto_name: str,
    module: str,
    view: Callable[..., Any],
    signature: Callable[..., Any] | None,
    source: Any,
) -> Route:
    prefix = prefix or RouteSpec()
    priority = next((p for p in (spec.priority, prefix.priority) if p is not None), 0)
    return Route(
        path=prefix.path + spec.path,
        name=(prefix.name or "") + spec.name if spec.name is not None else auto_name,
        methods=spec.methods or prefix.methods,
        requirements={**prefix.requirements, **spec.requirements},
        defaults={**prefix.defaults, **spec.defaults},
        priority=priority,
        module=module,
        view=view,
        signature=signature,
        source=source,
    )


def _method_view(owner: type, attr: str) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """A view instantiating ``owner`` for each request and calling its ``attr`` method."""
    member = inspect.getattr_static(owner, attr)
    if isinstance(member, (staticmethod, classmethod)):
        raise ImproperlyConfigured(
            f"{owner.__qualname__}.{attr}: static and class methods cannot be routed."
        )

    if iscoroutinefunction(member):

        async def view(request: Any, **kwargs: Any) -> Any:
            return await getattr(owner(), attr)(request, **kwargs)

    else:

        def view(request: Any, **kwargs: Any) -> Any:
            return getattr(owner(), attr)(request, **kwargs)

    view.__module__ = owner.__module__
    view.__name__ = attr
    view.__qualname__ = f"{owner.__qualname__}.{attr}"
    view.__doc__ = member.__doc__
    view.controller_class = owner  # type: ignore[attr-defined]
    return view, member


def _owner(func: Callable[..., Any], routes: RouteSet) -> tuple[type | None, str | None]:
    """The class defining ``func`` if it is a method, else ``(None, None)``."""
    if routes.owner is not None:
        return routes.owner, routes.attr
    qualname = func.__qualname__
    tail = qualname.rsplit("<locals>.", 1)[-1]
    if "." not in tail:
        return None, None
    if "<locals>" in qualname:
        raise ImproperlyConfigured(
            f"{qualname} is a method of a class defined inside a function: decorate the class "
            "with @route() so that kyro can find it."
        )
    *owner_path, attr = tail.split(".")
    owner = _resolve(func.__module__, owner_path)
    member = inspect.getattr_static(owner, attr, None) if isinstance(owner, type) else None
    if getattr(member, ROUTES_ATTR, None) is not routes:
        raise ImproperlyConfigured(f"Cannot find the class defining {func.__module__}.{qualname}.")
    return owner, attr


def _live(func: Callable[..., Any], routes: RouteSet) -> Callable[..., Any]:
    """The module attribute ``func`` ended up as, so decorators above ``@route`` are kept."""
    if "<locals>" in func.__qualname__:
        return func
    live = _resolve(func.__module__, func.__qualname__.split("."))
    return live if getattr(live, ROUTES_ATTR, None) is routes else func


def _resolve(module: str, path: list[str]) -> Any:
    obj: Any = sys.modules.get(module)
    for part in path:
        obj = getattr(obj, part, None)
    return obj


def _has_routed_methods(cls: type) -> bool:
    return any(isinstance(getattr(v, ROUTES_ATTR, None), RouteSet) for v in vars(cls).values())


def _check_names(routes: list[Route]) -> None:
    seen: dict[str, Route] = {}
    for route in routes:
        other = seen.setdefault(route.name, route)
        if other is not route:
            raise ImproperlyConfigured(
                f"Route name {route.name!r} is used by both {_describe(other)} and "
                f"{_describe(route)}."
            )


def _describe(route: Route) -> str:
    return f"{route.view.__module__}.{route.view.__qualname__} ({route.path!r})"


def _normalize_methods(methods: str | Iterable[str] | None) -> frozenset[str]:
    if methods is None:
        return frozenset()
    if isinstance(methods, str):
        methods = [methods]
    normalized = {method.upper() for method in methods}
    if "GET" in normalized:
        normalized.add("HEAD")
    return frozenset(normalized)


def _in_modules(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes)


def _snake(name: str) -> str:
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower()


def _slug(name: str) -> str:
    return re.sub(r"\W+", "_", name).strip("_").lower()


default_router = Router()
