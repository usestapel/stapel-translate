"""Per-module contract triad + capabilities + drift gate (contract-pipeline.md §2-3).

stapel-translate emits its OWN contract triad — ``docs/schema.json`` (OpenAPI),
``docs/flows.json`` (``[]``, no ``@flow_step`` here) and ``docs/errors.json``
— from a single-module ``{translate + core}`` Django instance mounted at the
canonical ``/translate/api/v1/`` prefix (``_codegen.py`` / ``_codegen_settings.py``
/ ``codegen_urls.py``). Before 0.7.0 it did not: the only way to get this
module's OpenAPI was to filter stapel-example-monolith's unified schema, which
made this repo's contract a property of a *different* repo's install list, and
left a ``gen:api`` frontend pair with nothing to generate from wherever the
module was mounted on its own (BACKEND-GAPS X-1/TR-2).

``docs/capabilities.json`` stays HAND-AUTHORED apart from module/version and
the derived ``surface`` section (see ``tests/test_capabilities_surface.py`` and
the note in ``docs/capabilities.meta.json``) — so it is gated here only for the
things a machine can check against the emitted triad.

stapel-translate is mounted in stapel-example-monolith, but the aggregate slice
is not diffed here: the monolith's schema is a build artifact of another repo
on another schedule. Validation is standalone (determinism, self-contained
``$ref`` closure, canonical-prefix paths, JWT security on protected ops).

Regenerate after any change to a serializer/view/url/error key:

    make contract

then commit docs/{schema,flows,errors,capabilities}.json + docs/llms.txt +
README.md.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PY = sys.version_info[:2]
if _PY != (3, 12):
    _GOT = f"{_PY[0]}.{_PY[1]}"
    pytest.skip(
        "stapel-translate contract tests require Python 3.12 (the CI/monolith "
        f"pin) — running {_GOT}. drf-spectacular renders component descriptions "
        "(Optional[X] vs X | None) differently across Python minor versions, so "
        "drift/identity checks emitted+compared under any other minor produce "
        "false diffs. Skipping on any non-3.12 interpreter.",
        allow_module_level=True,
    )

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
TRIAD = ("schema.json", "flows.json", "errors.json")
#: The fifth artifact (badge-canon §3): docs/llms.txt, rendered from
#: docs/capabilities.json (+ schema/errors/flows) by stapel_tools.llms_txt.
ARTIFACTS = TRIAD + ("llms.txt",)

#: Must equal LLMS_TXT_BUDGET in the Makefile; the test at the bottom of this
#: file is what keeps the two from drifting apart.
LLMS_TXT_BUDGET = 6000


def _emit(out_dir: Path) -> None:
    """Emit the triad into *out_dir*, then llms.txt rendered against it.

    llms.txt is rendered from the REAL committed docs/capabilities.json (not a
    regenerated one — this module's capabilities document is hand-authored),
    exactly as `make contract-check` does, so this step also catches a stale
    llms.txt independently of the triad.
    """
    docs = out_dir / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, "-m", "stapel_translate._codegen", "--out", str(docs)],
        cwd=str(REPO), check=True, capture_output=True,
    )
    (docs / "capabilities.json").write_bytes((DOCS / "capabilities.json").read_bytes())
    subprocess.run(
        [
            sys.executable, "-m", "stapel_tools.llms_txt", str(out_dir),
            "--out", str(docs), "--budget", str(LLMS_TXT_BUDGET),
        ],
        cwd=str(REPO), check=True, capture_output=True,
    )


def test_contract_artifacts_committed():
    for name in ARTIFACTS + ("capabilities.json",):
        assert (DOCS / name).is_file(), f"missing docs/{name} — run `make contract`"
    assert (DOCS / "capabilities.meta.json").is_file(), (
        "missing docs/capabilities.meta.json — the curated layer is "
        "hand-written and committed, not generated"
    )


def test_contract_has_no_drift(tmp_path):
    _emit(tmp_path)
    for name in ARTIFACTS:
        committed = (DOCS / name).read_bytes()
        regenerated = (tmp_path / "docs" / name).read_bytes()
        assert committed == regenerated, (
            f"docs/{name} drifted — run `make contract` and commit docs/{name}"
        )


def test_emission_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _emit(a)
    _emit(b)
    for name in ARTIFACTS:
        assert (a / "docs" / name).read_bytes() == (b / "docs" / name).read_bytes()


def test_paths_carry_the_canonical_prefix():
    schema = json.loads((DOCS / "schema.json").read_text())
    assert schema["paths"], "schema has no paths"
    stray = [p for p in schema["paths"] if not p.startswith("/translate/api/v1/")]
    assert not stray, f"paths outside the canonical /translate/api/v1/ mount: {stray}"


def test_flows_are_empty_no_flow_step_annotations():
    flows = json.loads((DOCS / "flows.json").read_text())
    assert flows == [], (
        "docs/flows.json is non-empty but no @flow_step annotation exists in "
        "stapel_translate — investigate before assuming [] is still correct"
    )


def _all_refs(obj) -> set:
    return set(re.findall(r'"#/components/schemas/([^"]+)"', json.dumps(obj)))


def test_schema_refs_are_self_contained():
    schema = json.loads((DOCS / "schema.json").read_text())
    comps = schema.get("components", {}).get("schemas", {})
    seen: set = set()
    stack = list(_all_refs(schema["paths"]))
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in comps:
            stack.extend(_all_refs(comps[name]))
    dangling = seen - set(comps)
    assert not dangling, f"dangling $ref(s) with no component definition: {dangling}"


#: Operations the emitted schema declares with NO security scheme at all.
#: That is the Figma plugin surface and only it: the plugin authenticates with
#: its own ``FigmaApiKey`` header, a separate channel drf-spectacular cannot
#: see, not an open one. Everything else carries ``JWTCookieAuth``.
#:
#: The set is asserted whole rather than "at least these", so a new endpoint
#: cannot land with no declared auth without somebody naming it here.
#:
#: Honest boundary: this proves what the CONTRACT declares, not who the
#: runtime lets in — several read endpoints below carry the scheme and still
#: answer anonymous callers (``ReadOnlyOrSuperUser``: a UI-string bundle is
#: what an unauthenticated app boots with, so gating it would mean a login
#: page with no words on it). The runtime side is gated by
#: tests/test_public_api.py; the two are different questions.
UNAUTHENTICATED_IN_SCHEMA = {
    "GET /translate/api/v1/figma/auth/",
    "GET /translate/api/v1/figma/translations/",
    "GET /translate/api/v1/figma/translations/{key}/",
    "POST /translate/api/v1/figma/translations/",
    "POST /translate/api/v1/figma/translations/search/",
    "POST /translate/api/v1/figma/translations/sync/",
    "POST /translate/api/v1/figma/translations/remove-ref/",
    "POST /translate/api/v1/figma/translations/screenshot/",
}


def _operations():
    schema = json.loads((DOCS / "schema.json").read_text())
    for path, operations in schema["paths"].items():
        for method, op in operations.items():
            if method in ("get", "put", "post", "patch", "delete"):
                yield f"{method.upper()} {path}", op


def test_the_schemas_unauthenticated_surface_is_exactly_what_is_declared():
    undeclared = {
        name for name, op in _operations()
        if not any("JWTCookieAuth" in entry for entry in (op.get("security") or []))
    }
    assert undeclared == UNAUTHENTICATED_IN_SCHEMA, {
        "newly undeclared": sorted(undeclared - UNAUTHENTICATED_IN_SCHEMA),
        "no longer undeclared": sorted(UNAUTHENTICATED_IN_SCHEMA - undeclared),
    }


def test_content_translation_is_not_anonymous():
    """The one that spends money per call, asserted by name (TR-1).

    Its permission is settings-driven (TEXT_PERMISSIONS), so this pins the
    DEFAULT the wheel ships with: a deployment opens it deliberately.
    """
    ops = dict(_operations())
    op = ops["POST /translate/api/v1/text/"]
    assert any("JWTCookieAuth" in entry for entry in (op.get("security") or []))


def test_capabilities_operations_total_matches_the_schema():
    doc = json.loads((DOCS / "capabilities.json").read_text())
    assert doc["operations_total"] == len(dict(_operations()))


def test_capabilities_envelope():
    import tomllib

    doc = json.loads((DOCS / "capabilities.json").read_text())
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert doc["module"] == pyproject["project"]["name"]
    assert doc["version"] == pyproject["project"]["version"]
    assert doc["provides"]
    assert doc["extension_points"]
    assert doc["requires"]


def test_llms_txt_budget_matches_the_makefile():
    """Two places name the budget, so one test makes them one number.

    A drift gate that regenerates under a different ceiling than `make
    contract` uses is a gate that passes on an artifact nobody can reproduce.
    """
    makefile = (REPO / "Makefile").read_text()
    assert f"LLMS_TXT_BUDGET ?= {LLMS_TXT_BUDGET}" in makefile
    assert "--budget $(LLMS_TXT_BUDGET)" in makefile
    assert re.search(r"--budget (?!\$\(LLMS_TXT_BUDGET\))", makefile) is None


# --- README.md — the sixth artifact (tracker #257) ---------------------------
#
# README.md is assembled by ``stapel_tools.readme`` from docs/readme.md (the
# human half: what this module is and how to think about it) plus the contract
# documents above (badges, version, surface counts, doc links). Everything a
# hand-written README used to restate — and therefore used to get wrong one
# release later — is generated here and gated below.

def test_readme_is_assembled_and_has_no_drift():
    from stapel_tools.readme import load_inputs, render, static_languages

    inputs = load_inputs(REPO)
    languages = static_languages(REPO)
    assert languages == ["en"], "expected exactly the English static body docs/readme.md"
    committed = (REPO / "README.md").read_text()
    assert committed == render(REPO, inputs, "en", languages), (
        "README.md drifted — run `make contract` and commit README.md "
        "(edit prose in docs/readme.md, never README.md itself)"
    )


def test_readme_version_matches_the_package():
    """The #226 gate, at the point where the number is published.

    A capabilities.json whose version lags pyproject.toml is exactly the
    defect tracked as #226; the generator refuses to render around it, so
    this test fails loudly rather than shipping a README stating a version
    the wheel does not have.
    """
    import tomllib

    from stapel_tools.readme import load_inputs, resolve_version

    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert resolve_version(load_inputs(REPO)) == pyproject["project"]["version"]
