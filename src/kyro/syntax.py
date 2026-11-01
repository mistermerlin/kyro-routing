"""Translate Symfony-style and Django-style route paths into Django ``path()`` routes.

Supported placeholders, freely mixed in one path:

- Django: ``<name>``, ``<int:name>`` (any registered converter)
- Symfony: ``{name}``, ``{name<regex>}``, ``{name?default}``, ``{name?}`` (default ``None``),
  ``{name<regex>?default}``

Trailing parameters that have a default are optional, as in Symfony: ``/blog/{page?1}``
compiles to two Django routes, ``blog/<page>`` and ``blog`` (with ``page="1"``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.urls import register_converter

_SYMFONY = r"\{(?P<s_name>\w+)(?:<(?P<s_req>.*?)>)?(?P<s_opt>\?(?P<s_default>[^}]*))?\}"
_DJANGO = r"<(?:(?P<d_conv>[^>:]+):)?(?P<d_name>[^>]+)>"
_TOKEN_RE = re.compile(f"{_SYMFONY}|{_DJANGO}")

# Characters removed together with a trailing optional parameter (same set as Symfony).
SEPARATORS = "/,;.:-_~+*=@|"

_NO_DEFAULT: Any = object()


class RegexConverter:
    """Base class of the converters generated for ``{name<regex>}`` requirements."""

    regex = "[^/]+"

    def to_python(self, value: str) -> str:
        return value

    def to_url(self, value: Any) -> str:
        return str(value)


_regex_converters: dict[str, str] = {}


def regex_converter(regex: str) -> str:
    """Return the name of a Django converter matching ``regex``, registering it if needed."""
    regex = _sanitize_regex(regex)
    name = _regex_converters.get(regex)
    if name is None:
        name = "kyro_" + hashlib.sha1(regex.encode()).hexdigest()[:12]
        converter = type(f"RegexConverter_{name}", (RegexConverter,), {"regex": regex})
        register_converter(converter, name)
        _regex_converters[regex] = name
    return name


def _sanitize_regex(regex: str) -> str:
    # Requirements match a whole segment, so anchors are redundant (Symfony strips them too).
    if regex.startswith("^"):
        regex = regex[1:]
    if regex.endswith("$") and not regex.endswith(r"\$"):
        regex = regex[:-1]
    if not regex:
        raise ImproperlyConfigured("Route requirements cannot be empty.")
    try:
        re.compile(regex)
    except re.error as exc:
        raise ImproperlyConfigured(f"Invalid route requirement {regex!r}: {exc}") from exc
    return regex


@dataclass
class _Param:
    name: str
    converter: str | None
    default: Any

    @property
    def optional(self) -> bool:
        return self.default is not _NO_DEFAULT

    def render(self) -> str:
        return f"<{self.converter}:{self.name}>" if self.converter else f"<{self.name}>"


@dataclass(frozen=True)
class CompiledRoute:
    """One Django route produced from a kyro path."""

    route: str
    """Route in Django ``path()`` syntax, without leading slash."""
    defaults: dict[str, Any]
    """Extra kwargs for the view: omitted optional parameters and non-path defaults."""
    params: tuple[str, ...]
    """Names of the parameters captured from the URL."""

    @property
    def kwarg_names(self) -> tuple[str, ...]:
        return (*self.params, *self.defaults)


def compile_path(
    path: str,
    requirements: Mapping[str, str] | None = None,
    defaults: Mapping[str, Any] | None = None,
) -> list[CompiledRoute]:
    """Compile ``path`` into Django routes, the most specific first."""
    requirements = dict(requirements or {})
    defaults = dict(defaults or {})

    tokens: list[str | _Param] = []
    position = 0
    for match in _TOKEN_RE.finditer(path):
        if match.start() > position:
            tokens.append(path[position : match.start()])
        tokens.append(_make_param(path, match, requirements, defaults))
        position = match.end()
    if position < len(path):
        tokens.append(path[position:])

    names = [token.name for token in tokens if isinstance(token, _Param)]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ImproperlyConfigured(f"Route {path!r} uses parameter(s) {duplicates} twice.")
    unknown = sorted(set(requirements) - set(names))
    if unknown:
        raise ImproperlyConfigured(
            f"Route {path!r} has requirements for unknown parameter(s) {unknown}."
        )
    extra = {key: value for key, value in defaults.items() if key not in names}

    cuts = [len(tokens), *reversed(_optional_indexes(tokens))]
    compiled = []
    for cut in cuts:
        kept = list(tokens[:cut])
        last = kept[-1] if kept else None
        if cut < len(tokens) and isinstance(last, str) and last and last[-1] in SEPARATORS:
            kept[-1] = last[:-1]
        dropped = [token for token in tokens[cut:] if isinstance(token, _Param)]
        route = "".join(token if isinstance(token, str) else token.render() for token in kept)
        compiled.append(
            CompiledRoute(
                route=route.removeprefix("/"),
                defaults={**extra, **{param.name: param.default for param in dropped}},
                params=tuple(token.name for token in kept if isinstance(token, _Param)),
            )
        )
    return compiled


def _make_param(
    path: str, match: re.Match[str], requirements: dict[str, str], defaults: dict[str, Any]
) -> _Param:
    if match["s_name"] is not None:
        name, regex, converter = match["s_name"], match["s_req"], None
        default = _NO_DEFAULT
        if match["s_opt"] is not None:
            default = match["s_default"] if match["s_default"] else None
    else:
        name, regex, converter = match["d_name"], None, match["d_conv"]
        default = _NO_DEFAULT

    if not name.isidentifier():
        raise ImproperlyConfigured(f"Route {path!r}: {name!r} is not a valid parameter name.")
    if name in requirements:
        if regex is not None or converter is not None:
            raise ImproperlyConfigured(
                f"Route {path!r}: parameter {name!r} already has a requirement or converter."
            )
        regex = requirements[name]
    if name in defaults:
        if default is not _NO_DEFAULT:
            raise ImproperlyConfigured(f"Route {path!r}: parameter {name!r} has two defaults.")
        default = defaults[name]
    if regex is not None:
        converter = regex_converter(regex)
    return _Param(name, converter, default)


def _optional_indexes(tokens: list[str | _Param]) -> list[int]:
    """Indexes of the trailing optional parameters, in path order.

    Optional parameters may only be separated by a single separator character.
    """
    indexes: list[int] = []
    i = len(tokens) - 1
    while i >= 0 and isinstance(tokens[i], _Param) and tokens[i].optional:
        indexes.append(i)
        i -= 1
        between = tokens[i] if i >= 0 else None
        if isinstance(between, str) and len(between) == 1 and between in SEPARATORS:
            before = tokens[i - 1] if i >= 1 else None
            if isinstance(before, _Param) and before.optional:
                i -= 1
    indexes.reverse()
    return indexes
