from __future__ import annotations

import importlib
import sys
import types

_pipeline = importlib.import_module(".pipeline", __name__)


class _SearchPackage(types.ModuleType):
    def __getattr__(self, name):
        return getattr(_pipeline, name)

    def __setattr__(self, name, value):
        if name.startswith("__") or name in {"_pipeline"}:
            super().__setattr__(name, value)
        else:
            setattr(_pipeline, name, value)


sys.modules[__name__].__class__ = _SearchPackage
