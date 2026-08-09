PYTHON ?= python3

# docs/capabilities.json is otherwise HAND-AUTHORED here (git log: "docs:
# author capabilities.json for the stapel-catalog sweep") — this module has no
# _capabilities.py / _codegen.py codegen pipeline, so provides/axes/
# extension_points/requires stay curated prose, never regenerated.
#
# What IS derived: the `surface` section — the symbols a product is meant to
# CALL (discoverability-design.md §1.2), plus module/version. AST-derived from
# the roots in docs/capabilities.meta.json; a selected export with no curated
# intent line fails `contract` naming the symbol. `--patch` touches only those
# two things and leaves the rest of the document verbatim.
#
# Then docs/llms.txt, the fifth contract artifact (stapel_tools.llms_txt),
# rendered straight from the docs/capabilities.json the step above produces.
#
# Then assemble README.md (stapel_tools.readme) from docs/readme.md — the
# human half, the only file a person edits — plus the artifacts above. The
# badge row, the version, the surface counts and every doc link are generated,
# so they cannot lag a release the way a hand-written README always has.
.PHONY: contract contract-check migration-lint

contract:
	$(PYTHON) -m stapel_tools.surface . --patch
	$(PYTHON) -m stapel_tools.llms_txt .
	$(PYTHON) -m stapel_tools.readme .

# Drift gate: surface --check compares the derivable parts of
# docs/capabilities.json; llms_txt's own --check mode compares a fresh render
# (from the committed docs/capabilities.json) against the committed
# docs/llms.txt.
contract-check:
	$(PYTHON) -m stapel_tools.surface . --patch --check
	$(PYTHON) -m stapel_tools.llms_txt . --check
	$(PYTHON) -m stapel_tools.readme . --check

# Expand/contract gate for Django migrations (release-management.md §3;
# stapel_tools.migration_lint). Requires stapel-tools importable (the
# workspace venv, or `pip install stapel-tools` once published).
migration-lint:
	$(PYTHON) -m stapel_tools.migration_lint . --strict
