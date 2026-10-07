"""
Generates the ANDES code of the models in models/ into ~/.andes/pycode, next to the built-in models:

    python prepare_models.py

Run it after `andes prepare` (which rewrites the pycode index without these models) and after
editing a model's parameters, variables or equations. Edits to the Python relay logic need no
regeneration.
"""

import logging

import andes

from models import register_models

andes.config_logger(stream_level=logging.INFO)
register_models()

# autogen_stale=False and nomp=True keep the code generation in this process; the worker processes
# ANDES would start otherwise don't have the models registered
ss = andes.System(autogen_stale=False)
ss.prepare(incremental=True, nomp=True)
