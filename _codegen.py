"""stapel-translate contract-emission harness (contract-pipeline.md §2-3).

Closes BACKEND-GAPS X-1/TR-2: until this existed the module had no
``docs/schema.json`` of its own and a frontend pair could only get one by
filtering the monolith's unified schema — which meant a module not mounted
in the monolith had no contract at all, and a pair could not `gen:api`.

Emits the module's own contract triad into ``docs/`` from a single-module
``{translate + core}`` Django instance mounted at the canonical
``/translate/api/v1/`` prefix (api-versioning.md §2):

  docs/schema.json   drf-spectacular OpenAPI, this module only
  docs/flows.json    generate_flow_docs machine artifact (empty — no @flow_step)
  docs/errors.json   generate_error_keys registry (core + this module's keys)

The *mechanism* is stapel_tools.codegen (shared); this file is the thin
per-module *config* wiring the module's settings + canonical mount.

Usage:
    python -m stapel_translate._codegen --out docs        # `make contract`
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _configure() -> None:
    """Configure + boot the single-module Django instance for emission."""
    # `python -m` prepends cwd to sys.path; strip the repo root the way the
    # flat-layout conftest does, so a top-level `views`/`models` module in
    # this repo cannot shadow a stdlib or third-party import.
    repo_root = os.path.dirname(os.path.abspath(__file__))
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != repo_root]

    from django.conf import settings

    if not settings.configured:
        from stapel_translate._codegen_settings import settings_kwargs

        settings.configure(**settings_kwargs())

    import django

    django.setup()

    # drf-spectacular froze its settings singleton at import time — pin the
    # one knob that matters for byte-identity with the monolith aggregate
    # (see _codegen_settings.CODEGEN_SCHEMA_PATH_PREFIX).
    from drf_spectacular.settings import spectacular_settings

    from stapel_translate._codegen_settings import CODEGEN_SCHEMA_PATH_PREFIX

    spectacular_settings.SCHEMA_PATH_PREFIX = CODEGEN_SCHEMA_PATH_PREFIX

    # Reproduce the monolith's process-global JWTCookieAuth extension
    # registration: without it every protected operation loses its
    # `security` block relative to the aggregate slice.
    from stapel_core.django.openapi.swagger import _register_jwt_auth_extension

    _register_jwt_auth_extension()


def _require_python_312() -> None:
    """Abort emission if not running the pinned 3.12 interpreter.

    drf-spectacular's rendering of component descriptions (``Optional[X]``
    vs ``X | None``) depends on the Python **minor** version — contracts
    emitted on anything else produce false diffs against the committed
    docs/*.json forever.
    """
    if sys.version_info[:2] != (3, 12):
        got = f"{sys.version_info.major}.{sys.version_info.minor}"
        raise SystemExit(
            f"stapel-translate contract emission ABORTED: running Python {got}, "
            "but contracts must be emitted on Python 3.12 (the CI/monolith "
            "pin). Re-run under a 3.12 interpreter."
        )


def main(argv: list[str] | None = None) -> int:
    _require_python_312()

    parser = argparse.ArgumentParser(
        prog="stapel-translate-contract",
        description="Emit this module's contract triad (schema.json + flows.json "
        "+ errors.json) into --out, canonical /translate/api/v1/ prefix.",
    )
    parser.add_argument(
        "--out",
        default="docs",
        help="Output directory for the triad (default: docs).",
    )
    args = parser.parse_args(argv)

    _configure()

    from stapel_tools.codegen import emit_errors, emit_flows, emit_schema

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    paths = emit_schema(out / "schema.json")
    flows = emit_flows(out / "flows.json")
    errors = emit_errors(out / "errors.json")

    print(
        f"stapel-translate contract: {paths} paths, {flows} flows, {errors} error "
        f"keys → {out}/",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
