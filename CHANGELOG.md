# Changelog

## [Unreleased]

## [0.7.0] — 2026-08-24

### Added — `POST /translate/api/v1/text/`, content translation (BACKEND-GAPS TR-1)

Until now this module could only translate catalogued UI-string **keys**. A
listing description has no key and never will, so the one thing a marketplace
actually asks a translation service for — "show me this in my language" — was
not on the surface at all. The nearest route was `dashboard/llm-help/`, which
needs an existing `translation_id` and `IsAuthorizedTranslator`: a translator
tool, not a reader's button. `@stapel/translate-react` specified
`TranslatedText` / `TranslateButton` against nothing, gated behind a capability
flag that could not be turned on.

Text in, text out, over the same `LLM_PROVIDER` seam the dashboard and autofill
already use, so a deployment configures one provider and both halves follow it:

| Aspect | Contract |
| --- | --- |
| Request | `{"text": str}` **or** `{"texts": [str]}` (exactly one), `target_lang` (required), `source_lang` (optional), `context` (optional domain hint) |
| Response | `{"texts": [str], "text": str, "source_language": str, "target_language": str, "provider": str, "cached": bool}` |
| Guard | `TEXT_PERMISSIONS`, default `IsNotAnonymousUser` |
| Throttle | `ScopedRateThrottle`, scope `translate_text`, `TEXT_THROTTLE` / `TEXT_ANON_THROTTLE` |

Every bound on it exists for one reason: a cache miss spends real money on
somebody's LLM budget.

- **The guard is a seam, not a constant.** `TEXT_PERMISSIONS` is a list of
  dotted DRF permission paths resolved per request (the shape stapel-geo's
  `GEOCODER_PERMISSIONS` uses). A public storefront that wants a translate
  button for logged-out readers sets `AllowAny`; a paid product tightens it to
  its own plan gate. Neither needs a view subclass, and `permission_classes` on
  a subclass still wins — the setting is the default, not a ceiling.
- **Two throttles, not one.** `TEXT_THROTTLE` (`30/min`) and
  `TEXT_ANON_THROTTLE` (`10/min`). The anonymous rate is dormant under the
  default permission and is the *only* brake the moment the endpoint is opened
  — which is exactly when nobody remembers to add one, so it ships now.
- **Ceilings with their own codes.** `TEXT_MAX_CHARS` (5000, per text),
  `TEXT_BATCH_MAX_ITEMS` (50) and `TEXT_BATCH_MAX_CHARS` (20000) each refuse
  with a distinct `error.400.translate.*` code carrying the limit it enforced,
  so a client can offer to trim rather than blindly retry.
- **A batch of short strings in one call.** `{"texts": [...]}` translates a
  screen's worth of UI copy together, which also keeps its tone consistent.
- **A cache, keyed by a digest.** `TEXT_CACHE_TTL` (30 days) over the Django
  cache, keyed by a sha256 of (source, target, context hint, text) — a digest
  because a description contains spaces and memcached rejects those in a key.
  A partially cached batch asks the provider only for the misses; `cached` is
  true only when nothing was fetched.
- **Same language in and out costs nothing.** Answered from the input with no
  provider call: a translate button whose target happens to be the source must
  not bill anybody.

### Added — the generic half of the provider seam: `complete(prompt)`

`BaseTranslationProvider` gains `complete(prompt) -> str`, `translate_text`,
`translate_texts` and `parse_content_batch`. A provider that implements
`complete` translates a whole batch in **one** upstream call: the content
prompt asks for a JSON array and `parse_content_batch` validates the answer —
parses as JSON, is a list, exactly the expected length, every item a non-empty
string — before anything is zipped back onto the inputs. A misaligned array
would hand a listing another listing's description, so a malformed answer falls
back to one call per text; that costs more, it is never wrong.

The three builtin providers implement it (the transport was already there; it
is now split from the prompt). **A third-party provider implementing only the
historical `translate(key, english_text, target_language, context)` contract
keeps working unchanged** — one call per string, exercised by a test.

### Added — this module's own error keys, with `ru`/`es` catalogs (TR-3)

`errors.py` registers six `error.*.translate.*` codes through
`register_service_errors`, and `translations/errors.{ru,es}.json` ship their
translations, seeded from this repo's own builtin corpus. Before this every
refusal in the module was an English literal in `{"error": "..."}` that no
consumer could localize — a defect that reads worse here than anywhere else,
since this is the module that holds everyone else's translations.

The six strings are also in `fixtures/builtin/{lang}.json` for all twenty
default languages (264 → 270 keys), where the whole fleet seeds from.

### Added — the module emits its own contract triad (X-1 / TR-2)

`make contract` now emits `docs/schema.json`, `docs/flows.json` (`[]` — no
`@flow_step` here) and `docs/errors.json` from a single-module
`{translate + core}` Django instance mounted at the canonical
`/translate/api/v1/` prefix (`_codegen.py`, `_codegen_settings.py`,
`codegen_urls.py`), plus `docs/llms.txt` and `README.md`. Until now the only
way to obtain this module's OpenAPI was to filter stapel-example-monolith's
unified schema — which made this repo's contract a property of a *different*
repo's install list, and left a `gen:api` frontend pair with nothing to
generate from wherever the module is mounted on its own.

`tests/test_contract.py` grows from an `llms.txt`-only check into the full
drift gate: determinism, `$ref` closure, canonical-prefix paths, and the
schema's unauthenticated surface asserted as a whole set so a new endpoint
cannot land with no declared auth without somebody naming it.

### Fixed — `docs/capabilities.json` claimed 22 operations; the schema has 25

The number was hand-maintained and stale. It is now derived from the emitted
schema and gated by `test_capabilities_operations_total_matches_the_schema`, so
it cannot drift again.

### Notes

- No migration: the cache is the Django cache, not a table.
- `docs/llms.txt` budget raised 4000 → 6000 deliberately (the Makefile says
  why): the growth is the surface, error and operation sections that only
  became visible once this module started emitting its own triad.
- Known, untouched: the two revision endpoints still return the same number
  (TR-4), and `figma/translations/` collides with `figma/translations/{key}/`
  on `operationId`, which drf-spectacular resolves with a numeral suffix.

## [0.6.1] — 2026-08-14

### Added — the three gdpr error keys the 2026-08-11 security wave introduced

`stapel-gdpr` 0.4.0 registers three new error keys, and no corpus carried a
translation for any of them — `stapel-gdpr` ships no catalogs of its own, so
every consumer that renders a localized error reference (stapel-auth is the
reference case) fell back to the English literal:

| Key | English |
| --- | --- |
| `error.403.gdpr.account_closed` | This account is being erased and can no longer be used. |
| `error.410.gdpr.download_consumed` | Download link was already used. Request a new export. |
| `error.503.gdpr.closure_unavailable` | Account closure is temporarily unavailable. Please retry later. |

All three are now in `fixtures/builtin/{lang}.json` for all 20 default
languages, alongside the seven `gdpr.*` errors already there — same
provenance as the rest of the corpus (`source="stapel:builtin"`,
`verified=True` on load). The builtin catalog goes from 256 to 259 keys.

Strings only: no code, no schema and no migration changed.

## [0.6.0] — 2026-08-14

### Changed — requires stapel-core >= 0.24.0 (was `>=0.15.5`)

The TRANS-06 scope model below has exactly one unrestricted path:
`is_privileged_user` reads `user.is_staff` / `user.is_superuser` and returns
`ALL_LANGUAGES`. Before core 0.24.0, `JWT_CREATE_USERS_FROM_TOKEN` defaulted
to `True`, which materialised unknown users locally **and replaced
`is_staff` / `is_superuser` from the token's claims on every request** — so
"an empty scope grants nothing" was bypassed by any token asserting
`is_staff`, and the whole scope model was decorative. Core 0.24.0 makes the
local database authoritative by default.

`>=0.15.5` remains the API floor (`stapel_core.django.peers` —
`get_with_path_discovery` / `PathResolver` / `PeerRouteUnavailable`, imported
unconditionally by both key collectors); 0.24.0 is the floor this release's
security posture actually rests on.

### Security — BREAKING: `translate.autofill` is bounded and needs a caller

Closes TRANS-07 from the 2026-08-11 audit.

The `translate.autofill` comm task had **no caller identity check at all**
and took `limit=None` to mean unlimited — so any peer on the bus could
walk the whole catalogue times every configured language, one LLM call
each, on someone's budget.

**Both defaults changed.**

1. A call must name a trusted caller:

   ```python
   start("translate.autofill", {"caller_service": "stapel-studio", ...})
   ```

   ```python
   STAPEL_TRANSLATE = {"INTERNAL_TRUSTED_SERVICES": ["stapel-studio"]}
   ```

   The default list is empty, so **every existing caller is refused until
   it is listed**. Restore the old unauthenticated behaviour with
   `INTERNAL_REQUIRE_CALLER = False` (same vocabulary as stapel-docs).

2. `AUTOFILL_MAX_VALUES` (default `200`) caps a single run. A caller's own
   `limit` may ask for fewer, never more; `limit=None` now means the
   ceiling, not "everything". There is deliberately no `0`-means-unlimited
   sentinel — raise the number to raise the bound. The returned stats
   carry the `limit` actually applied.

`manage.py autofill_translations` gained `--caller-service` and refuses up
front with a `CommandError` rather than printing a task id for work that
will be rejected. `--sync` runs inline, where the shell is the authority,
and needs no caller.

### Security — BREAKING: an empty translator language scope now grants nothing

Closes TRANS-06 from the 2026-08-11 audit.

`AuthorizedTranslator.allowed_languages` defaults to `[]`, and an empty
list meant "all languages" — so every translator row created without
languages filled in (the state each one starts in) could edit and verify
the whole catalogue in every language. Empty now means an empty scope.

**Read this before upgrading if you have translator rows with an empty
`allowed_languages`.** Those translators lose dashboard write access until
their languages are named — in the admin, or in bulk:

```python
AuthorizedTranslator.objects.filter(allowed_languages=[]).update(
    allowed_languages=["de", "fr"],
)
```

Check what you have first:

```
AuthorizedTranslator.objects.filter(allowed_languages=[], is_active=True).count()
```

Staff and superusers are unaffected — `is_privileged_user` still takes the
unrestricted path. To restore the old reading while you migrate the rows:

```python
STAPEL_TRANSLATE = {"EMPTY_ALLOWED_LANGUAGES_MEANS_ALL": True}
```

`get_user_allowed_languages` now also returns `[]` (not "all") for an
authenticated user with no translator record at all. The unrestricted
sentinel is exported as `stapel_translate.permissions.ALL_LANGUAGES`;
call sites must keep branching on `is not None` so an empty scope never
collapses back into it. Migration `0022` is help-text only — no column
change, no data movement.

### Security — BREAKING: screenshot uploads need an image decoder

Closes TRANS-05 from the 2026-08-11 audit.

`SCREENSHOT_MAX_PIXELS`, `SCREENSHOT_MAX_DIMENSION` and the
format/signature cross-check are enforced with Pillow, which ships in the
optional `stapel-translate[images]` extra. When it was absent those bounds
were skipped silently (`except ImportError: return`) — so the *default*
install accepted decompression bombs that fit inside `SCREENSHOT_MAX_BYTES`.

**`POST figma/translations/screenshot/` now answers 400 on a host with no
image decoder.** Install the extra wherever the Figma plugin endpoints are
reachable:

```
pip install "stapel-translate[images]"
```

A new `manage.py check` warning (`stapel_translate.W002`) reports the
missing decoder at boot instead of letting it surface as plugin 400s. To
keep accepting uploads without pixel bounds — the previous behaviour —
opt in explicitly:

```python
STAPEL_TRANSLATE = {"SCREENSHOT_ALLOW_UNVERIFIED_UPLOADS": True}
```

That opt-in is itself reported (`stapel_translate.W003`).

### Security — screenshot uploads default to a storage alias of their own

Closes TRANS-04 from the 2026-08-11 audit.

`STAPEL_TRANSLATE["SCREENSHOT_STORAGE"]` defaulted to `"default"` — the
project-wide media alias, normally served publicly — while its own comment
warned that this exposes every uploaded product screen. The default is now
the dedicated alias `"stapel_translate_screenshots"`.

**Nothing breaks on upgrade.** If that alias is not defined in `STORAGES`,
uploads still go to `default` exactly as before; the fallback is explicit
and reported by a new `manage.py check` warning,
`stapel_translate.W001`. To make screenshots private, define the alias —
there is no second setting to remember:

```python
STORAGES = {
    "default": {...},
    "stapel_translate_screenshots": {"BACKEND": "...private bucket..."},
}
```

An alias a deployment names itself and misspells still fails loudly at
boot — only the package's own default alias degrades. **Repointing does
not move already-uploaded files.**

### Security — BREAKING: the read API no longer publishes authoring metadata

Closes TRANS-03 from the 2026-08-11 audit.

`GET /translate/api/v1/translations/` answers anonymous requests
(`ReadOnlyOrSuperUser` passes every SAFE_METHOD), and its serializer used
`fields = '__all__'` — so `comment` (developer notes),
`translator_comment`, `refs` (Figma URLs of unreleased designs),
`screenshot`, `source`, `order` and `llm_translated` were served to
anyone who asked.

**The response shape changed for unprivileged callers.** List and retrieve
now carry `id`, `key`, `revision` and `values` only. Staff and superusers
still receive the full authoring row (a second serializer,
`TranslationEntrySerializer`, selected per request), so the dashboard and
any staff tooling are unaffected.

Restore the old shape for a client that genuinely needs a wider public
surface by naming the columns explicitly:

```python
STAPEL_TRANSLATE = {
    "PUBLIC_ENTRY_FIELDS": ["id", "key", "revision", "values", "order"],
}
```

The default is the narrow list; widening it is the deliberate act. A
column added to `TranslationEntry` in a future release stays off the
public surface until it is named there.

### Security — BREAKING: the Figma plugin surface is now allowlisted and bounded

Closes two P1 findings from the 2026-08-11 audit (TRANS-01, TRANS-02).

**Read this before upgrading if you run the Figma plugin endpoints.** Two
previously-accepted inputs are now rejected:

- `figma_url` on `POST figma/translations/`, `figma/translations/search/`
  and `figma/translations/sync/` must be an **HTTPS URL on an allowed Figma
  host** — anything else is a `400`, including plain `http`, credentials in
  the URL, a non-default port, and every non-http scheme. Widen with
  `STAPEL_TRANSLATE["FIGMA_URL_ALLOWED_HOSTS"]` (default `["figma.com"]`;
  subdomains of each entry are accepted). Removing an already-stored bad ref
  via `figma/translations/remove-ref/` is deliberately *not* validated, so a
  poisoned ref can still be deleted.
- `image` on `POST figma/translations/screenshot/` must decode to a real
  `png`/`jpeg`/`webp`/`gif` within `SCREENSHOT_MAX_BYTES` (default 5 MiB),
  `SCREENSHOT_MAX_PIXELS` (40M) and `SCREENSHOT_MAX_DIMENSION` (20000px).
  The cap is applied to the *encoded* string first, the decoded bytes next,
  then the magic bytes, then the decoded header. Previously any base64-
  decodable blob was written to disk as `.png`. Uploads are also metered per
  API key at `SCREENSHOT_UPLOADS_PER_HOUR` (default 300, `0` disables) and
  answer `429` past the budget.

Also changed on that surface:

- Stored screenshots get a random filename instead of one derived from the
  translation key, which was an enumerable index of every uploaded screen.
- `TranslationEntry.screenshot` now resolves its storage from
  `STAPEL_TRANSLATE["SCREENSHOT_STORAGE"]` (a `STORAGES` alias, default
  `"default"` — no behaviour change until you point it elsewhere). Migration
  `0021` is a field-level `AlterField`: no column change, no data movement.
  **Repointing the alias does not move already-uploaded files.** Install the
  new `stapel-translate[images]` extra (Pillow) wherever these endpoints are
  reachable — without a decoder the byte cap and magic-byte sniff still
  apply, but the pixel/dimension caps cannot.

### Security — the staff dashboard no longer builds DOM from strings

- `templates/dashboard/translation.html` built the LLM "translate all"
  results panel by concatenating model output into an HTML string and
  assigning it to `innerHTML` — stored XSS in a privileged staff session
  (TRANS-01). Every template now builds nodes through the shared
  `stapelDom` helper (`templates/dashboard/_safe_dom.html`), and a test
  fails the build if `innerHTML`/`outerHTML`/`insertAdjacentHTML`/
  `document.write` reappears in any template.
- Stored ref URLs are rendered through a new `|safe_href` filter
  (`{% load stapel_translate %}`) and carry `rel="noopener noreferrer"`.
  A ref whose scheme is not `http`/`https`/`mailto` renders as an inert
  empty `href` instead of a live `javascript:` link. This covers refs that
  are *already* in the database from before the ingestion allowlist above.
- Dashboard pages now send a `Content-Security-Policy` with a per-response
  nonce and no `unsafe-inline`/`unsafe-eval` for scripts. Every inline
  `on*=` handler in the shipped templates was replaced with a delegated
  `data-click`/`data-change`/`data-submit` action so the policy is real
  rather than decorative. Replace the whole policy via
  `STAPEL_TRANSLATE["DASHBOARD_CSP"]`, set it to `{}` to send no header, or
  set `DASHBOARD_CSP_REPORT_ONLY` to observe before enforcing. Responses
  also carry `X-Content-Type-Options` and `Referrer-Policy`.

  *If you override any dashboard template in your project*, add the nonce to
  your own `<script>` tags (`{% if csp_nonce %} nonce="{{ csp_nonce }}"{% endif %}`)
  and drop inline handlers, or set `DASHBOARD_CSP_REPORT_ONLY = True` until
  you have.

### Fixed

- `templates/dashboard/index.html` carried a stray `}` that made its whole
  `<script>` block a syntax error: the source filter and both modals were
  dead on the dashboard index page.
- Dashboard pages had no rendering test at all (the test settings defined no
  `TEMPLATES` engine), which is how both of the above survived a green
  suite. `conftest.py` now configures templates, middleware and an isolated
  `MEDIA_ROOT`.

## [0.5.6] — 2026-08-02

Fix-up: 0.5.5's `publish.yml` test gate never installed `stapel-tools`,
unlike `ci.yml` — the new `docs/llms.txt` drift/determinism tests in
`tests/test_contract.py` failed at the tag-triggered publish workflow
(0.5.5 never reached PyPI). `publish.yml` now installs `stapel-tools`
the same way `ci.yml` does. No other change.

## [0.5.5] — 2026-08-02

Packaging/docs catch-up, no behavior change:

- Badge canon + CI fix-up.
- `docs/llms.txt` — the fifth contract artifact (badge-canon §3),
  rendered from the curated (hand-authored) `docs/capabilities.json` by
  `stapel_tools.llms_txt`; `capabilities.json`'s `version` field brought
  in sync with `pyproject.toml` (0.5.2 → 0.5.5), no other change to its
  hand-authored content.

## [0.5.4] — 2026-07-26

### Changed — requires stapel-core >= 0.15.5

Both collectors import `stapel_core.django.peers`
(`get_with_path_discovery` / `PathResolver` / `PeerRouteUnavailable`), which
lands in stapel-core 0.15.5. The floor moves `0.12.2 → 0.15.5`; the `<1.0`
ceiling is unchanged.

### Fixed — key collectors asked for paths nobody served

Both collectors hardcoded a peer's URL and read the resulting 404 as an
answer — the same two-bug pattern as the stapel-workspaces membership
incident (stapel-core 0.12.x, `django/workspaces.py`).

- `notification_collector.py` polled `/notifications/api/notification-keys/`
  while stapel-notifications mounts `NotificationKeysView` in `urls_v1.py`,
  i.e. at `/notifications/api/v1/notification-keys/` (the §60 v1-canon
  sweep). Every run got a routing 404 and raised a bare
  `Notification keys API returned 404` that read like a peer problem;
  notification templates have not been collected since the sweep.
- `error_collector.py` polled `/{prefix}/api/v1/error-keys/`, which **no**
  library mounted: `ErrorKeysView` was subclassed in profiles, workspaces,
  agent, auth, billing and cdn, and mounted in none of them. Those libraries
  now mount it in their `urls_v1.py` (see their changelogs); it stays out of
  the OpenAPI contract (`schema = None`) and off the flow gate, like every
  other infrastructure endpoint.

The fix is not a fresh literal: endpoint paths are configuration
(`NOTIFICATION_KEYS_PATHS`, `ERROR_KEYS_PATHS`, `SERVICE_URL_TEMPLATE`),
discovered newest-mount-first via the new
`stapel_core.django.peers.get_with_path_discovery`, and a 404 that came from
Django's URL resolver rather than from the view (Content-Type: HTML vs JSON)
raises `PeerRouteUnavailable` / is reported as
`no error-keys endpoint` in `services_failed` instead of being swallowed as
"this service has no keys".

## [0.5.2] — 2026-07-17

### Changed — dashboard moved under the `admin/` canon (BREAKING, alpha — no redirect)

Fleet follow-up to stapel-core 0.12.2's new E004 §37 surface-topology check:
a Stapel module may only mount inside `/<mod>/api/`, `/<mod>/swagger/`,
`/<mod>/schema.json`, `/<mod>/admin/` — a bare `translate/dashboard/`
sub-path (no canonical segment anywhere) is frontend territory, the same
class of finding as the `/calendar` nginx incident E004 exists to catch
mechanically.

- The server-rendered, staff-gated translator dashboard moved from
  `translate/dashboard/` to `translate/admin/dashboard/` (`urls_v1.py`). It
  is a staff-only admin surface (`AuthorizedTranslatorMixin`/`StaffOnlyMixin`
  gating unchanged), so it now lives under the `admin/` canon instead of a
  bare module sub-path.
- No redirect from the old path — pre-1.0 alpha, no compatibility shims.
  Reverse lookups by URL name (`dashboard-index`, etc.) are unaffected;
  hardcoded `/translate/dashboard/...` references (nav-link registration,
  a post-save redirect, dashboard JS) were updated to the new path.
- `stapel-core` dependency floor `>=0.10` → `>=0.12.2` (the version that
  carries the E004 check this fix responds to; ceiling unchanged `<0.13`).
- Added an integration test (`tests/test_surface_containment.py`) that
  runs `stapel_core`'s real E004 check — and `manage.py check` itself —
  against this repo's actual installed URLconf, proving the fleet is clean
  rather than trusting self-report.

## [0.5.1] — 2026-07-17

Fleet follow-up to stapel-core 0.12.0 (legacy shim sweep). No source
changes needed — the module's own `TRANSLATIONS_CHANGED` constant is
distinct from the removed `stapel_core.kafka.events.EventType
.TRANSLATIONS_CHANGED` deprecated alias. Full suite green against core
0.12.0.

### Changed
- `stapel-core` dependency ceiling `<0.12` → `<0.13`.

## [0.5.0] — 2026-07-17

### Removed — legacy flat wire shape & compat re-exports (BREAKING)

- `/translate/api/v1/translations/` responses no longer inline one `<lang>` /
  `<lang>_verified` key per configured language (the pre-0.2.0 column-era
  shape). Stored per-language values are now exposed as a `values` list of
  `{language, value, verified}` rows (`TranslationValueSerializer`).
- `bulk_update` no longer reads flat `<lang>` keys from each item (and drops
  the hardcoded 7-language list): send `{"key": ..., "values": {lang: text}}`;
  languages are validated against the configured set.
- `TranslationEntry.as_dict()` deleted (flat-shape dump; unused outside its
  own test).
- Backwards-compat re-exports of `SUPPORTED_LANGUAGES` / `LANGUAGE_NAMES` /
  `get_default_language` / `translate_settings` from
  `stapel_translate.models` deleted — import them from
  `stapel_translate.conf` (canonical since 0.2.0). Internal importers
  (`views`, `admin`, `dashboard_views`, `figma_views`) now import from
  `conf` directly.
- Tests of the removed surface deleted/rewritten (flat list shape, `as_dict`,
  module re-exports).
- Kept: the dashboard Django-fixture export/import flat inlining — it is the
  live round-trip format of that feature, not a dead compat path. The
  per-language `{key: text}` repo fixtures (`dump_translations` /
  `load_builtin_translations`) are unaffected.

## [0.4.9] — 2026-07-17

### Changed
- `stapel-core` ceiling raised `>=0.10,<0.11` → `>=0.10,<0.12` (core 0.11
  fleet re-pin: default bus, nav, config-checks, error params/language —
  additive for modules). Suite green against core 0.11.2 (incl. the
  `kafka` extra), no code changes needed.

## [0.4.8] — 2026-07-16

### Changed
- **v1 canon sweep §60** (api-versioning.md §2, §6): URL set moved to
  `urls_v1.py`; API mounts now read `translate/api/v1/`,
  `translate/api/v1/dashboard/`, `translate/api/v1/figma/` (version segment
  right after `api/`, per canon); dashboard HTML pages stay unversioned (not
  API surface). Bare `/translate/api/...` no longer exists (sweep lands
  before the §3 API00x gates are enabled). No contract artifacts in this
  repo yet — nothing to regenerate.
- Cross-service callers follow the canon: error-keys collector now queries
  `/{prefix}/api/v1/error-keys/`; LLM proxy calls agent at
  `/api/v1/llm/complete`.
- Lint hygiene to a clean `stapel-verify`: explicit `# noqa` on pre-existing
  findings (R002/R006/R007).

### Changed — admin-suite AS-5: `@access` category rollout
- `TranslationHistory` decorated `@access.ops` (append-only audit log) and its
  `ModelAdmin` swapped to `stapel_core.django.admin.base.StapelModelAdmin`;
  the model's hand-rolled `has_{add,change,delete}_permission` overrides
  (which still allowed a superuser to delete history rows) are dropped in
  favor of the category's uniform read-only-even-for-superuser enforcement.
- `FigmaApiKey` decorated `@access.secret` (hashed Figma-plugin API key
  carrier — the canonical `secret` example named in `docs/admin-suite.md`)
  and its `ModelAdmin` swapped to `StapelModelAdmin`, pinning
  `secret_fields = ("key_hash",)`. `prefix` stays unmasked by design (the
  model's own docstring: an 8-char lookup fragment, not the secret itself).
- `TranslationEntry`, `TranslationValue`, and `AuthorizedTranslator` stay
  undecorated (business, implicit `@access.standard`) — see MODULE.md for
  the reasoning.
- Class/attribute-only changes — confirmed via a standalone
  `makemigrations --check` dry-run: no migrations.

### Fixed — emit-check (outbox atomicity)
- `emit_translations_changed()` (`events.py`) swallowed a failing `emit()`
  behind a broad `except Exception: logger.exception(...)` with no local
  atomic scope (EMIT002). It now runs the emit inside its own
  `transaction.atomic()` savepoint before the swallow — under
  `ATOMIC_REQUESTS=True` a failing emit marks the *surrounding* transaction
  rollback-only (`stapel_core.comm.actions`), so without the nested atomic a
  plain swallow would still 500 the request that changed the translation on
  its next query; the savepoint isolates the failure instead, matching the
  precedent already applied to `stapel-auth`/`stapel-profiles`
  (`emit-check-retrofit`). The call site in
  `TranslationValue.save()` (EMIT003 — the checker cannot see that the
  callee opens its own atomic block) carries a documented
  `# emit-check: ok` pragma. New regression tests
  (`tests/test_events.py::TestTranslationsChangedBestEffort`) prove a
  failing emit does not break `TranslationValue.save()` in either request
  mode. `emit_check` is now clean on this module.

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
