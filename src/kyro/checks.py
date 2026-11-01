"""System checks on the routes of the URLconf, run by ``manage.py check`` and ``runserver``.

- ``kyro.W001``: a route without parameters is served by an earlier route.
- ``kyro.W002``: a route name is shared with other routes, so ``reverse()`` is ambiguous.
- ``kyro.W003``: routes declared with ``@route`` are missing from the URLconf.
- ``kyro.W004``: a parameter default is ignored because the parameter is not trailing.
"""

from __future__ import annotations

import re
from typing import Any

from django.core.checks import CheckMessage, Tags, Warning, register

from kyro.inspection import MATCH, RouteInfo, RouteTable
from kyro.router import default_router
from kyro.syntax import ignored_defaults

# Methods tried for routes accepting any method. HEAD and OPTIONS follow GET.
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_REGEX_CHARS = re.compile(r"[<>()\[\]{}*+?|\\^$]")
_LISTED = 5


@register(Tags.urls)
def check_routes(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    table = RouteTable()
    return [
        *_check_shadowed(table),
        *_check_names(table),
        *_check_unmounted(table),
        *_check_ignored_defaults(table),
    ]


def _check_shadowed(table: RouteTable) -> list[CheckMessage]:
    messages: list[CheckMessage] = []
    for info, _ in table.declarations():
        url = next((r for r in info.django_routes if not _REGEX_CHARS.search(r)), None)
        if url is None:
            continue
        tried = [m for m in info.methods if m not in ("HEAD", "OPTIONS")] or list(
            info.methods or _METHODS
        )
        shadowed = {
            method: result.route
            for method, result in table.match_methods(url, tried).items()
            if result.status == MATCH and result.route is not None and result.route is not info
        }
        if not shadowed:
            continue
        culprits = ", ".join(sorted({_label(route) for route in shadowed.values()}))
        if len(shadowed) == len(tried):
            reached = "is never reached"
        else:
            reached = f"is not reached for {', '.join(shadowed)}"
        messages.append(
            Warning(
                f"Route {_label(info)} {reached}: {url} is served by {culprits}.",
                hint="Declare it before the routes shadowing it, or give it a higher priority.",
                obj=_obj(info),
                id="kyro.W001",
            )
        )
    return messages


def _check_names(table: RouteTable) -> list[CheckMessage]:
    by_name: dict[str, list[RouteInfo]] = {}
    for info in table.routes:
        if info.name:
            by_name.setdefault(info.name, []).append(info)
    return [
        Warning(
            f"Route name {name!r} is used by {len(infos)} routes: "
            f"{', '.join(info.path for info in infos)}.",
            hint="reverse() returns the URL of only one of them; give each route its own name.",
            obj=name,
            id="kyro.W002",
        )
        for name, infos in by_name.items()
        if len(infos) > 1 and any(info.is_kyro for info in infos)
    ]


def _check_unmounted(table: RouteTable) -> list[CheckMessage]:
    mounted = {(id(route.source), route.path) for _, route in table.declarations()}
    missing = [
        route for route in default_router.routes() if (id(route.source), route.path) not in mounted
    ]
    if not missing:
        return []
    names = ", ".join(route.name for route in missing[:_LISTED])
    if len(missing) > _LISTED:
        names += f" and {len(missing) - _LISTED} more"
    return [
        Warning(
            f"{len(missing)} route(s) declared with @route are not in the URLconf: {names}.",
            hint="Mount them with kyro.discover() in your URLconf.",
            id="kyro.W003",
        )
    ]


def _check_ignored_defaults(table: RouteTable) -> list[CheckMessage]:
    messages: list[CheckMessage] = []
    for info, route in table.declarations():
        for name in ignored_defaults(route.path, route.requirements, route.defaults):
            messages.append(
                Warning(
                    f"Route {_label(info)}: parameter {name!r} has a default, but it is not "
                    "at the end of the path, so it cannot be omitted from the URL.",
                    hint="Only trailing parameters are optional; remove the default or move "
                    "the parameter to the end.",
                    obj=_obj(info),
                    id="kyro.W004",
                )
            )
    return messages


def _label(info: RouteInfo) -> str:
    return repr(info.name) if info.name else info.path


def _obj(info: RouteInfo) -> str:
    return info.source or info.view
