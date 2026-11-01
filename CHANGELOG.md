# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-01

First release.

### Added

- `@route` decorator for functions (sync and async), methods of any class, classes with
  `__call__` and Django class-based views. On a class with routed methods, the class route
  is a prefix for path, name, requirements, defaults and methods.
- Paths in Django syntax (`<int:id>`) and Symfony syntax (`{id}`, `{id<\d+>}`, `{page?1}`,
  `{page?}`), mixed freely. Trailing parameters with a default are optional.
- Route options: `name` (generated when omitted), `methods`, `requirements`, `defaults` and
  `priority`. Several routes can share a path with different methods; other methods get a
  405 with an `Allow` header.
- Parameter conversion from annotations: `int`, `float`, `Decimal`, `bool`, `UUID`, `date`,
  `datetime` and `Enum`, plus Django models looked up by primary key, by field or with
  `MapModel`. Invalid values and missing objects are a 404.
- `kyro.discover()` to build the URL patterns from the `views` modules of the installed
  apps, or from given modules; `Router` for separate sets of routes.
- `debug_router` management command, listing the routes of the project or showing one in
  detail.
- `router_match` management command, telling which route serves a request.
- System checks: shadowed routes (`kyro.W001`), shared route names (`kyro.W002`), routes
  missing from the URLconf (`kyro.W003`) and ignored defaults (`kyro.W004`).
- Support for Python 3.10 to 3.14 and Django 4.2, 5.2, 6.0 and 6.1.

[Unreleased]: https://github.com/mistermerlin/kyro-routing/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mistermerlin/kyro-routing/releases/tag/v0.1.0
