"""Text and JSON rendering shared by the kyro management commands."""

import json
from collections.abc import Iterable, Mapping
from typing import Any

from django.core.management.base import BaseCommand

from kyro.inspection import RouteInfo


def write_table(command: BaseCommand, headers: list[str], rows: list[list[str]]) -> None:
    widths = [max(len(cell) for cell in column) for column in zip(headers, *rows, strict=True)]
    rule = " " + " ".join("-" * (width + 2) for width in widths)

    def line(cells: list[str]) -> str:
        return (
            " " + " ".join(f" {c.ljust(w)} " for c, w in zip(cells, widths, strict=True)).rstrip()
        )

    command.stdout.write(rule)
    command.stdout.write(command.style.MIGRATE_HEADING(line(headers)))
    command.stdout.write(rule)
    for row in rows:
        command.stdout.write(line(row))
    command.stdout.write(rule)


def detail_rows(route: RouteInfo) -> list[list[str]]:
    return [
        ["Name", route.name or ""],
        ["Path", route.path],
        ["Django routes", ", ".join(route.django_routes)],
        ["Method", methods_label(route.methods)],
        ["Requirements", pairs(route.requirements)],
        ["Defaults", pairs(route.defaults)],
        ["Priority", "-" if route.priority is None else str(route.priority)],
        ["View", route.view],
        ["Defined in", route.source or "-"],
        ["Declared with", "kyro" if route.is_kyro else "Django"],
    ]


def methods_label(methods: Iterable[str]) -> str:
    return "|".join(methods) or "ANY"


def pairs(values: Mapping[str, Any]) -> str:
    return ", ".join(f"{key}: {value}" for key, value in values.items()) or "-"


def dumps(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)
