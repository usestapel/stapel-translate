"""Data Transfer Objects for translate API."""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class LanguageRevisionResponse:
    """Current maximum revision number for translations.

    Attributes:
        revision: Latest revision number. Example: 42
    """
    revision: int


# -- Dashboard DTOs --------------------------------------------------------


@dataclass
class LanguageStats:
    """Translation statistics for a single language.

    Attributes:
        lang: ISO 639-1 language code. Example: fr
        name: Human-readable language name. Example: French
        total: Total translation entries. Example: 350
        verified: Verified entries count. Example: 280
        unverified: Unverified entries count. Example: 70
    """
    lang: str
    name: str
    total: int
    verified: int
    unverified: int


@dataclass
class DashboardStatsResponse:
    """Dashboard translation statistics across all languages.

    Attributes:
        languages: Per-language statistics list.
        total_entries: Total translation entries. Example: 350
    """
    languages: List[LanguageStats]
    total_entries: int


@dataclass
class NavigationResponse:
    """Previous/next translation entry IDs for keyboard navigation.

    Attributes:
        prev_id: Previous entry ID, null if at start. Example: 41
        next_id: Next entry ID, null if at end. Example: 43
    """
    prev_id: Optional[int]
    next_id: Optional[int]


@dataclass
class LLMSingleTranslationResponse:
    """LLM translation suggestion for a single language.

    Attributes:
        suggestion: Suggested translation text. Example: Speichern
        applied: Whether the suggestion was auto-applied. Example: false
        target_lang: Target language code. Example: de
        source_context: Source texts used for context. Example: {"en": "Save"}
    """
    suggestion: str
    applied: bool
    target_lang: str
    source_context: Dict[str, str]


@dataclass
class LLMAllTranslationsResponse:
    """LLM translation suggestions for all languages at once.

    Attributes:
        suggestions: Language code to suggested text mapping. Example: {"de": "Speichern", "fr": "Sauvegarder"}
        applied: Whether suggestions were auto-applied. Example: false
        translate_all: Whether all languages were requested. Example: true
        source_context: Source texts used for context. Example: {"en": "Save"}
    """
    suggestions: Dict[str, str]
    applied: bool
    translate_all: bool
    source_context: Dict[str, str]


# -- Figma DTOs ------------------------------------------------------------

@dataclass
class FigmaAuthResponse:
    """Figma API key validation result.

    Attributes:
        valid: Whether the API key is valid. Example: true
        name: Translator name. Example: John
        languages: Allowed languages with code and name. Example: [{"code": "fr", "name": "French"}]
    """
    valid: bool
    name: str
    languages: List[Dict[str, str]]


@dataclass
class FigmaTranslationsListResponse:
    """All translations for a language (Figma plugin).

    Attributes:
        translations: Key to translated text mapping. Example: {"common.save": "Sauvegarder"}
        language: Language code. Example: fr
        count: Number of entries. Example: 350
    """
    translations: Dict[str, str]
    language: str
    count: int


@dataclass
class FigmaTranslationUpsertResponse:
    """Created or updated translation entry (Figma plugin).

    Attributes:
        id: Entry database ID. Example: 42
        key: Translation key. Example: common.save
        value: Translation text. Example: Sauvegarder
        comment: Admin comment. Example: Save button label
        translator_comment: Translator note. Example: Used in header
        refs: Figma node references. Example: ["1:23", "4:56"]
        order: Sort order. Example: 10
        created: True if newly created. Example: true
        updated: True if an existing entry was modified. Example: false
        verified: Verification status after upsert. Example: false
    """
    id: int
    key: str
    value: str
    comment: str
    translator_comment: str
    refs: List[str]
    order: Optional[int]
    created: bool
    updated: Optional[bool] = None
    verified: Optional[bool] = None


@dataclass
class FigmaSearchResponse:
    """Search for translation entry by text (Figma plugin).

    Attributes:
        found: Whether a match was found. Example: true
        entry: Matched translation entry object. Example: {"id": 42, "key": "common.save"}
        ref_added: Whether a Figma ref was added to the entry. Example: true
    """
    found: bool
    entry: Optional[Dict[str, Any]]
    ref_added: bool


@dataclass
class FigmaTranslationDetailResponse:
    """Full translation entry detail (Figma plugin).

    Attributes:
        id: Entry database ID. Example: 42
        key: Translation key. Example: common.save
        value: Translation text for requested language. Example: Sauvegarder
        language: Requested language code. Example: fr
        comment: Admin comment. Example: Save button label
        translator_comment: Translator note. Example: Used in header
        source: Entry source (manual, figma, llm, dashboard). Example: figma
        order: Sort order. Example: 10
        all_translations: All language translations for this key. Example: {"en": "Save", "fr": "Sauvegarder"}
        verified: Whether current language is verified. Example: true
        verification_status: Per-language verification status. Example: {"en": true, "fr": true, "de": false}
    """
    id: int
    key: str
    value: str
    language: str
    comment: str
    translator_comment: str
    source: str
    order: Optional[int]
    all_translations: Dict[str, str]
    verified: bool
    verification_status: Dict[str, bool]


@dataclass
class FigmaSyncResponse:
    """Figma bulk sync result.

    Attributes:
        synced: Total entries processed. Example: 50
        created: New entries created. Example: 5
        updated: Existing entries updated. Example: 12
    """
    synced: int
    created: int
    updated: int


@dataclass
class FigmaScreenshotUploadResponse:
    """Screenshot upload result for a single key.

    Attributes:
        key: Translation key. Example: common.save
        uploaded: Whether the screenshot was saved. Example: true
    """
    key: str
    uploaded: bool


@dataclass
class FigmaRemoveRefResponse:
    """Figma ref removal result.

    Attributes:
        key: Translation key. Example: common.save
        ref_removed: Whether the ref was removed. Example: true
        refs: Remaining Figma refs after removal. Example: ["1:23"]
    """
    key: str
    ref_removed: bool
    refs: List[str]
