"""Convert URL parameters into the types a view's signature asks for.

- Scalars (``int``, ``float``, ``Decimal``, ``bool``, ``UUID``, ``date``, ``datetime``,
  ``Enum`` subclasses): the URL value is converted; a value that does not convert is a 404.
- Models: the object is fetched, and a missing object is a 404 (or ``None`` when the
  annotation is optional). The lookup is chosen like Symfony's entity value resolver:

  1. ``Annotated[Post, MapModel(slug="post_slug")]``: explicit field -> URL parameter mapping.
  2. A URL parameter named like the argument (``{post}`` for ``post: Post``): lookup by pk.
  3. URL parameters named like model fields (``{slug}`` for ``post: Post``). They are
     consumed: passed to the view only if its signature accepts them.
"""

from __future__ import annotations

import functools
import inspect
import types
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Union, get_args, get_origin, get_type_hints
from uuid import UUID

from asgiref.sync import iscoroutinefunction, sync_to_async
from django.core.exceptions import FieldDoesNotExist, ImproperlyConfigured, ValidationError
from django.db import models
from django.http import Http404

_SCALARS = (int, float, str, bool, Decimal, UUID, date, datetime)
_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class MapModel:
    """Explicit lookup of a model argument: ``Annotated[Post, MapModel(slug="post_slug")]``.

    Keys are model fields, values are URL parameter names.
    """

    def __init__(self, **lookup: str) -> None:
        if not lookup:
            raise TypeError("MapModel() needs at least one field=url_parameter pair.")
        self.lookup = lookup

    def __repr__(self) -> str:
        args = ", ".join(f"{field}={param!r}" for field, param in self.lookup.items())
        return f"MapModel({args})"


def with_conversion(
    view: Callable[..., Any], source: Callable[..., Any] | None, url_kwargs: Iterable[str]
) -> Callable[..., Any]:
    """Wrap ``view`` so its kwargs are converted according to ``source``'s signature."""
    if source is None:
        return view
    convert = build_converter(source, url_kwargs)
    if convert is None:
        return view

    if iscoroutinefunction(view):
        convert_async = sync_to_async(convert) if convert.uses_db else None

        async def wrapper(request: Any, **kwargs: Any) -> Any:
            kwargs = await convert_async(kwargs) if convert_async else convert(kwargs)
            return await view(request, **kwargs)

    else:

        def wrapper(request: Any, **kwargs: Any) -> Any:
            return view(request, **convert(kwargs))

    functools.update_wrapper(wrapper, view)
    return wrapper


def build_converter(func: Callable[..., Any], url_kwargs: Iterable[str]) -> _Converter | None:
    """Plan the conversions for ``func`` given the kwargs its route provides."""
    url_kwargs = set(url_kwargs)
    signature = inspect.signature(func)
    hints = _type_hints(func)
    named = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    accepted = {name for name, p in signature.parameters.items() if p.kind in named}
    accepts_any = any(p.kind is p.VAR_KEYWORD for p in signature.parameters.values())

    scalars: list[tuple[str, type]] = []
    model_params: list[
        tuple[str, type[models.Model], MapModel | None, bool, inspect.Parameter]
    ] = []
    for name, param in signature.parameters.items():
        if name not in accepted or name not in hints:
            continue
        typ, mapping, optional = _unwrap(hints[name])
        if _is_model(typ):
            model_params.append((name, typ, mapping, optional, param))
        elif name in url_kwargs and _is_scalar(typ):
            scalars.append((name, typ))

    model_names = {name for name, *_ in model_params}
    lookups: list[_Lookup] = []
    consumed: set[str] = set()
    claimed: dict[str, str] = {}
    for name, model, mapping, optional, param in model_params:
        if mapping is not None:
            missing = sorted(set(mapping.lookup.values()) - url_kwargs)
            if missing:
                raise ImproperlyConfigured(
                    f"{func.__qualname__}(): {mapping!r} refers to unknown URL parameter(s) "
                    f"{missing}."
                )
            lookup = dict(mapping.lookup)
        elif name in url_kwargs:
            lookup = {"pk": name}
        else:
            lookup = {k: k for k in sorted(url_kwargs - model_names) if _is_field(model, k)}
            for key in lookup:
                if key in claimed:
                    raise ImproperlyConfigured(
                        f"{func.__qualname__}(): URL parameter {key!r} could look up both "
                        f"{claimed[key]!r} and {name!r}; use MapModel to choose."
                    )
                claimed[key] = name
        if not lookup:
            if param.default is param.empty:
                raise ImproperlyConfigured(
                    f"{func.__qualname__}(): no URL parameter to look up {name!r} "
                    f"({model.__name__}). Add {{{name}}} to the path or use MapModel."
                )
            continue
        lookups.append(_Lookup(name, model, lookup, optional))
        consumed.update(param_name for param_name in lookup.values() if param_name != name)

    if not scalars and not lookups:
        return None
    drop = set() if accepts_any else consumed - accepted
    return _Converter(scalars, lookups, drop)


@dataclass(frozen=True)
class _Lookup:
    name: str
    model: type[models.Model]
    lookup: dict[str, str]
    """Model field -> URL parameter."""
    optional: bool

    def fetch(self, kwargs: dict[str, Any]) -> models.Model | None:
        values = {field: kwargs.get(param) for field, param in self.lookup.items()}
        try:
            if any(value is None for value in values.values()):
                raise self.model.DoesNotExist
            return self.model._default_manager.get(**values)
        except (self.model.DoesNotExist, ValueError, TypeError, ValidationError):
            if self.optional:
                return None
            raise Http404(f"No {self.model._meta.object_name} matches the given query.") from None


class _Converter:
    def __init__(
        self, scalars: list[tuple[str, type]], lookups: list[_Lookup], drop: set[str]
    ) -> None:
        self.scalars = scalars
        self.lookups = lookups
        self.drop = drop
        self.uses_db = bool(lookups)

    def __call__(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        converted = dict(kwargs)
        for name, typ in self.scalars:
            if name in converted:
                converted[name] = _to_scalar(converted[name], typ)
        for lookup in self.lookups:
            converted[lookup.name] = lookup.fetch(kwargs)
        for name in self.drop:
            converted.pop(name, None)
        return converted


def _to_scalar(value: Any, typ: type) -> Any:
    if value is None or (isinstance(value, typ) and not (typ is int and isinstance(value, bool))):
        return value
    text = str(value)
    try:
        if typ is bool:
            if text.lower() in _TRUE:
                return True
            if text.lower() in _FALSE:
                return False
            raise ValueError(text)
        if issubclass(typ, Enum):
            for member in typ:
                if str(member.value) == text:
                    return member
            raise ValueError(text)
        if typ is datetime:
            return datetime.fromisoformat(text)
        if typ is date:
            return date.fromisoformat(text)
        return typ(text)
    except (ValueError, TypeError, ArithmeticError):
        raise Http404(f"Invalid value {text!r} for a {typ.__name__} parameter.") from None


def _type_hints(func: Callable[..., Any]) -> dict[str, Any]:
    try:
        return get_type_hints(inspect.unwrap(func), include_extras=True)
    except (NameError, TypeError):
        parameters = inspect.signature(func).parameters.values()
        return {
            p.name: p.annotation
            for p in parameters
            if p.annotation is not p.empty and not isinstance(p.annotation, str)
        }


def _unwrap(hint: Any) -> tuple[Any, MapModel | None, bool]:
    """Return ``(type, MapModel or None, optional)`` for an annotation."""
    origin = get_origin(hint)
    if origin is Annotated:
        inner, *extras = get_args(hint)
        typ, mapping, optional = _unwrap(inner)
        mapping = mapping or next((e for e in extras if isinstance(e, MapModel)), None)
        return typ, mapping, optional
    if origin is Union or origin is types.UnionType:
        args = [arg for arg in get_args(hint) if arg is not type(None)]
        if len(args) == 1:
            typ, mapping, _ = _unwrap(args[0])
            return typ, mapping, True
        return None, None, False
    return hint, None, False


def _is_model(typ: Any) -> bool:
    return isinstance(typ, type) and issubclass(typ, models.Model)


def _is_scalar(typ: Any) -> bool:
    return typ in _SCALARS or (isinstance(typ, type) and issubclass(typ, Enum))


def _is_field(model: type[models.Model], name: str) -> bool:
    if name == "pk":
        return True
    try:
        model._meta.get_field(name)
    except FieldDoesNotExist:
        return False
    return True
