"""Symfony-style attribute routing for Django."""

from kyro.params import MapModel
from kyro.router import Router, default_router

__version__ = "0.1.0"

route = default_router.route
discover = default_router.discover

__all__ = ["MapModel", "Router", "default_router", "discover", "route"]
