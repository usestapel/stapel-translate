"""Every response body the contract declares is a body the views actually send.

``docs/schema.json`` is emitted from the views' ``@extend_schema``
annotations, and an annotation is a CLAIM: it says what the view returns, and
the generator has no way to check it against the method body.
``tests/test_contract.py`` compares the committed document against a FRESH
EMISSION of the same annotations — it proves the file is not stale, and
nothing else, because both sides come from the claim. stapel-alerts 0.2.0
shipped ``GET /issues`` declared as ``Issue[]`` while the wire carried
``{count, offset, limit, results}``: the drift gate was green and the
frontend pair rendered ``undefined``.

This is the gate the generator cannot be: it performs every operation the
committed schema declares with a JSON response body, and validates the body
it gets against the schema it was promised.

Rules this file holds itself to:

* an operation with a declared JSON response and no entry in ``RECIPES``
  FAILS LOUDLY — a gate that quietly covers three of four rows is the family
  of green that proves nothing;
* a path parameter the gate cannot fill fails at the point of substitution,
  naming the operation;
* an operation that genuinely cannot run in-process is listed by name in
  ``UNDRIVABLE`` with a one-line reason. That list is asserted to be exactly
  current: a stale entry, or a missing reason, fails;
* a collection that comes back empty fails in the populated pass — an empty
  array validates against any item schema, so an empty answer is a check that
  looked at nothing;
* every read is driven a SECOND time against an empty (or valuâ€‘less) database
  (``EMPTY_STATE``), because the claims that break are the ones about what a
  field holds when there is nothing to hold: three of the four libraries in
  the first wave of this gate were caught by a ``null`` on the empty state.

Runs on every interpreter: it reads the committed schema and never emits.
``tests/test_contract.py`` skips off Python 3.12 because it EMITS; this file
does not, so it must not skip either — a contract gate that only runs on one
interpreter is a contract gate the next developer never sees fail.

The urlconf below is the EMISSION mount (``codegen_urls.py``):
``path("", include("stapel_translate.urls"))``, which is what yields the
canonical ``/translate/api/v1/…`` prefix the document is written against.
This module's own ``conftest.py`` sets the same ``ROOT_URLCONF``, so unlike
three of the first four libraries this gate was written for, translate's
suite was already looking where its document describes.

What it found on its first run — 24 of 24 operations driven, 25 declared
(method, path, code) rows, 1 red:

* ``POST /translate/api/v1/translations/bulk_update/`` declared
  ``BulkUpdateResponse.updated_ids`` as an array of UUID STRINGS and answered
  ``{"updated_ids": [1]}``. The claim was inherited — ``stapel_core``'s
  ``BulkUpdateResponseSerializer.updated_ids`` was
  ``ListField(child=UUIDField())`` through 0.24.0 — while the view appends
  ``obj.pk`` of a ``BigAutoField`` model (``views.py:112``,
  ``TranslationEntryViewSet.bulk_update``). stapel-core 0.71.0 redeclared the
  field as a pk union; the floor now names it, the document is emitted against
  it, and the entry is deleted. ``KNOWN_MISMATCHES`` is empty.

``GET /translate/api/v1/translations/data.json/`` is the sibling of that
finding and is CLEAN here: ``TranslationEntryViewSet`` hand-annotates
``data_json`` with ``responses={200: TranslationEntryPublicSerializer(many=True)}``,
so it declares the array it actually sends. The un-annotated form of the same
inherited action is what stapel-core 0.71.0 fixed in the shared mixin.

Two claims are honest but narrow, and are worth naming even though they do
not fail:

* ``POST /translate/api/v1/dashboard/llm-help/`` declares
  ``LLMSingleTranslationResponse`` for the whole operation, and
  ``LLMHelpView.post`` answers ``LLMAllTranslationsResponse``
  (``{suggestions, applied, translate_all, source_context}`` — no
  ``suggestion``, no ``target_lang``) whenever the request carries
  ``translate_all: true``. The declared shape is what the DEFAULT request
  gets, which is what this gate drives; the second shape is undeclared
  surface rather than a false claim about the one that is declared.
* ``GET /translate/api/v1/translations/{id}/`` declares
  ``TranslationEntryPublic``, and ``TranslationEntryViewSet.get_serializer_class``
  answers the wider ``TranslationEntry`` row to a staff/superuser caller.
  The extra keys are additive and JSON Schema admits them, so the declared
  claim holds for every caller; the privileged shape is simply undocumented.

Nothing here is fixed: this is a gate, not a fix.
"""
import base64
import copy
import io
import json
import re
import uuid
from pathlib import Path
from unittest.mock import patch

import jsonschema
import pytest
from django.test import override_settings
from django.urls import include, path as url_path
from rest_framework.test import APIClient

from stapel_translate.providers import BaseTranslationProvider as _BaseProvider

REPO = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((REPO / "docs" / "schema.json").read_text())

#: The mount the contract is emitted at, reproduced for the test client.
#: ``stapel_translate.urls`` carries its own ``translate/api/v1/`` prefixes,
#: so the emission mounts it at the root and so does this.
urlpatterns = [
    url_path("", include("stapel_translate.urls")),
]

pytestmark = [pytest.mark.django_db, pytest.mark.urls(__name__)]

V1 = "/translate/api/v1"

#: An HTTPS Figma link — ``FIGMA_URL_ALLOWED_HOSTS`` ships as ``["figma.com"]``
#: and ``validate_figma_url`` refuses anything else at the write boundary.
FIGMA_URL = "https://www.figma.com/file/wire-contract/Node?node-id=1%3A23"


@pytest.fixture(autouse=True)
def _media_root(tmp_path):
    """Pin every uploaded screenshot to the test's own directory.

    ``POST figma/translations/screenshot/`` writes a real file through a real
    ``FileField``. ``conftest.py`` points ``MEDIA_ROOT`` at a process-wide
    ``mkdtemp``, which survives the run; pinning it per test keeps this
    gate's uploads out of both the checkout and every other test's storage.
    """
    with override_settings(MEDIA_ROOT=str(tmp_path)):
        yield


# ─────────────────────────────────────────────────────────────────────────────
# The contract side: what the document declares
# ─────────────────────────────────────────────────────────────────────────────


def _json_schema(node):
    """OpenAPI 3.0 → JSON Schema, for the divergences that matter here.

    OAS 3.0 spells "may be null" as ``nullable: true`` beside a ``type``;
    JSON Schema has no such keyword and would refuse the null — which is
    exactly the value the interesting operations answer. Everything else
    drf-spectacular emits here (``$ref``, ``enum``, ``required``,
    ``readOnly``, ``additionalProperties``) is JSON Schema as written.
    """
    if isinstance(node, list):
        return [_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    rebuilt = {k: _json_schema(v) for k, v in node.items() if k != "nullable"}
    if node.get("nullable"):
        return {"anyOf": [rebuilt, {"type": "null"}]}
    return rebuilt


def _validator(response_schema):
    root = copy.deepcopy(response_schema)
    root["components"] = copy.deepcopy(SCHEMA["components"])
    return jsonschema.Draft202012Validator(_json_schema(root))


def _operations():
    """Every ``(method, path, 2xx code, JSON body schema)`` the contract declares."""
    ops = []
    for path, methods in SCHEMA["paths"].items():
        for method, op in methods.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            for code, response in op.get("responses", {}).items():
                body = (
                    response.get("content", {})
                    .get("application/json", {})
                    .get("schema")
                )
                if body is not None and code.startswith("2"):
                    ops.append((method.upper(), path, int(code), body))
    return sorted(ops, key=lambda o: (o[1], o[0], o[2]))


OPERATIONS = _operations()


# ─────────────────────────────────────────────────────────────────────────────
# The wire side: harness
# ─────────────────────────────────────────────────────────────────────────────


def _unique(prefix):
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def anonymous():
    """The surface ``ReadOnlyOrSuperUser`` serves to an unauthenticated app."""
    return APIClient()


def make_user(**kwargs):
    from stapel_core.django.users.models import User

    defaults = dict(
        username=_unique("wire_"),
        email=f"{_unique('wire-')}@example.com",
        password="wire-contract-password-7",
    )
    defaults.update(kwargs)
    return User.objects.create_user(**defaults)


def user_client(**kwargs):
    """An authenticated non-privileged caller (``IsNotAnonymousUser``)."""
    client = APIClient()
    client.force_authenticate(user=make_user(**kwargs))
    return client


def staff_client():
    """The dashboard caller: ``IsAuthorizedTranslator`` passes staff outright."""
    client = APIClient()
    client.force_authenticate(user=make_user(is_staff=True))
    return client


def superuser_client():
    """``IsSuperUser`` — the only door onto ``translations/bulk_update/``."""
    client = APIClient()
    client.force_authenticate(user=make_user(is_staff=True, is_superuser=True))
    return client


def figma_client():
    """A client bearing a real Figma plugin key.

    ``FigmaApiKeyAuthentication`` looks the key up by its 8-char prefix and
    compares SHA-256 hashes, so the plaintext has to come from the row that
    was just created — it is never stored.
    """
    from stapel_translate.models import FigmaApiKey

    key = FigmaApiKey.objects.create(name="Wire Contract Design Team")
    return APIClient(HTTP_X_FIGMA_API_KEY=key.plaintext_key)


def make_entry(key=None, values=None, **kwargs):
    """A translation entry, optionally with per-language values."""
    from stapel_translate.models import TranslationEntry

    entry = TranslationEntry.objects.create(key=key or _unique("wire.key."), **kwargs)
    for lang, value in (values or {}).items():
        entry.set_value(lang, value)
    return entry


def png_base64(width=4, height=4):
    """A real, small PNG — ``decode_screenshot`` sniffs the bytes."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (1, 2, 3)).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


class _FakeLLMResponse:
    """What ``requests.post`` hands ``LLMHelpView`` back."""

    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def llm_agent(result="Speichern"):
    """Stand in for the agent HTTP call ``LLMHelpView`` makes.

    The boundary is the network, not the view: everything this gate is about
    — the DTO the view builds and the serializer that renders it — runs for
    real.
    """
    from stapel_translate import dashboard_views

    def _post(url, json=None, headers=None, timeout=None):
        return _FakeLLMResponse({"status": "ok", "result": result})

    return patch.object(dashboard_views.http_requests, "post", _post)


class WireProvider(_BaseProvider):
    """``LLM_PROVIDER`` for ``POST text/`` — the seam a host actually swaps.

    Declared as a module-level class so ``override_settings`` can name it by
    dotted path, the way a deployment does. Only the transport is fake: the
    batching, the bounds, the cache and the DTO are the shipped ones.
    """

    def complete(self, prompt):
        payload = re.search(r"\[.*\]", prompt, re.DOTALL)
        texts = json.loads(payload.group(0)) if payload else []
        return json.dumps([f"[es] {text}" for text in texts], ensure_ascii=False)


def text_provider():
    return override_settings(
        STAPEL_TRANSLATE={"LLM_PROVIDER": f"{__name__}.WireProvider"}
    )


# ─────────────────────────────────────────────────────────────────────────────
# The recipe table
# ─────────────────────────────────────────────────────────────────────────────


class Call:
    """Performs one declared operation, and refuses to guess a path parameter."""

    def __init__(self, method, path):
        self.method = method
        self.path = path

    def __call__(self, client, params=None, data=None, query="", **extra):
        url = self.path
        for name, value in (params or {}).items():
            url = url.replace("{%s}" % name, str(value))
        assert "{" not in url, (
            f"{self.method} {self.path}: a path parameter this gate does not "
            "know how to fill — teach its recipe, or the operation goes unchecked"
        )
        send = getattr(client, self.method.lower())
        if self.method in ("GET", "DELETE"):
            return send(url + query, **extra)
        return send(url + query, data if data is not None else {}, format="json", **extra)


#: How to perform each operation the contract declares with a JSON response
#: body, keyed by ``(METHOD, path template, status code)``. ``code`` is
#: ``None`` for the usual case of one 2xx per operation, and an explicit
#: integer where one operation declares two (``POST figma/translations/``
#: answers 201 on create and 200 on update, and both are declared).
RECIPES = {}

#: The same operations again, driven against a database with nothing in it —
#: or, where the operation addresses a row by id, a row carrying no values at
#: all. Populated answers hide every claim about absence: an empty array
#: satisfies any item schema and a ``null`` only appears when there is
#: nothing to report. The first wave of this gate found its nulls here.
EMPTY_STATE = {}


def recipe(method, path, code=None, table=None):
    def register(fn):
        target = RECIPES if table is None else table
        key = (method, V1 + path, code)
        assert key not in target, f"duplicate recipe for {method} {path} {code}"
        target[key] = fn
        return fn

    return register


def empty_state(method, path, code=None):
    return recipe(method, path, code, table=EMPTY_STATE)


#: Operations that cannot be driven in-process, by name and with the reason.
#: A short, visible list is acceptable here; a silent skip is not.
#:
#: EMPTY, and that is worth stating: every operation this module declares is
#: reachable from a test client, including the two that reach outside the
#: process (the LLM agent and the translation provider), because both of them
#: are library SEAMS a deployment configures — so the gate configures them
#: too, and everything on this side of the seam runs for real.
UNDRIVABLE: dict = {}


# ── dashboard JSON API (IsAuthorizedTranslator) ──────────────────────────────


@recipe("GET", "/dashboard/stats/")
def _dashboard_stats(call):
    make_entry(values={"en": "Save", "de": "Speichern"})
    return call(staff_client())


@empty_state("GET", "/dashboard/stats/")
def _dashboard_stats_empty(call):
    return call(staff_client())


@recipe("GET", "/dashboard/languages/{lang}/")
def _dashboard_language(call):
    make_entry(values={"en": "Save"})
    return call(staff_client(), params={"lang": "en"})


@empty_state("GET", "/dashboard/languages/{lang}/")
def _dashboard_language_empty(call):
    return call(staff_client(), params={"lang": "en"})


@recipe("GET", "/dashboard/translations/{id}/")
def _dashboard_translation_get(call):
    entry = make_entry(values={"en": "Save"}, comment="Button label")
    return call(staff_client(), params={"id": entry.pk})


@empty_state("GET", "/dashboard/translations/{id}/")
def _dashboard_translation_get_empty(call):
    """A key nobody has translated yet — every language value is absent."""
    return call(staff_client(), params={"id": make_entry().pk})


@recipe("PATCH", "/dashboard/translations/{id}/")
def _dashboard_translation_patch(call):
    entry = make_entry(values={"en": "Save"})
    return call(
        staff_client(), params={"id": entry.pk}, data={"lang": "en", "value": "Store"}
    )


@recipe("PATCH", "/dashboard/translations/{id}/comment/")
def _dashboard_translator_comment(call):
    entry = make_entry(values={"en": "Save"})
    return call(
        staff_client(),
        params={"id": entry.pk},
        data={"translator_comment": "Used in the header"},
    )


@recipe("POST", "/dashboard/translations/{id}/verify/")
def _dashboard_verify(call):
    entry = make_entry(values={"en": "Save"})
    return call(
        staff_client(), params={"id": entry.pk}, data={"lang": "en", "verified": True}
    )


@recipe("GET", "/dashboard/translations/{id}/navigation/")
def _dashboard_navigation(call):
    """Three rows, asked about the middle one: both neighbours are integers."""
    make_entry(key="wire.nav.a", values={"en": "A"})
    middle = make_entry(key="wire.nav.b", values={"en": "B"})
    make_entry(key="wire.nav.c", values={"en": "C"})
    return call(staff_client(), params={"id": middle.pk})


@empty_state("GET", "/dashboard/translations/{id}/navigation/")
def _dashboard_navigation_empty(call):
    """The only row there is: ``prev_id`` and ``next_id`` are both null."""
    return call(staff_client(), params={"id": make_entry().pk})


@recipe("POST", "/dashboard/llm-help/")
def _dashboard_llm_help(call):
    entry = make_entry(values={"en": "Save"}, comment="Button label")
    with llm_agent():
        return call(
            staff_client(),
            data={"translation_id": entry.pk, "target_lang": "de"},
        )


@empty_state("POST", "/dashboard/llm-help/")
def _dashboard_llm_help_empty(call):
    """No existing translations at all — ``source_context`` is ``{}``."""
    entry = make_entry()
    with llm_agent():
        return call(
            staff_client(),
            data={"translation_id": entry.pk, "target_lang": "de"},
        )


# ── figma plugin API (X-Figma-API-Key) ───────────────────────────────────────


@recipe("GET", "/figma/auth/")
def _figma_auth(call):
    return call(figma_client())


@recipe("GET", "/figma/translations/")
def _figma_translations_list(call):
    make_entry(source="app:figma", values={"en": "Save"})
    return call(figma_client(), query="?lang=en")


@empty_state("GET", "/figma/translations/")
def _figma_translations_list_empty(call):
    return call(figma_client(), query="?lang=en")


@recipe("POST", "/figma/translations/", code=201)
def _figma_translations_create(call):
    """A key the catalogue has never seen — the create half of the upsert."""
    return call(
        figma_client(),
        data={
            "key": _unique("wire.figma."),
            "value": "Save",
            "comment": "Button label",
            "figma_url": FIGMA_URL,
            "lang": "en",
            "screen_name": "Home",
        },
    )


@recipe("POST", "/figma/translations/", code=200)
def _figma_translations_update(call):
    """The same key again — the update half, which answers 200, not 201."""
    entry = make_entry(source="app:figma", values={"en": "Save"})
    return call(
        figma_client(),
        data={
            "key": entry.key,
            "value": "Store",
            "comment": "Reworded",
            "figma_url": FIGMA_URL,
            "lang": "en",
        },
    )


@recipe("GET", "/figma/translations/{key}/")
def _figma_translation_detail(call):
    entry = make_entry(values={"en": "Save", "de": "Speichern"}, comment="Button label")
    return call(figma_client(), params={"key": entry.key}, query="?lang=de")


@empty_state("GET", "/figma/translations/{key}/")
def _figma_translation_detail_empty(call):
    """A key with no values: ``all_translations`` is ``{}`` and ``value`` ``""``."""
    return call(figma_client(), params={"key": make_entry().key})


@recipe("POST", "/figma/translations/search/")
def _figma_search(call):
    make_entry(values={"en": "Wire contract needle"})
    return call(
        figma_client(),
        data={
            "text": "Wire contract needle",
            "figma_url": FIGMA_URL,
            "screen_name": "Home",
        },
    )


@empty_state("POST", "/figma/translations/search/")
def _figma_search_empty(call):
    """Nothing matches — ``entry`` comes back null, which the claim allows."""
    return call(figma_client(), data={"text": "nothing matches this"})


@recipe("POST", "/figma/translations/sync/")
def _figma_sync(call):
    make_entry(key="wire.sync.existing", source="app:figma", values={"en": "Save"})
    return call(
        figma_client(),
        data={
            "entries": [
                {
                    "key": "wire.sync.existing",
                    "currentText": "Save",
                    "figmaUrl": FIGMA_URL,
                    "containerName": "Home",
                    "order": 1,
                },
                {
                    "key": "wire.sync.fresh",
                    "currentText": "Cancel",
                    "figmaUrl": FIGMA_URL,
                    "containerName": "Home",
                    "order": 2,
                },
            ]
        },
    )


@recipe("POST", "/figma/translations/remove-ref/")
def _figma_remove_ref(call):
    entry = make_entry(
        source="app:figma",
        refs=[FIGMA_URL],
        comment="Screen: Home",
        values={"en": "Save"},
    )
    return call(
        figma_client(),
        data={"key": entry.key, "figma_url": FIGMA_URL, "screen_name": "Home"},
    )


@recipe("POST", "/figma/translations/screenshot/")
def _figma_screenshot(call):
    entry = make_entry(values={"en": "Save"})
    return call(figma_client(), data={"key": entry.key, "image": png_base64()})


# ── public API (ReadOnlyOrSuperUser / IsSuperUser / IsNotAnonymousUser) ───────


@recipe("GET", "/translations/")
def _translations_list(call):
    make_entry(values={"en": "Save"})
    return call(anonymous())


@empty_state("GET", "/translations/")
def _translations_list_empty(call):
    """No rows: ``revisions.min`` and ``revisions.max`` are both null."""
    return call(anonymous())


@recipe("GET", "/translations/{id}/")
def _translations_retrieve(call):
    entry = make_entry(values={"en": "Save"})
    return call(anonymous(), params={"id": entry.pk})


@empty_state("GET", "/translations/{id}/")
def _translations_retrieve_empty(call):
    return call(anonymous(), params={"id": make_entry().pk})


@recipe("GET", "/translations/revision/")
def _translations_revision(call):
    make_entry(values={"en": "Save"})
    return call(anonymous())


@empty_state("GET", "/translations/revision/")
def _translations_revision_empty(call):
    return call(anonymous())


@recipe("GET", "/translations/data.json/")
def _translations_data_json(call):
    make_entry(values={"en": "Save"})
    return call(anonymous(), query="?revision=1")


@empty_state("GET", "/translations/data.json/")
def _translations_data_json_empty(call):
    return call(anonymous(), query="?revision=0")


@recipe("POST", "/translations/bulk_update/")
def _translations_bulk_update(call):
    return call(
        superuser_client(),
        data=[{"key": _unique("wire.bulk."), "values": {"en": "Save"}}],
    )


@recipe("GET", "/languages/revision/")
def _language_revision(call):
    make_entry(values={"en": "Save"})
    return call(anonymous())


@empty_state("GET", "/languages/revision/")
def _language_revision_empty(call):
    return call(anonymous())


@recipe("GET", "/languages/{lang}/data/")
def _language_data(call):
    make_entry(values={"en": "Save"})
    return call(anonymous(), params={"lang": "en"}, query="?revision=1")


@empty_state("GET", "/languages/{lang}/data/")
def _language_data_empty(call):
    return call(anonymous(), params={"lang": "en"}, query="?revision=0")


@recipe("POST", "/text/")
def _text_translation(call):
    with text_provider():
        return call(
            user_client(),
            data={"text": "A red car in good condition", "target_lang": "es"},
        )


# ─────────────────────────────────────────────────────────────────────────────
# The gate
# ─────────────────────────────────────────────────────────────────────────────


#: Operations whose declared body the wire does not send.
#:
#: An entry names the defect AND its owner, and ``strict=True`` turns a fixed
#: one into a failure until the entry is deleted — so a finding can be neither
#: forgotten nor quietly kept.
KNOWN_MISMATCHES: dict[tuple[str, str], str] = {}


def _recipe_for(table, method, path, code):
    """The code-specific recipe if there is one, else the operation's."""
    return table.get((method, path, code)) or table.get((method, path, None))


def test_the_contract_declares_something_to_check():
    assert OPERATIONS, "docs/schema.json declares no JSON responses at all"


def test_every_declared_path_resolves_under_this_urlconf():
    """The suite must be looking where the document describes.

    Three of the first four libraries this gate was written for had a
    committed contract that nothing had ever driven, because the test urlconf
    mounted somewhere the document does not describe: one mounted a different
    prefix AND one segment short, one mounted the paths bare, and one mounted
    less than the emission did. In every case the operations were "covered"
    by a file that could not have reached a single one of them.

    That is the same family as a gate nobody asks: the recipes can all be
    written, the run can be green, and not one request went where the
    contract says it goes. A missing recipe already fails loudly; this fails
    when the MOUNT is wrong, which no per-operation check can see, because
    when the mount is wrong every operation is equally and silently
    unreachable.

    Asserted against the urlconf this module declares, so it fails at the one
    moment it is cheap to fix: when somebody changes a mount.
    """
    from django.urls import Resolver404, resolve

    # Resolution cares about the SHAPE of a segment, and URL sets use several
    # converters — uuid, int, slug/str. A path counts as reachable if any one
    # shape resolves: the question here is whether the mount exists, not
    # whether a particular id does.
    candidates = (
        "00000000-0000-4000-8000-000000000000",
        "1",
        "a-slug",
    )

    unreachable = []
    for _method, path, _code, _schema in OPERATIONS:
        for value in candidates:
            try:
                resolve(re.sub(r"\{[^}]+\}", value, path))
                break
            except Resolver404:
                continue
        else:
            unreachable.append(path)

    assert not unreachable, (
        "these declared paths do not resolve under this module's urlconf, so "
        "nothing here can be driving them — the mount is wrong, not the "
        "recipes:\n  " + "\n  ".join(sorted(set(unreachable)))
    )


def test_every_declared_operation_is_driven_or_named_undrivable():
    """No operation is covered by silence, and no entry outlives its operation."""
    missing = [
        (method, path, code)
        for method, path, code, _schema in OPERATIONS
        if _recipe_for(RECIPES, method, path, code) is None
        and (method, path) not in UNDRIVABLE
    ]
    assert not missing, (
        "operations with a declared JSON response body and no recipe:\n"
        + "\n".join(f"  {m} {p} -> {c}" for m, p, c in missing)
    )

    declared_codes = {(m, p, c) for m, p, c, _ in OPERATIONS}
    declared_ops = {(m, p) for m, p, _c, _ in OPERATIONS}
    stale = sorted(
        key
        for key in RECIPES
        if (key[0], key[1]) not in declared_ops
        or (key[2] is not None and key not in declared_codes)
    )
    assert not stale, (
        "recipes for operations/status codes the contract no longer declares:\n"
        + "\n".join(f"  {m} {p} -> {c}" for m, p, c in stale)
    )
    stale_exclusions = sorted(set(UNDRIVABLE) - declared_ops)
    assert not stale_exclusions, (
        "exclusions for operations the contract no longer declares: "
        f"{stale_exclusions}"
    )
    both = sorted(
        (m, p) for m, p, _c in RECIPES if (m, p) in UNDRIVABLE
    )
    assert not both, f"driven AND excluded: {both}"
    for key, reason in UNDRIVABLE.items():
        assert reason and reason.strip(), f"{key} is excluded with no reason"


def test_every_read_is_also_driven_against_an_empty_database():
    """A populated answer cannot say what a field holds when there is nothing.

    Every null finding in the first wave of this gate was on the empty state:
    an ``exp`` that is null for every active token, a counter that is null for
    every account without the feature, a ``created_at`` that is null for every
    account that just signed up. A gate that only ever seeds three rows and
    asks never sees any of them.

    So every GET is required to have an ``EMPTY_STATE`` recipe as well. The
    one exemption is named here, with its reason.
    """
    exempt = {
        # Answers from the API-key row and the configured language list —
        # there is no catalogue state for it to be empty of, so the "empty"
        # run would be byte-for-byte the populated one.
        ("GET", V1 + "/figma/auth/"),
    }
    reads = {
        (method, path)
        for method, path, _code, _schema in OPERATIONS
        if method == "GET"
    }
    covered = {(m, p) for m, p, _c in EMPTY_STATE}
    missing = sorted(reads - covered - exempt)
    assert not missing, (
        "reads driven only against a populated database — the state where "
        "every null claim in this gate's history was found is unchecked:\n"
        + "\n".join(f"  {m} {p}" for m, p in missing)
    )
    declared_ops = {(m, p) for m, p, _c, _ in OPERATIONS}
    stale = sorted({(m, p) for m, p, _c in EMPTY_STATE} - declared_ops)
    assert not stale, f"empty-state recipes for undeclared operations: {stale}"


def test_every_known_mismatch_is_still_declared_and_explained():
    """A recorded defect must name a live operation and carry its reason.

    Without this, an operation that is renamed or removed leaves an entry that
    silences nothing and reads like a known problem forever.
    """
    declared = {(method, path) for method, path, _code, _schema in OPERATIONS}
    for key, reason in KNOWN_MISMATCHES.items():
        assert key in declared, (
            f"{key} is recorded as a known mismatch but the contract no longer "
            "declares it — delete the entry"
        )
        assert reason and reason.strip(), f"{key} is recorded with no reason"


def _drive(table, method, path, code, body_schema, *, expect_rows):
    perform = _recipe_for(table, method, path, code)
    assert perform is not None, (
        f"{method} {path} declares a response body and has no recipe — an "
        "unchecked operation is a schema nobody proves. Teach RECIPES, or "
        "name it in UNDRIVABLE with a reason."
    )

    response = perform(Call(method, path))
    assert response.status_code == code, (
        f"{method} {path}: expected the declared {code}, got "
        f"{response.status_code}: {response.content[:400]}"
    )

    body = response.json()
    errors = sorted(_validator(body_schema).iter_errors(body), key=lambda e: list(e.path))
    assert not errors, (
        f"{method} {path} answers a body the contract does not describe:\n"
        + "\n".join(f"  at {list(e.path) or '<root>'}: {e.message}" for e in errors[:10])
        + f"\n  body: {json.dumps(body)[:600]}"
    )
    # An empty list validates against any item schema, so a list response must
    # actually carry a row for the check to have looked at anything.
    if expect_rows and isinstance(body, list):
        assert body, f"{method} {path}: the declared list came back empty"
    return body


@pytest.mark.parametrize(
    "method,path,code,body_schema",
    OPERATIONS,
    ids=[f"{m} {p} {c}" for m, p, c, _ in OPERATIONS],
)
def test_the_wire_matches_the_declared_response(method, path, code, body_schema, request):
    if (method, path) in UNDRIVABLE:
        pytest.skip(f"excluded by name: {UNDRIVABLE[(method, path)]}")

    if (method, path) in KNOWN_MISMATCHES:
        request.node.add_marker(
            pytest.mark.xfail(
                strict=True,
                reason=f"{method} {path}: {KNOWN_MISMATCHES[(method, path)]}",
            )
        )

    _drive(RECIPES, method, path, code, body_schema, expect_rows=True)


_EMPTY_OPERATIONS = [
    (method, path, code, schema)
    for method, path, code, schema in OPERATIONS
    if _recipe_for(EMPTY_STATE, method, path, code) is not None
]


@pytest.mark.parametrize(
    "method,path,code,body_schema",
    _EMPTY_OPERATIONS,
    ids=[f"{m} {p} {c}" for m, p, c, _ in _EMPTY_OPERATIONS],
)
def test_the_wire_matches_the_declared_response_when_there_is_nothing_there(
    method, path, code, body_schema, request
):
    """The same claim, asked of a database with nothing in it."""
    if (method, path) in KNOWN_MISMATCHES:
        request.node.add_marker(
            pytest.mark.xfail(
                strict=True,
                reason=f"{method} {path}: {KNOWN_MISMATCHES[(method, path)]}",
            )
        )

    _drive(EMPTY_STATE, method, path, code, body_schema, expect_rows=False)


def test_the_gate_is_not_blind():
    """A canary: swap a declared schema for one the wire cannot satisfy.

    Everything above can be green for two reasons — the claims are honest, or
    the check never looks at the body. This tells them apart by validating a
    real response against ``{"type": "string"}``: every operation here answers
    an object or an array, so every one of them must fail. If any passes, the
    validation in ``_drive`` is not reaching the received body and this whole
    file proves nothing.
    """
    honest = [
        (method, path, code)
        for method, path, code, _schema in OPERATIONS
        if (method, path) not in KNOWN_MISMATCHES and (method, path) not in UNDRIVABLE
    ]
    assert honest, "nothing left to canary"

    survivors = []
    for method, path, code in honest:
        try:
            _drive(
                RECIPES, method, path, code, {"type": "string"}, expect_rows=False
            )
        except AssertionError:
            continue
        survivors.append(f"{method} {path}")
    assert not survivors, (
        "these operations passed validation against {'type': 'string'} — the "
        "gate is not looking at the body it received:\n  " + "\n  ".join(survivors)
    )
