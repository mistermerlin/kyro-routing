import kyro


def test_version():
    assert kyro.__version__ == "0.1.1"


def test_django_is_configured(settings):
    assert "kyro" in settings.INSTALLED_APPS
