from django.core.management.base import BaseCommand, CommandError

from kyro.inspection import collect_routes
from kyro.management.output import detail_rows, dumps, methods_label, write_table


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
                if format == "json":
                    self.stdout.write(dumps(routes[0].as_dict()))
                else:
                    write_table(self, ["Property", "Value"], detail_rows(routes[0]))
                return

        if format == "json":
            self.stdout.write(dumps([route.as_dict() for route in routes]))
            return
        headers = ["Name", "Method", "Path"] + (["View"] if show_views else [])
        rows = [
            [route.name or "", methods_label(route.methods), route.path]
            + ([route.view] if show_views else [])
            for route in routes
        ]
        write_table(self, headers, rows)
