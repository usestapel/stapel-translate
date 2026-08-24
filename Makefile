# stapel-translate — contract emission + drift gate (contract-pipeline.md §2-3).
#
# This module emits its OWN contract triad (schema.json + flows.json +
# errors.json) from a single-module {translate + core} Django instance mounted
# at the canonical /translate/api/v1/ prefix (see _codegen.py /
# _codegen_settings.py / codegen_urls.py). Before that harness existed
# (BACKEND-GAPS X-1/TR-2) the only way to get this module's OpenAPI was to
# filter stapel-example-monolith's unified schema — which made the contract a
# property of a *different* repo's install list, and left a `gen:api` pair
# with nothing to generate from when the module was mounted anywhere else.
#
# PYTHON must have the module + its deps importable (the workspace venv, or a
# CI venv) and be a 3.12 interpreter: drf-spectacular renders component
# descriptions differently across minors, and a contract emitted on the wrong
# one produces false diffs forever.
PYTHON ?= python3

# The llms.txt budget, raised from the generator's default 4000. The measured
# document is ~5390 tokens and the bulk of it is the 28-entry usage surface
# (2980) plus the 48-key error catalogue (630) plus 25 operations (550) — all
# three of which only became visible to the generator when this module started
# emitting its own triad, so the growth is contract that was previously
# missing, not padding. Raise the ceiling deliberately; do NOT shorten the
# `intent` lines in docs/capabilities.meta.json to fit, because a trimmed
# context file reads exactly like a complete one at the point of use.
#
# tests/test_contract.py asserts this number matches the one it emits with:
# a drift gate that regenerates under a different ceiling than `make contract`
# uses is a gate that passes on an artifact nobody can reproduce.
LLMS_TXT_BUDGET ?= 6000

.PHONY: contract contract-check migration-lint lint test

# docs/capabilities.json is otherwise HAND-AUTHORED here (git log: "docs:
# author capabilities.json for the stapel-catalog sweep") — provides/axes/
# extension_points/requires stay curated prose, never regenerated.
#
# What IS derived: the triad above, plus the `surface` section — the symbols a
# product is meant to CALL (discoverability-design.md §1.2), AST-derived from
# the roots in docs/capabilities.meta.json; a selected export with no curated
# intent line fails `contract` naming the symbol. `--patch` touches only
# module/version and `surface`, leaving the rest of the document verbatim.
#
# Then docs/llms.txt, the fifth contract artifact (stapel_tools.llms_txt),
# rendered from the freshly emitted triad PLUS the patched capabilities.json.
#
# Then assemble README.md (stapel_tools.readme) from docs/readme.md — the
# human half, the only file a person edits — plus the artifacts above. The
# badge row, the version, the surface counts and every doc link are generated,
# so they cannot lag a release the way a hand-written README always has.
contract:
	$(PYTHON) -m stapel_translate._codegen --out docs
	$(PYTHON) -m stapel_tools.surface . --patch
	$(PYTHON) -m stapel_tools.llms_txt . --out docs --budget $(LLMS_TXT_BUDGET)
	$(PYTHON) -m stapel_tools.readme .

# Drift gate. `stapel_tools.surface . --patch --check` runs against the real
# repo (it AST-scans the source files named by surface_roots, so it cannot run
# against a docs/-only temp dir) and compares the freshly patched
# capabilities.json to the committed one in memory, byte for byte. The triad
# + llms.txt regenerate into a temp dir and diff there; llms.txt is rendered
# against the (already checked) committed capabilities.json, copied in
# verbatim for that render.
contract-check:
	@$(PYTHON) -m stapel_tools.surface . --patch --check || exit 1; \
	tmp=$$(mktemp -d); \
	mkdir -p "$$tmp/docs"; \
	$(PYTHON) -m stapel_translate._codegen --out "$$tmp/docs" || { rm -rf "$$tmp"; exit 1; }; \
	cp docs/capabilities.json "$$tmp/docs/capabilities.json"; \
	$(PYTHON) -m stapel_tools.llms_txt "$$tmp" --out "$$tmp/docs" --budget $(LLMS_TXT_BUDGET) || { rm -rf "$$tmp"; exit 1; }; \
	rc=0; \
	for f in schema.json flows.json errors.json llms.txt; do \
		if ! cmp -s "docs/$$f" "$$tmp/docs/$$f"; then \
			echo "DRIFT: docs/$$f is stale — run 'make contract' and commit it"; \
			diff "docs/$$f" "$$tmp/docs/$$f" | head -20; rc=1; \
		fi; \
	done; \
	rm -rf "$$tmp"; \
	$(PYTHON) -m stapel_tools.readme . --check || rc=1; \
	if [ $$rc -eq 0 ]; then echo "contract-check: docs/{capabilities,schema,flows,errors,llms.txt} + README.md up to date"; fi; \
	exit $$rc

# Expand/contract gate for Django migrations (release-management.md §3;
# stapel_tools.migration_lint). Requires stapel-tools importable (the
# workspace venv, or `pip install stapel-tools` once published).
migration-lint:
	$(PYTHON) -m stapel_tools.migration_lint . --strict

lint:
	ruff check . --select E,F,W --ignore E501

test:
	$(PYTHON) -m pytest tests/ -q
