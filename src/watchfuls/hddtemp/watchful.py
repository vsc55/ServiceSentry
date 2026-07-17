# ─────────────────────────────────────────────────────────────────────────────
# DO NOT DELETE — required project convention.
# Every watchful module must expose a `watchful.py` with this exact alias; the
# implementation lives in __init__.py (see docs/caso-guia-watchful.md,
# docs/ai-module-guide.md, docs/ref-modulos.md — it's on the new-module checklist).
#
# This is NOT dead code: dead-code scans / linters flag it as "unused" because
# the loader imports the *package* (`watchfuls.<name>`), never `.watchful`.
# It exists so every module has the same entry-point filename. Keep it.
# ─────────────────────────────────────────────────────────────────────────────
from . import Watchful  # noqa: F401
