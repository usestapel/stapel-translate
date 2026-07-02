# Changelog

## 0.2.0 (unreleased)

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
