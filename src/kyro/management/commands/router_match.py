from django.core.management.base import BaseCommand, CommandError

from kyro.inspection import MATCH, METHOD_NOT_ALLOWED, NO_MATCH, match_route
from kyro.management.output import detail_rows, dumps, methods_label, pairs, write_table


class Command(BaseCommand):
    help = "Show which route serves a request to a path."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to match, e.g. /blog/hello (a full URL works too).")
        parser.add_argument("--method", default="GET", help="HTTP method (default: GET).")
        parser.add_argument("--format", choices=["txt", "json"], default="txt")
        parser.add_argument("--urlconf", help="URLconf module to use (default: ROOT_URLCONF).")

    def handle(self, *args, path, method="GET", format="txt", urlconf=None, **options):
        result = match_route(path, method, urlconf)
        if format == "json":
            self.stdout.write(dumps(result.as_dict()))
            if result.status != MATCH:
                raise CommandError(f"No route serves {result.method} {result.path}.")
            return

        verbose = options.get("verbosity", 1) >= 2
        trace = [(info, status) for info, status in result.trace if verbose or status != NO_MATCH]
        others = [(info, status) for info, status in trace if status != MATCH]
        if others:
            rows = [
                [info.name or "", methods_label(info.methods), info.path, status]
                for info, status in trace
            ]
            write_table(self, ["Name", "Method", "Path", "Result"], rows)
            self.stdout.write("")

        if result.status == NO_MATCH:
            raise CommandError(f"None of the routes match the path {result.path!r}.")
        if result.status == METHOD_NOT_ALLOWED:
            raise CommandError(
                f"The path {result.path!r} matches, but not the method {result.method}"
                f" (allowed: {', '.join(result.allowed) or 'none'})."
            )

        route = result.route
        self.stdout.write(self.style.SUCCESS(f"Route {route.name or route.path!r} matches."))
        self.stdout.write("")
        rows = [*detail_rows(route), ["View kwargs", pairs(result.kwargs)]]
        write_table(self, ["Property", "Value"], rows)
