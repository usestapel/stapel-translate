"""docs/llms.txt drift gate — the fifth contract artifact (badge-canon §3).

stapel-translate has no per-module ``_codegen.py``/``_capabilities.py``
pipeline yet: ``docs/capabilities.json`` here is HAND-AUTHORED (see the
"docs: author capabilities.json for the stapel-catalog sweep" commit), not
emitted. There is therefore no triad/capabilities drift gate to run in this
file — that arrives with the codegen pipeline, not before it.

What this file DOES gate is ``docs/llms.txt``, rendered from that curated
capabilities.json by ``stapel_tools.llms_txt``. It is a pure function of the
committed ``docs/*.json`` files, so the same regenerate-and-diff discipline
applies without needing Django, a codegen harness or a subprocess per se —
one is used anyway (mirrors every other module's ``make contract-check``, and
keeps this test honest about running exactly what the Makefile runs).

Regenerate after any edit to ``docs/capabilities.json``:

    make contract        # or: python -m stapel_tools.llms_txt .
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"


def _emit(out_dir: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "stapel_tools.llms_txt", str(REPO), "--out", str(out_dir)],
        check=True,
        capture_output=True,
    )


def test_llms_txt_committed():
    assert (DOCS / "llms.txt").is_file(), "missing docs/llms.txt — run `make contract`"


def test_llms_txt_has_no_drift(tmp_path):
    """Regenerate into a temp dir; the committed file must match byte-for-byte."""
    _emit(tmp_path)
    committed = (DOCS / "llms.txt").read_bytes()
    regenerated = (tmp_path / "llms.txt").read_bytes()
    assert committed == regenerated, (
        "docs/llms.txt drifted — run `make contract` and commit docs/llms.txt"
    )


def test_llms_txt_emission_is_deterministic(tmp_path):
    """Two independent emissions are byte-identical (the drift gate above is
    only meaningful if this holds)."""
    a, b = tmp_path / "a", tmp_path / "b"
    _emit(a)
    _emit(b)
    assert (a / "llms.txt").read_bytes() == (b / "llms.txt").read_bytes()


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
