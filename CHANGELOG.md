# Changelog

## [Unreleased]

### Changed
- `apps.py` now registers the Translator Dashboard nav link with
  `service_dashboard=True` — the explicit admin-suite AS-4 arbitration flag
  (stapel-core follow-up) that tells `current_dashboard_url()` this link
  *is* the translate service's dashboard, instead of relying on the
  `URL_PREFIX`-matching heuristic. Requires `stapel-core`'s
  `register_nav_link(..., service_dashboard=...)` parameter.
- Tests: `tests/test_nav_integration.py` asserts the registered link carries
  `service_dashboard is True`.

## 0.4.6 — 2026-07-06

### Changed — cross-service navigation from the registry (admin-suite AS-4)
- The dashboard's "Services" dropdown (`templates/dashboard/base.html`) no
  longer hardcodes 12 root-relative service links (6 Admin + 6 API). It now
  renders from the `STAPEL_SERVICES` / `STAPEL_ADMIN["NAV_LINKS"]` registries
  via the core `stapel_services` context processor — service list, Tools,
  Monitoring and Dashboards sections all come from deploy config.
- The staff login link (`templates/dashboard/login.html`) drops the hardcoded
  `/auth/admin/login` and uses the mount-derived `stapel_admin_login_url`
  (survives sub-path deployments).
- `apps.py` registers the Translator Dashboard as a nav link
  (`register_nav_link("translate.dashboard", section="dashboards", …)`) so it
  appears in the admin/Swagger service menu without the framework hardcoding
  it; the project can re-title/relocate/remove it via
  `STAPEL_ADMIN["NAV_LINKS"]`.
- `error_collector.py` reads the service list from
  `stapel_core.django.nav.get_services()` instead of the removed
  `stapel_core.core.config.STAPEL_SERVICES` hardcode.
- Tests: `tests/test_nav_integration.py`; collector tests patch
  `get_services` instead of the removed symbol.

## 0.4.5 — 2026-07-06

### Fixed
- `TranslationEntryAdmin.set_translation_lang`: the no-referer fallback was a
  hardcoded `"/admin/"` — 404s once the project is mounted under a prefix.
  Now derives the deployment-canonical admin index via
  `stapel_core.django.mounts.admin_index_url()` (house convention: house
  MODULE.md → "URL mounting").


## 0.4.4 — 2026-07-06

### Changed
- Pinned `stapel-core` to the `>=0.8,<0.9` window (library-standard §7.1: one
  minor window; floor `0.8.0` is published on PyPI — no pin into the void).
- CI: added the release-track job (library-standard §7.4) — installs the package
  the way an end user does (`pip install .`, dependencies resolved from PyPI
  strictly by the declared pins, no git-main core, no editable siblings), asserts
  `stapel-core` resolves inside the `0.8` window, and runs an import smoke.
  Advisory (continue-on-error) until the whole stapel graph is on PyPI; becomes
  the blocking precondition for a `vX.Y.Z` tag once it is.


## 0.4.3 — 2026-07-06

### Packaging
- Tests excluded from the built wheel/sdist (the `stapel_translate.tests`
  subpackage is no longer listed in `[tool.setuptools] packages`). Added
  `[project.urls]`, completed the trove classifiers (MIT/OSI, Python 3.13,
  `Typing :: Typed`, OS Independent, `3 :: Only`, Development Status) and a
  `[tool.ruff]` lint section (single source shared with the git hooks/CI).


## 0.4.2 — 2026-07-05

### Fixed
- OpenAPI: request-body serializers for the Figma plugin POST endpoints
  (`translations/`, `search/`, `sync/`, `remove-ref/`, `screenshot/`) —
  drf-spectacular no longer defaults them to a generic free-form object.
  Added explicit request serializers in `figma_serializers.py` and mapped
  real response/error codes (`StapelErrorSerializer` for 4xx). The
  screenshot endpoint takes a base64 PNG string in JSON, documented as such
  (not multipart).
- OpenAPI: type hints on dashboard `SerializerMethodField`s —
  `TranslationListSerializer.get_value` (`-> str`), `get_verified`
  (`-> bool`), and `TranslationDetailSerializer.get_translations`
  (`@extend_schema_field(LanguageTranslationSerializer(many=True))`).


## 0.4.1 — 2026-07-05

### Fixed
- `user_id` in comm schemas typed uuid, was integer — rejected valid
  `user.deleted` events. `schemas/consumes/user.deleted.json` now types
  `user_id` as `{"type": "string", "format": "uuid"}`, matching the
  UUID-pk canonical user and the auth/gdpr producers.


## 0.4.0 — 2026-07-04
### Added
- `CommAgentProvider` — the stapel-agent facade through the `llm.complete`
  comm Function instead of HTTP: in-process in a monolith where
  stapel-agent is installed, over the Function transport (NATS) in
  microservices. Select via `STAPEL_TRANSLATE["LLM_PROVIDER"]`.
- Settings keys `AGENT_SERVICE_URL`, `AGENT_MODEL_SIZE`, `AGENT_PROVIDER`,
  `NOTIFICATIONS_URL` in the `STAPEL_TRANSLATE` namespace. The
  `AGENT_SERVICE_URL`/`NOTIFICATIONS_URL` env vars keep working via the
  AppSettings env fallback, but are now read lazily instead of frozen at
  import; `AGENT_PROVIDER` replaces the previously hardcoded
  `"claude-code"` in agent payloads (empty = the agent's
  `DEFAULT_PROVIDER` decides).
- comm Function `translate.resolve` (`functions.py`, registered from
  `TranslateConfig.ready()`): input `{"keys": [str], "language": str}`,
  output `{"values": {key: text}}`. Resolves `TranslationValue` rows for the
  requested language with fallback to the `DEFAULT_LANGUAGE` value; keys
  with no non-empty value in either language are omitted (never null).
  Soft-deleted entries are never resolved. Contract committed as
  `schemas/functions/translate.resolve.json` (input schema,
  `additionalProperties: false`). `translations.changed` stays a thin
  invalidation event — consumers pull values via `translate.resolve`.
- `manage.py dump_translations --out <dir> [--source backend:notifications]
  [--languages en,de] [--verified-only]` — the inverse of
  `load_builtin_translations`. Writes one JSON file per language
  (`{key: text}`), sorted keys, 2-space indent, `ensure_ascii=False`,
  trailing newline: deterministic, byte-stable output that round-trips with
  `load_builtin_translations`. Skips soft-deleted entries and empty values;
  `--source` may be repeated.

### Removed
- Orphan `schemas/consumes/user.deletion_initiated.json`: translate had no
  handler for it and needs none — `user.deletion_initiated` only starts the
  reversible 30-day grace period (account deactivation happens in the GDPR
  orchestrator), while translate's per-user data (`AuthorizedTranslator`,
  `TranslationHistory.author_email`) is erased/anonymized on the final
  `user.deleted` event, which is already handled in `actions.py` via
  `TranslateGDPRProvider`. Acting at initiation would be irreversible with
  no `deletion_cancelled` consume to undo it.


## 0.3.0 — 2026-07-03

### Added
- LLM autofill pipeline: `autofill.py` + pluggable dotted-path providers,
  consolidated collectors, management commands (collect/backlog/autofill),
  celery tasks, builtin translation fixtures shipped in the wheel.


## 0.2.0 — 2026-07-02

### Changed — row-per-language storage (BREAKING at the ORM level, API-compatible)

- `TranslationEntry` no longer has 20 hardcoded language columns and 20
  `<lang>_verified` booleans. Values now live in the new `TranslationValue`
  model (`entry` FK with `related_name="values"`, `language`, `value`,
  `verified`, unique per `(entry, language)`).
- Migrations `0017`–`0019` create the new table, copy every non-empty column
  (and verified-only flags) into rows, then drop the old columns. The data
  migration is reversible.
- New helpers on `TranslationEntry`: `get_value(lang)`, `get_verified(lang)`,
  `set_value(lang, value=None, verified=None)`, `values_dict()`, and a
  read-only `en` property. Direct attribute writes (`entry.en = ...`) are no
  longer possible — use `set_value`.
- Saving a `TranslationValue` bumps the parent entry's `revision`
  (RevisionMixin semantics, via UPDATE) so revision-based client sync keeps
  working, and refreshes the per-key entry cache.
- HTTP API response shapes are unchanged: `/translate/api/translations/`
  still returns flat `<lang>` / `<lang>_verified` keys, the dashboard and
  Figma endpoints return the same JSON as before, and the fixture
  export/import keeps the legacy flat shape (language fields inlined into
  each entry's `fields`).

### Changed — configurable languages

- Languages are configurable via the `STAPEL_TRANSLATE` settings namespace
  (`stapel_translate.conf.translate_settings`, built on
  `stapel_core.conf.AppSettings`): `LANGUAGES`, `DEFAULT_LANGUAGE`,
  `LANGUAGE_NAMES`. Defaults are the previous 20 hardcoded languages.
- `SUPPORTED_LANGUAGES` and `LANGUAGE_NAMES` remain importable from
  `stapel_translate.models` / `stapel_translate.dashboard_views` (and now
  canonically from `stapel_translate.conf`) but are lazy views over the
  configuration.

### Security — Figma API keys (BREAKING: keys must be re-issued)

- The `FigmaApiKey` UUID primary key is no longer the secret. Keys are now
  `fk_` + 32-byte urlsafe tokens, shown exactly ONCE on creation (Django
  admin message / `plaintext_key` one-time attribute) and stored only as a
  SHA-256 hash plus an 8-char prefix.
- Authentication looks the key up by prefix and compares hashes in constant
  time.
- Migration `0020` WIPES all existing Figma API keys — they were stored in
  plaintext and cannot be hashed retroactively. Re-issue keys in the admin
  after upgrading.

### Changed — events

- `translations.changed` is now emitted through `stapel_core.comm.emit`
  (transactional outbox) instead of publishing directly to the Kafka bus.
- The payload now matches `schemas/emits/translations.changed.json`:
  `{"language": "<code>", "keys_changed": ["key", ...]}` (previously
  `{"key": ..., "values": {...}}`).
- Events are emitted for ANY translation value change (error keys, app/Figma
  strings, manual dashboard edits, LLM applies, imports) — previously only
  `backend:notifications` keys were published.

### Fixed

- Figma translation detail endpoint (`GET /translate/api/figma/translations/<key>/`)
  returned `language`/`verified` computed from the last supported language
  (loop-variable shadowing) instead of the requested one.

### Packaging

- Added `py.typed` marker (PEP 561) and included it in package data.
- Version bumped to 0.2.0.

## 0.1.0

- Initial release.
