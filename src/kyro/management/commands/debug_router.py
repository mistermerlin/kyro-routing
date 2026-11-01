import json

from django.core.management.base import BaseCommand, CommandError

from kyro.inspection import RouteInfo, collect_routes


class Command(BaseCommand):
    help = "List the routes of the project, or show the details of one route."

    def add_arguments(self, parser):
        parser.add_argument(
            "name",
            nargs="?",
            help="Route name, or part of it: one match is shown in detail, several are listed.",
        )
        parser.add_argument("--format", choices=["txt", "json"], default="txt")
        parser.add_argument(
            "--show-views", action="store_true", help="Add the view of each route to the list."
        )
        parser.add_argument("--urlconf", help="URLconf module to inspect (default: ROOT_URLCONF).")

    def handle(self, *args, name=None, format="txt", show_views=False, urlconf=None, **options):
        routes = collect_routes(urlconf)
        if name is not None:
            routes = [r for r in routes if r.name == name] or [
                r for r in routes if r.name and name in r.name
            ]
            if not routes:
                raise CommandError(f"No route matches {name!r}.")
            if len(routes) == 1:
                self._detail(routes[0], format)
                return
        self._list(routes, format, show_views)

    def _list(self, routes, format, show_views):
        if format == "json":
            self.stdout.write(_dumps([route.as_dict() for route in routes]))
            return
        headers = ["Name", "Method", "Path"] + (["View"] if show_views else [])
        rows = [
            [route.name or "", _methods(route), route.path] + ([route.view] if show_views else [])
            for route in routes
        ]
        self._table(headers, rows)

    def _detail(self, route: RouteInfo, format):
        if format == "json":
            self.stdout.write(_dumps(route.as_dict()))
            return
        rows = [
            ["Name", route.name or ""],
            ["Path", route.path],
            ["Django routes", ", ".join(route.django_routes)],
            ["Method", _methods(route)],
            ["Requirements", _pairs(route.requirements)],
            ["Defaults", _pairs(route.defaults)],
            ["Priority", "-" if route.priority is None else str(route.priority)],
            ["View", route.view],
            ["Defined in", route.source or "-"],
            ["Declared with", "kyro" if route.is_kyro else "Django"],
        ]
        self._table(["Property", "Value"], rows)

    def _table(self, headers, rows):
        widths = [max(len(cell) for cell in column) for column in zip(headers, *rows, strict=True)]
        rule = " " + " ".join("-" * (width + 2) for width in widths)

        def line(cells):
            return (
                " "
                + " ".join(f" {c.ljust(w)} " for c, w in zip(cells, widths, strict=True)).rstrip()
            )

        self.stdout.write(rule)
        self.stdout.write(self.style.MIGRATE_HEADING(line(headers)))
        self.stdout.write(rule)
        for row in rows:
            self.stdout.write(line(row))
        self.stdout.write(rule)


def _methods(route: RouteInfo) -> str:
    return "|".join(route.methods) or "ANY"


def _pairs(values) -> str:
    return ", ".join(f"{key}: {value}" for key, value in values.items()) or "-"


def _dumps(data) -> str:
    return json.dumps(data, indent=2, default=str)
