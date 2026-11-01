import re

import pytest
from django.core.exceptions import ImproperlyConfigured

from kyro.syntax import compile_path


def routes(path, **kwargs):
    return [(c.route, c.defaults) for c in compile_path(path, **kwargs)]


def test_static_path():
    assert routes("/blog") == [("blog", {})]


def test_symfony_parameter():
    assert routes("/blog/{slug}") == [("blog/<slug>", {})]


def test_django_parameters_are_kept():
    assert routes("/blog/<int:id>/<slug>") == [("blog/<int:id>/<slug>", {})]


def test_both_syntaxes_in_one_path():
    assert routes("/<int:year>/{slug}") == [("<int:year>/<slug>", {})]


def test_inline_requirement_uses_a_generated_converter():
    [compiled] = compile_path(r"/item/{id<\d+>}")
    assert re.fullmatch(r"item/<kyro_[0-9a-f]{12}:id>", compiled.route)
    assert compiled.params == ("id",)


def test_same_regex_reuses_the_converter():
    first = compile_path(r"/a/{id<\d+>}")[0].route.split(":")[0]
    second = compile_path("/b/{n}", requirements={"n": r"\d+"})[0].route.split(":")[0]
    assert first.removeprefix("a/") == second.removeprefix("b/")


def test_requirement_with_braces():
    [compiled] = compile_path("/{code<[A-Z]{3}>}")
    assert compiled.params == ("code",)


def test_requirement_anchors_are_ignored():
    assert compile_path(r"/{id<^\d+$>}")[0].route == compile_path(r"/{id<\d+>}")[0].route


def test_requirement_on_untyped_django_parameter():
    [compiled] = compile_path("/<id>", requirements={"id": r"\d+"})
    assert compiled.route.startswith("<kyro_")


def test_optional_parameter():
    assert routes("/blog/{page?1}") == [("blog/<page>", {}), ("blog", {"page": "1"})]


def test_optional_parameter_without_default():
    assert routes("/blog/{page?}") == [("blog/<page>", {}), ("blog", {"page": None})]


def test_default_makes_a_trailing_parameter_optional():
    assert routes("/blog/{page}", defaults={"page": 1}) == [
        ("blog/<page>", {}),
        ("blog", {"page": 1}),
    ]


def test_several_trailing_optional_parameters():
    assert routes("/a/{x?1}/{y?2}") == [
        ("a/<x>/<y>", {}),
        ("a/<x>", {"y": "2"}),
        ("a", {"x": "1", "y": "2"}),
    ]


def test_non_trailing_default_is_not_optional():
    assert routes("/{page?1}/list") == [("<page>/list", {})]


def test_other_defaults_are_extra_kwargs():
    assert routes("/feed", defaults={"format": "rss"}) == [("feed", {"format": "rss"})]


@pytest.mark.parametrize(
    ("path", "kwargs", "message"),
    [
        ("/{id}/{id}", {}, "twice"),
        ("/{id}", {"requirements": {"slug": "x"}}, "unknown parameter"),
        ("/<int:id>", {"requirements": {"id": r"\d+"}}, "already has a requirement"),
        ("/{id<\\d+>}", {"requirements": {"id": r"\d+"}}, "already has a requirement"),
        ("/{id?1}", {"defaults": {"id": 2}}, "two defaults"),
        ("/{id<[>}", {}, "Invalid route requirement"),
        ("/{1id}", {}, "not a valid parameter name"),
    ],
)
def test_invalid_paths(path, kwargs, message):
    with pytest.raises(ImproperlyConfigured, match=message):
        compile_path(path, **kwargs)
