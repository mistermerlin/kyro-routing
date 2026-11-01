import sys
import types

import pytest
from django.urls import clear_url_caches

MOUNTED = "tests._mounted_urls"


@pytest.fixture
def mount(settings):
    """Serve a router's routes as the root URLconf; returns the URL patterns."""

    def _mount(router, modules=None):
        module = types.ModuleType(MOUNTED)
        module.urlpatterns = router.urlpatterns(modules)
        sys.modules[MOUNTED] = module
        settings.ROOT_URLCONF = MOUNTED
        clear_url_caches()
        return module.urlpatterns

    yield _mount
    sys.modules.pop(MOUNTED, None)
    clear_url_caches()
