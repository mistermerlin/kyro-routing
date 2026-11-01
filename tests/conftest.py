import sys
import types

import pytest
from django.urls import clear_url_caches

MOUNTED = "tests._mounted_urls"


@pytest.fixture
def urlconf(settings):
    """Serve the given URL patterns as the root URLconf."""

    def _install(patterns):
        module = types.ModuleType(MOUNTED)
        module.urlpatterns = patterns
        sys.modules[MOUNTED] = module
        settings.ROOT_URLCONF = MOUNTED
        clear_url_caches()
        return patterns

    yield _install
    sys.modules.pop(MOUNTED, None)
    clear_url_caches()


@pytest.fixture
def mount(urlconf):
    """Serve a router's routes as the root URLconf; returns the URL patterns."""

    def _mount(router, modules=None):
        return urlconf(router.urlpatterns(modules))

    return _mount
