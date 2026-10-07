"""
ANDES models kept outside the ANDES package, for PSS®E dynamic models ANDES doesn't have
(FRQTPAT, LDSHBL).

ANDES builds only the models listed in `andes.models.file_classes` and imports each file as
`andes.models.<file>`, so `register_models()` puts ours in both places. It has to run before any
ANDES System is created (`andes.load`, `andes.System`). The generated code comes from
`prepare_models.py`.
"""

import sys

import andes.models

from . import frqtpat, ldshbl
from .frqtpat import add_frqtpat_relays
from .ldshbl import add_ldshbl_relays

MODEL_FILES = [
    (frqtpat, ["FRQTPAT"]),  # module, model classes in it
    (ldshbl, ["LDSHBL"]),
]


def register_models():
    """Makes the models in this folder known to ANDES; a second call does nothing."""
    for module, class_names in MODEL_FILES:
        file_name = module.__name__.split(".")[-1]
        entry = (file_name, class_names)
        if entry in andes.models.file_classes:
            continue
        sys.modules[f"andes.models.{file_name}"] = module
        andes.models.file_classes.append(entry)


def find_stale_models(ss):
    """Names of the models in this folder whose generated code is missing or out of date."""
    stale_models = []
    for _, class_names in MODEL_FILES:
        for name in class_names:
            model = ss.models[name]
            if model.calls.md5 != model.get_md5():
                stale_models.append(name)
    return stale_models
