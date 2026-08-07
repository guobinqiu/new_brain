from __future__ import annotations

import importlib
import sys
import types

from config import CONFIG

_backend = importlib.import_module(f".{CONFIG.store.type.rsplit('/', 1)[-1]}", __name__)


class _StorePackage(types.ModuleType):
    def __getattr__(self, name):
        return getattr(_backend, name)

    def __setattr__(self, name, value):
        if name.startswith("__") or name in {"_backend"}:
            super().__setattr__(name, value)
        else:
            setattr(_backend, name, value)


sys.modules[__name__].__class__ = _StorePackage
