from django.apps import AppConfig


class KyroConfig(AppConfig):
    name = "kyro"
    verbose_name = "kyro"

    def ready(self) -> None:
        from kyro import checks  # noqa: F401  (registers the system checks)
