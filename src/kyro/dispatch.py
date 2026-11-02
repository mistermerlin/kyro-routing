"""Choose the view of a route by HTTP method when several routes share a path."""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from asgiref.sync import async_to_sync, iscoroutinefunction
from django.http import HttpResponseNotAllowed


@dataclass(frozen=True)
class Handler:
    view: Callable[..., Any]
    methods: frozenset[str]
    """Accepted HTTP methods; empty means any."""
    defaults: Mapping[str, Any]
    """Extra kwargs this handler receives."""

    def accepts(self, method: str) -> bool:
        return not self.methods or method in self.methods


def make_view(handlers: list[Handler], own_defaults: Mapping[str, Any]) -> Callable[..., Any]:
    """Build the view of one URL pattern.

    ``handlers`` are all the routes sharing the pattern's path, in matching order. The first
    one accepting the request method is called; if none does, the response is a 405.
    ``own_defaults`` are the extra kwargs Django passes for this pattern: they are replaced by
    the defaults of the handler that is called.
    """
    if len(handlers) == 1 and not handlers[0].methods:
        return handlers[0].view

    allowed = sorted(set().union(*(handler.methods for handler in handlers)))

    def select(request: Any, kwargs: dict[str, Any]) -> tuple[int | None, dict[str, Any]]:
        for index, handler in enumerate(handlers):
            if handler.accepts(request.method):
                captured = {k: v for k, v in kwargs.items() if k not in own_defaults}
                return index, {**handler.defaults, **captured}
        return None, kwargs

    view: Callable[..., Any]
    if all(iscoroutinefunction(handler.view) for handler in handlers):

        async def async_view(request: Any, **kwargs: Any) -> Any:
            index, kwargs = select(request, kwargs)
            if index is None:
                return HttpResponseNotAllowed(allowed)
            return await handlers[index].view(request, **kwargs)

        view = async_view
    else:
        calls = [
            async_to_sync(handler.view) if iscoroutinefunction(handler.view) else handler.view
            for handler in handlers
        ]

        def sync_view(request: Any, **kwargs: Any) -> Any:
            index, kwargs = select(request, kwargs)
            if index is None:
                return HttpResponseNotAllowed(allowed)
            return calls[index](request, **kwargs)

        view = sync_view

    if len(handlers) == 1:
        functools.update_wrapper(view, handlers[0].view)
    else:
        _share_markers(view, handlers)
    return view


# View attributes read by Django middleware to lift a protection from a view:
# ``csrf_exempt`` (CsrfViewMiddleware) and ``login_required = False``
# (LoginRequiredMiddleware, set by ``login_not_required``).
_MARKERS = ("csrf_exempt", "login_required")
_MISSING = object()


def _share_markers(view: Callable[..., Any], handlers: list[Handler]) -> None:
    """Give the view of a shared path the markers all its handlers agree on.

    The middleware only sees this view, not the handler it calls. A marker set by some
    handlers only is left out, so a path is never less protected than its most protected
    handler.
    """
    for marker in _MARKERS:
        values = [getattr(handler.view, marker, _MISSING) for handler in handlers]
        if values[0] is not _MISSING and all(value == values[0] for value in values):
            setattr(view, marker, values[0])
