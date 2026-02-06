# Compatibility shim package exposing mercadolivre_upload.auth as top-level `auth`
from importlib import import_module

mod = import_module("mercadolivre_upload.auth")

# Re-export common names if present
for name in dir(mod):
    if not name.startswith("_"):
        globals()[name] = getattr(mod, name)

__all__ = [n for n in dir(mod) if not n.startswith("_")]
