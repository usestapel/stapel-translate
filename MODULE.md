# stapel-translate — MODULE.md

Agent-facing map of this module: what it provides, its fork-free extension
points, and anti-patterns. Use it to classify a desired change as an
**app-layer override via an extension point** vs an **upstream contribution**
(see `docs/stdlib-contribution-pipeline.md` and system-design §8.6 in the
Stapel docs). Stapel modules never import each other; everything below is
customizable **without forking** this repository.

- Package: `stapel-translate` (PyPI), Django app `stapel_translate`, app label `translate`.
- Depends on `stapel_core` only (comm bus, `AppSettings`, `RevisionMixin`, GDPR registry, DRF helpers).

## What this module provides

| Surface | Contents |
|---|---|
| Models | `TranslationEntry` (unique `key`, `source`, `comment`, `refs`, soft-delete via `RevisionMixin.deleted`), `TranslationValue` (row-per-language: `entry` FK, `language`, `value`, `verified`; unique on `(entry, language)`), `TranslationHistory`, `AuthorizedTranslator`, `FigmaApiKey` (hashed keys) |
| Comm Function | `translate.resolve` — the main surface other modules call (schema: `schemas/functions/translate.resolve.json`) |
| Comm task | `translate.autofill` — LLM autofill of missing values (`tasks.py`) |
| Emits | `translations.changed` `{language, keys_changed}` (schema: `schemas/emits/translations.changed.json`), emitted from `TranslationValue.save()` when a value changes |
| Consumes | `user.deleted` → GDPR erasure (`actions.py`; provider registered in `TranslateConfig.ready()`); `user.merged` → declared **no-op** — nothing here is keyed by a user id (the two person-shaped columns, `AuthorizedTranslator.email` and `TranslationHistory.author_email`, are addressed by email, which the payload does not carry) |
| HTTP API | `translate/api/v1/` (entries CRUD, per-language data + revision sync, `POST text/` content translation), `translate/api/v1/dashboard/`, `translate/api/v1/figma/`, `translate/admin/dashboard/` staff HTML pages (`urls.py`) |
| Management commands | `collect_translations`, `dump_translations`, `load_builtin_translations`, `autofill_translations`, `translation_backlog` |
| Fixtures | `fixtures/builtin/{lang}.json` — curated translations for Stapel's own keys, loaded with `source="stapel:builtin"` |
| Error keys | `errors.py` registers six `error.*.translate.*` codes (the `POST text/` refusals) with `ru`/`es` catalogs in `translations/` — this module is the fleet's error-key *collector*, which never stopped it from being a producer |
| Contract artifacts | `docs/{schema,flows,errors,capabilities}.json` + `docs/llms.txt`, emitted by `make contract` from a single-module `{translate + core}` instance (`_codegen.py`) and gated against drift by `tests/test_contract.py` |

Public API (`__all__`, lazily exported from `stapel_translate/__init__.py`):
`translate_settings`, `SUPPORTED_LANGUAGES`, `LANGUAGE_NAMES`,
`get_supported_languages`, `get_language_names`, `get_default_language`,
`emit_translations_changed`, `TRANSLATIONS_CHANGED`, `get_cache_key`,
`register_collector`, `autofill_missing`, `get_llm_provider`.
Anything not exported there is internal.

## Extension points (fork-free)

### Settings — `STAPEL_TRANSLATE` namespace (`conf.py`)

`translate_settings = AppSettings("STAPEL_TRANSLATE", ...)`. Resolution order
per key: `settings.STAPEL_TRANSLATE[key]` → flat Django setting of the same
name → environment variable → default.

| Key | Default | Notes |
|---|---|---|
| `LANGUAGES` | `DEFAULT_LANGUAGES` (20 codes, `en`…`he`) | List of codes; Django-style `(code, name)` tuples accepted (codes extracted); Django's untouched global `LANGUAGES` default is ignored |
| `DEFAULT_LANGUAGE` | `"en"` | Source/fallback language for `translate.resolve` and autofill |
| `LANGUAGE_NAMES` | `DEFAULT_LANGUAGE_NAMES` | `{code: display name}`; merged over the builtin names |
| `LLM_PROVIDER` | `"stapel_translate.providers.AgentProvider"` | **Dotted-path seam.** Resolved with `import_string` in `get_llm_provider()` (a class object is also accepted). Contract: class with `translate(key, english_text, target_language, context) -> str`; **optionally** `complete(prompt) -> str`, which unlocks one-call batch content translation (see "Content translation" below). Subclass `providers.BaseTranslationProvider` to reuse prompt building; raise `TranslationProviderError` on failure. Builtin alternatives: `CommAgentProvider` (same agent facade via the `llm.complete` comm Function — in-process in a monolith, NATS in microservices), `OpenAICompatibleProvider` |
| `TEXT_PERMISSIONS` | `["stapel_core.django.api.permissions.IsNotAnonymousUser"]` | **Permission seam** of `POST translate/api/v1/text/` — dotted DRF permission paths, **all** must pass, resolved per request. The default refuses anonymous callers because every cache miss spends real money; a public storefront opens it (`AllowAny`, and then `TEXT_ANON_THROTTLE` is the only brake), a paid product tightens it to its own plan gate. Setting `permission_classes` on a view subclass still wins — this is the default, not a ceiling |
| `TEXT_THROTTLE` | `"30/min"` | DRF rate for `POST text/` (`ScopedRateThrottle`, scope `translate_text`). A library cannot own the project-wide `DEFAULT_THROTTLE_RATES`, so the rate is read from this namespace |
| `TEXT_ANON_THROTTLE` | `"10/min"` | Rate for a caller with no identity. Dormant under the default permission; the only brake once `TEXT_PERMISSIONS` is opened |
| `TEXT_MAX_CHARS` | `5000` | Length ceiling **per text**. Above it: `400 error.400.translate.text_too_long` with `{max_chars}` — its own code, so a client can offer to trim instead of retrying |
| `TEXT_BATCH_MAX_ITEMS` | `50` | Most texts one `{"texts": [...]}` call may carry → `error.400.translate.batch_too_large` |
| `TEXT_BATCH_MAX_CHARS` | `20000` | Combined length of a batch → `error.400.translate.batch_too_long` |
| `TEXT_CACHE_TTL` | `2592000` (30 days) | How long a translation is remembered in the Django cache, keyed by a digest of (source, target, context hint, text). `0` disables caching — a cost decision, not a correctness one |
| `LLM_OPENAI_BASE_URL` | `"https://api.openai.com/v1"` | For `OpenAICompatibleProvider` |
| `LLM_OPENAI_API_KEY` | `""` | For `OpenAICompatibleProvider` |
| `LLM_OPENAI_MODEL` | `"gpt-4o-mini"` | For `OpenAICompatibleProvider` |
| `AGENT_SERVICE_URL` | `"http://stapel-agent:3000/agent"` | stapel-agent base URL for `AgentProvider` and the dashboard/admin LLM-help calls (env var of the same name keeps working via the AppSettings fallback; previously a raw `os.getenv` at import time) |
| `AGENT_MODEL_SIZE` | `"medium"` | Model size sent to the agent (`small`/`medium`/`large`) |
| `AGENT_PROVIDER` | `""` | Agent-side provider name; empty lets the agent's `DEFAULT_PROVIDER` decide (previously hardcoded `"claude-code"`) |
| `NOTIFICATIONS_URL` | `"http://stapel-notifications:8000"` | notifications service base URL for the notification-keys collector (previously a raw `os.getenv`) |
| `NOTIFICATION_KEYS_PATHS` | `["/notifications/api/v1/notification-keys/", "/notifications/api/notification-keys/"]` | Candidate mount points of the notification-keys endpoint, **newest first**. The collector tries them in order and keeps the one that reaches the view; a 404 from Django's URL resolver (HTML, not JSON) is a path skew, never "no keys" |
| `SERVICE_URL_TEMPLATE` | `"http://stapel-{prefix}:8000"` | Base URL of a sibling service by URL prefix — deploy config for the error-keys fan-out |
| `ERROR_KEYS_PATHS` | `["/{prefix}/api/v1/error-keys/", "/{prefix}/api/error-keys/"]` | Candidate mount points of a service's error-keys endpoint, newest first (same discovery rule) |
| `FIGMA_URL_ALLOWED_HOSTS` | `["figma.com"]` | Hosts a `figma_url` ref may point at (subdomains included, HTTPS only). Enforced at every Figma write endpoint by `security.validate_figma_url`; a ref outside the list is a `400`. Widen it if your design tool is fronted by your own domain |
| `SCREENSHOT_MAX_BYTES` | `5 * 1024 * 1024` | Hard cap on an uploaded screenshot, checked against the *encoded* string first and the decoded bytes second |
| `SCREENSHOT_MAX_PIXELS` | `40_000_000` | Raster cap, read from the image header before any pixel buffer is allocated. Needs the `images` extra (Pillow) |
| `SCREENSHOT_MAX_DIMENSION` | `20_000` | Per-side cap, same header-only check |
| `SCREENSHOT_ALLOWED_FORMATS` | `["png", "jpeg", "webp", "gif"]` | Sniffed from magic bytes, never from a declared content type |
| `SCREENSHOT_UPLOADS_PER_HOUR` | `300` | Per-API-key upload budget (`0` disables). One global plugin key otherwise means an unbounded write channel; past the budget the endpoint answers `429` |
| `SCREENSHOT_STORAGE` | `"stapel_translate_screenshots"` | `STORAGES` alias `TranslationEntry.screenshot` writes to. Define that alias with a private backend and uploads are private with nothing else to set; leave it undefined and writes fall back to `default` (public media on most deployments) with system check `stapel_translate.W001` saying so. Repointing does not move existing files |
| `SCREENSHOT_ALLOW_UNVERIFIED_UPLOADS` | `False` | Accept screenshots on a host with no image decoder. Off, a missing Pillow refuses the upload — the pixel/dimension caps and the format/signature cross-check cannot run without it, and the `images` extra is optional, so the default install was the fail-open one. Reported as `stapel_translate.W002`/`W003` |
| `PUBLIC_ENTRY_FIELDS` | `["id", "key", "revision", "values"]` | Entry fields the read API serves to a caller that is not staff/superuser. The endpoints answer anonymous requests, so widening this publishes those columns (`comment`, `refs`, `screenshot`, …) to the internet |
| `EMPTY_ALLOWED_LANGUAGES_MEANS_ALL` | `False` | Read an `AuthorizedTranslator` with an empty `allowed_languages` as "may edit every language". Off, empty is an empty scope — the field defaults to `[]`, so the old reading gave every new translator row the whole catalogue |
| `AUTOFILL_MAX_VALUES` | `200` | Hard cap on values filled per autofill run (one LLM call each). A caller's `limit` may ask for fewer, never more; `limit=None` means this ceiling. No `0`-means-unlimited sentinel |
| `INTERNAL_REQUIRE_CALLER` | `True` | Refuse a comm task whose payload names no trusted `caller_service`. A comm call has no session, so the payload carries the authority |
| `INTERNAL_TRUSTED_SERVICES` | `[]` | Service names allowed to invoke this module's comm tasks |
| `DASHBOARD_CSP` | see `conf.py` | Content-Security-Policy for the server-rendered dashboard, as `{directive: value}`. `{nonce}` in a value is replaced with the per-response nonce. `{}` sends no header. The shipped templates carry no inline `on*=` handlers, so the default needs no `unsafe-inline` for scripts — **an overridden template with inline handlers will break under it** |
| `DASHBOARD_CSP_REPORT_ONLY` | `False` | Send the policy as `Content-Security-Policy-Report-Only` instead — for observing violations before enforcing |

### Functions — `translate.resolve` (`functions.py`)

Registered from `TranslateConfig.ready()`. Other modules call it by name via
`stapel_core.comm.call("translate.resolve", payload)` — never by importing
this package.

| Aspect | Contract |
|---|---|
| Payload | `{"keys": [str], "language": str}` — both required, `additionalProperties: false` |
| Returns | `{"values": {key: text}}` |
| Fallback | Value for `(key, language)`, else the `DEFAULT_LANGUAGE` value |
| Missing keys | **Omitted** from `values` — never returned as `null`; callers must handle absence |
| Soft-deleted | Entries with `deleted=True` are never resolved |

Related comm surfaces: `start("translate.autofill", {"caller_service": "...",
"languages": [...], "keys": [...], "limit": N})` — `caller_service` must be listed
in `INTERNAL_TRUSTED_SERVICES` while `INTERNAL_REQUIRE_CALLER` is on, the run is
capped at `AUTOFILL_MAX_VALUES`, and results are stored `verified=False`. Plus the
`translations.changed` event for cache invalidation in consumers.

### Content translation — `POST translate/api/v1/text/` (`text.py`, `views.py`)

The other half of this module. Everything above translates catalogued UI-string
**keys**; a listing description has no key and never will, so a viewer who
wants to read it in their own language needs text in / text out. Same
`LLM_PROVIDER` seam, so a deployment configures one provider and both halves
follow it.

| Aspect | Contract |
|---|---|
| Request | `{"text": str}` **or** `{"texts": [str]}` (exactly one), plus `target_lang` (required), `source_lang` (optional, defaults to `DEFAULT_LANGUAGE`), `context` (optional free-text domain hint) |
| Response | `{"texts": [str], "text": str, "source_language": str, "target_language": str, "provider": str, "cached": bool}` — `text` is `texts[0]`, the single-text form's answer; `cached` is true only when **nothing** reached the provider |
| Guard | `TEXT_PERMISSIONS` (settings-driven, per request), throttle scope `translate_text` |
| Bounds | `TEXT_MAX_CHARS` / `TEXT_BATCH_MAX_ITEMS` / `TEXT_BATCH_MAX_CHARS`, each with its own error code |
| Refusals | `error.400.translate.{text_required,text_too_long,batch_too_large,batch_too_long,unsupported_language}`, `error.502.translate.provider_unavailable`. The provider's own message never reaches the caller — it can carry an upstream URL or key fragment — and goes to the log instead |
| Cache | Django cache, `TEXT_CACHE_TTL` seconds, keyed by a digest of (source, target, hint, text). A partially cached batch asks the provider only for the misses |
| Same language in and out | Answered from the input, no provider call, `cached: true` — a translate button whose target happens to be the source must not bill anybody |

**Batching.** A provider that implements `complete(prompt) -> str` gets the
whole batch in **one** upstream call: the content prompt asks for a JSON array
and `providers.parse_content_batch` validates the answer (parses, is a list,
exactly the expected length, every item a non-empty string) before anything is
zipped back onto the inputs — a misaligned array would hand a listing another
listing's description. A malformed answer falls back to one call per text; that
costs more, it is never wrong. A provider implementing only the historical
`translate(...)` contract keeps working unchanged, one call per string.

Call it from Python with `text.translate_texts(...)`, which applies the bounds,
the language validation and the cache. `get_llm_provider().translate(...)` is
the UI-string-**key** contract and applies none of them.

### Adding / overriding translations

Modules never import each other, so keys enter this module through data
channels, not imports:

| Channel | Mechanism | `source` value |
|---|---|---|
| Error keys of any Stapel service | Service exposes `GET /{prefix}/api/v1/error-keys/` (subclass `stapel_core.django.api.errors.ErrorKeysView`, override `get_service_errors()`, **mount it in `urls_v1.py`**); `error_collector.py` polls all services, trying `ERROR_KEYS_PATHS` in order | `backend:errors` |
| Notification templates | notifications service exposes `GET /notifications/api/v1/notification-keys/` (`{key: english_default}`); `notification_collector.py` polls it, trying `NOTIFICATION_KEYS_PATHS` in order | `backend:notifications` |
| Project-specific keys | `register_collector("name", callable_or_dotted_path)` (`collectors.py`) — a collector is a zero-arg callable returning a stats dict; run by `collect_translations` and the dashboard "Collect keys" button | your choice |
| Curated fixtures | `fixtures/builtin/{lang}.json` + `load_builtin_translations` — idempotent upsert, `verified=True`, **user edits always win** (`--force` overwrites only `source="stapel:builtin"` entries) | `stapel:builtin` |
| Manual / bulk | Dashboard editing, export/import, entries API | — |

Collectors follow one safety rule: set `en` only if empty — never overwrite
manual edits; soft-deleted entries are reactivated by collectors (the key is
live again) but respected by the fixture loader.

**Fixtures workflow (`dump_translations`)** — DB → repo files, the inverse of
`load_builtin_translations`:

```
manage.py dump_translations --out fixtures/builtin \
    [--source backend:notifications] [--languages en,de] [--verified-only]
```

Output is **byte-stable**: one JSON file per language, `{key: text}` with
sorted keys, 2-space indent, `ensure_ascii=False`, trailing newline — two
consecutive dumps are byte-identical, so repo diffs are reviewable.
Soft-deleted entries and empty values are never dumped; a language with no
values gets no file.

### Swappable models

None. No model here is swappable (no `Meta.swappable`, no
`get_*_model()` indirection); `TranslationEntry`/`TranslationValue` are
concrete. Schema-level needs (new columns, new constraints) are upstream
contributions. App-layer alternatives that do NOT require model changes:
extra metadata via new `source` values and collectors, behavior via the
serializer seams and `LLM_PROVIDER`, side effects via the
`translations.changed` event.

### Serializer seams

`mixins.SerializerSeamMixin`: views declare `request_serializer_class` /
`response_serializer_class` (or purpose-prefixed variants such as
`list_response_serializer_class`, `upsert_response_serializer_class` on
`FigmaTranslationsView`) and instantiate serializers only through the
matching `get_*_serializer_class()` getters. To change a response shape:
subclass the view, override the single attribute (or getter), and route your
URL to the subclass — no view logic is copied. Proven by
`tests/test_serializer_seams.py`. The DRF `TranslationEntryViewSet` uses the
standard `serializer_class` attribute the same way.

### Signals / events

No custom Django signals. Cross-module reactivity uses the comm bus:
subscribe to `translations.changed` (constant `TRANSLATIONS_CHANGED`) with
`stapel_core.comm.on_action`. Per-entry cache uses key
`get_cache_key(key)` = `"translation:{key}"` and is refreshed on every
entry/value save. `AppSettings` invalidates on Django's `setting_changed`
(tests can use `override_settings`).

### Admin categories (`stapel_core.access`, admin-suite AS-5)

`TranslationHistory` is decorated `@access.ops` (append-only audit log — the
admin already forbade add/change; `StapelModelAdmin` now also makes delete
uniformly forbidden, including for a superuser — the mandate's A5 lets a
superuser through the backend regardless of category, so this admin-layer
enforcement is the actual gate; the model's own hand-rolled
`has_{add,change,delete}_permission` overrides were dropped in favor of it).

`FigmaApiKey` is decorated `@access.secret` (hashed API-key carrier for the
Figma plugin — superuser-only, listed by name in `docs/admin-suite.md` §1.1
as the canonical `secret` example) and its `ModelAdmin` subclasses
`stapel_core.django.admin.base.StapelModelAdmin`, pinning
`secret_fields = ("key_hash",)`. `prefix` (the 8-char lookup fragment) is
deliberately NOT masked — the model's own docstring calls it safe to display,
unlike the full key, which is never persisted at all (only its SHA-256 hash
is stored; the plaintext is shown exactly once via `plaintext_key` right
after generation).

`TranslationEntry`, `TranslationValue`, and `AuthorizedTranslator` stay
undecorated (business, implicit `@access.standard`): they are the content
staff actually work with day to day (translation strings, per-language
values, and — mirroring GDPR's `LegalHold` precedent — the roster of who is
allowed to edit them, a real staff workflow, not a secret).

## Anti-patterns

- **Hardcoding user-facing strings in other modules or app code.** Register a
  key (error-keys endpoint, notification-keys endpoint, or a project
  collector) and resolve it at render time via `translate.resolve`.
- **Importing `stapel_translate` from another Stapel module.** Modules never
  import each other — call `stapel_core.comm.call("translate.resolve", ...)`
  by name; payloads are validated against `schemas/functions/translate.resolve.json`.
- **Hand-editing dumped fixture files in a way that breaks byte-stability**
  (unsorted keys, ASCII-escaped unicode, different indent, missing trailing
  newline). The next `dump_translations` run will rewrite the file and your
  diff becomes noise. Change values in the DB (dashboard/API), then re-dump.
- **Writing `TranslationValue` rows around the model layer**
  (`bulk_create`/`bulk_update`/raw SQL). That skips `TranslationValue.save()`,
  which does the revision bump, shared-cache refresh, and
  `translations.changed` emission — clients syncing by revision silently miss
  the change. Use `entry.set_value(lang, value, verified=...)`.
- **Overwriting existing values from collectors or loaders.** The module
  invariant is "set `en` only if empty; user edits win". A collector that
  overwrites manual edits breaks the review workflow.
- **Treating a missing key in `translate.resolve` output as an error, or
  expecting `null`.** Missing/empty keys are omitted by contract; the caller
  falls back (e.g. to the key itself).
- **Hard-deleting entries.** Removal is soft (`deleted=True`); resolve, dump
  and the fixture loader all respect it. Hard deletes break revision-based
  client sync.
- **Forking a view to change its serialization**, when subclassing it and
  overriding one `*_serializer_class` attribute does the same.
- **Reading config with `getattr(settings, ...)`** instead of
  `translate_settings.<KEY>` — you lose the namespace/flat/env/default
  resolution and test-time cache invalidation.

## App-layer override vs upstream contribution

Rule of thumb: **if a documented seam absorbs the change, it is app-layer; if
you need to edit files in this repository, it is upstream.**

| Desired change | Classification |
|---|---|
| Different languages, default language, display names | App layer — `STAPEL_TRANSLATE` settings |
| Different LLM/translation backend for autofill | App layer — `LLM_PROVIDER` dotted path |
| Project-specific translation keys | App layer — `register_collector` + `collect_translations` |
| Ship/override translation values | App layer — fixtures + `load_builtin_translations` / dashboard / import |
| Different API response shape | App layer — subclass view, override serializer seam, remap URL |
| React to translation changes | App layer — subscribe to `translations.changed` |
| New field on `TranslationEntry`/`TranslationValue`, new migration | Upstream contribution |
| Change `translate.resolve` semantics (fallback chain, payload schema) | Upstream — it is a published cross-module contract |
| New builtin collector, command, or provider useful to any project | Upstream contribution |
| Bug in existing behavior | Upstream contribution (fix flows through the contribution pipeline; consume the beta from the artifact channel until released) |
| Client-specific behavior upstream won't take | App layer — keep it as an override at the seams above |
