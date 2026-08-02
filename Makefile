PYTHON ?= python3

# docs/capabilities.json is HAND-AUTHORED here (git log: "docs: author
# capabilities.json for the stapel-catalog sweep") — this module has no
# _capabilities.py / _codegen.py codegen pipeline yet, so there is nothing to
# regenerate it from. DO NOT point contract/contract-check at it, and do not
# attempt to regenerate it — the curated content would be lost.
#
# These targets manage ONLY docs/llms.txt (the fifth contract artifact,
# badge-canon §3), rendered from the curated capabilities.json by
# stapel_tools.llms_txt.
.PHONY: contract contract-check migration-lint

contract:
	$(PYTHON) -m stapel_tools.llms_txt .

contract-check:
	$(PYTHON) -m stapel_tools.llms_txt . --check

# Expand/contract gate for Django migrations (release-management.md §3;
# stapel_tools.migration_lint). Requires stapel-tools importable (the
# workspace venv, or `pip install stapel-tools` once published).
migration-lint:
	$(PYTHON) -m stapel_tools.migration_lint . --strict
