import logging
import threading

import requests as http_requests
from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import path

from .conf import LANGUAGE_NAMES
from .models import (
    SUPPORTED_LANGUAGES,
    AuthorizedTranslator,
    FigmaApiKey,
    TranslationEntry,
    TranslationHistory,
    TranslationValue,
)
from .providers import agent_payload, get_agent_url

logger = logging.getLogger(__name__)

LLM_TASK_CACHE_KEY = "llm_translation_task_status"


def _translate_entries_background(entry_ids: list):
    """Background task to translate entries with LLM."""
    api_key = getattr(settings, "SERVICE_API_KEY", None)
    headers = (
        {
            "Content-Type": "application/json",
            "X-API-KEY": api_key,
        }
        if api_key
        else {"Content-Type": "application/json"}
    )

    total = len(entry_ids)
    translated_count = 0
    error_count = 0
    errors = []

    # Update status: started
    cache.set(
        LLM_TASK_CACHE_KEY,
        {
            "status": "running",
            "total": total,
            "completed": 0,
            "errors": 0,
            "error_messages": [],
        },
        timeout=3600,
    )

    for entry_id in entry_ids:
        try:
            entry = TranslationEntry.objects.get(id=entry_id)
        except TranslationEntry.DoesNotExist:
            error_count += 1
            continue

        # Build context from existing translations
        existing_translations = []
        missing_langs = []

        for lang in SUPPORTED_LANGUAGES:
            value = entry.get_value(lang)
            is_verified = entry.get_verified(lang)
            if value:
                status_label = "VERIFIED" if is_verified else "unverified"
                existing_translations.append(f'- {lang} [{status_label}]: "{value}"')
            else:
                missing_langs.append(lang)

        # Only translate languages that have no value at all
        if not missing_langs:
            translated_count += 1
            continue

        lang_list = "\n".join([f"- {code}" for code in missing_langs])
        json_example = ", ".join([f'"{code}": "..."' for code in missing_langs])

        existing_section = ""
        if existing_translations:
            existing_section = f"""
Existing translations (use as reference for style and tone):
{chr(10).join(existing_translations)}
"""

        prompt = f"""You are a professional translator for a marketplace application.
Translate this UI/feature label into the specified languages.

Key to translate: "{entry.key}"
{f"Comment/context: {entry.comment}" if entry.comment else ""}
{existing_section}
Languages to translate (provide translations ONLY for these missing languages):
{lang_list}

Rules:
- Keep translations concise and natural for UI labels
- Preserve any technical terms or brand names
- If the key looks like a sentence, translate as a sentence
- If it's a single word or short phrase, keep it as such
- For ambiguous terms, prefer marketplace/e-commerce context
- Match the style and tone of existing translations

Return ONLY valid JSON like: {{{json_example}}}"""

        try:
            response = http_requests.post(
                f"{get_agent_url()}/api/llm/complete",
                json=agent_payload(prompt),
                headers=headers,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            if data.get("status") == "ok":
                result = data.get("result", {})
                # Handle string result (try to parse as JSON)
                if isinstance(result, str):
                    import json

                    try:
                        result = json.loads(result)
                    except json.JSONDecodeError:
                        error_count += 1
                        errors.append(f"{entry.key}: LLM returned invalid JSON")
                        continue

                # Update translations: only fill empty, non-verified fields
                for lang in SUPPORTED_LANGUAGES:
                    if lang in result and result[lang]:
                        # Skip if already has a value
                        if entry.get_value(lang):
                            continue
                        # Skip if verified
                        if entry.get_verified(lang):
                            continue
                        entry.set_value(lang, result[lang])
                entry.llm_translated = True
                entry.save()
                translated_count += 1
            else:
                error_count += 1
                errors.append(f"{entry.key}: LLM returned non-ok status")

        except Exception as e:
            error_count += 1
            errors.append(f"{entry.key}: {str(e)}")
            logger.warning(f"Error translating '{entry.key}': {e}")

        # Update progress in cache
        cache.set(
            LLM_TASK_CACHE_KEY,
            {
                "status": "running",
                "total": total,
                "completed": translated_count + error_count,
                "translated": translated_count,
                "errors": error_count,
                "error_messages": errors[-10:],  # Keep last 10 errors
            },
            timeout=3600,
        )

    # Final status
    cache.set(
        LLM_TASK_CACHE_KEY,
        {
            "status": "completed",
            "total": total,
            "completed": total,
            "translated": translated_count,
            "errors": error_count,
            "error_messages": errors[-10:],
        },
        timeout=3600,
    )

    logger.info(
        f"LLM translation completed: {translated_count} translated, {error_count} errors"
    )


@admin.action(description="Translate selected with LLM (background)")
def translate_with_llm(modeladmin, request, queryset):
    """Start background LLM translation for selected entries."""
    # Check if task is already running
    current_status = cache.get(LLM_TASK_CACHE_KEY)
    if current_status and current_status.get("status") == "running":
        modeladmin.message_user(
            request,
            f"Translation already in progress: {current_status.get('completed', 0)}/{current_status.get('total', 0)}. Wait for it to complete.",
            messages.WARNING,
        )
        return

    entry_ids = list(queryset.values_list("id", flat=True))
    if not entry_ids:
        modeladmin.message_user(request, "No entries selected", messages.WARNING)
        return

    # Start background thread
    thread = threading.Thread(
        target=_translate_entries_background, args=(entry_ids,), daemon=True
    )
    thread.start()

    modeladmin.message_user(
        request,
        f"Started LLM translation for {len(entry_ids)} entries in background. Check status via 'LLM Status' button.",
        messages.SUCCESS,
    )


def _language_choices():
    return [
        (code, f"{code} — {LANGUAGE_NAMES.get(code, code)}")
        for code in SUPPORTED_LANGUAGES
    ]


class AuthorizedTranslatorForm(forms.ModelForm):
    allowed_languages = forms.MultipleChoiceField(
        choices=_language_choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        help_text="Languages this translator can edit. Leave all unchecked = access to all languages.",
    )

    class Meta:
        model = AuthorizedTranslator
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.allowed_languages:
            self.initial["allowed_languages"] = self.instance.allowed_languages

    def clean_allowed_languages(self):
        return self.cleaned_data.get("allowed_languages", [])


@admin.register(AuthorizedTranslator)
class AuthorizedTranslatorAdmin(admin.ModelAdmin):
    form = AuthorizedTranslatorForm
    list_display = [
        "email",
        "name",
        "is_active",
        "allowed_languages_display",
        "created_at",
    ]
    list_filter = ["is_active"]
    search_fields = ["email", "name", "notes"]
    readonly_fields = ["created_at"]

    @admin.display(description="Languages")
    def allowed_languages_display(self, obj):
        if obj.allowed_languages:
            return ", ".join(obj.allowed_languages)
        return "All"


@admin.register(FigmaApiKey)
class FigmaApiKeyAdmin(admin.ModelAdmin):
    list_display = ["name", "prefix", "is_active", "created_at", "last_used_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "prefix"]
    readonly_fields = ["prefix", "created_at", "last_used_at"]
    fields = ["name", "is_active", "prefix", "created_at", "last_used_at"]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        plaintext = getattr(obj, "plaintext_key", None)
        if plaintext:
            messages.warning(
                request,
                f"Figma API key for '{obj.name}': {plaintext} — "
                "copy it now, it will NOT be shown again.",
            )


@admin.register(TranslationHistory)
class TranslationHistoryAdmin(admin.ModelAdmin):
    list_display = [
        "created_at",
        "entry_key",
        "language",
        "change_type",
        "author_email",
        "author_name",
        "source",
        "old_value_short",
        "new_value_short",
    ]
    list_filter = ["source", "change_type", "language", "author_email"]
    search_fields = [
        "entry__key",
        "author_email",
        "author_name",
        "old_value",
        "new_value",
    ]
    readonly_fields = [
        "entry",
        "language",
        "change_type",
        "old_value",
        "new_value",
        "author_email",
        "author_name",
        "source",
        "created_at",
    ]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    @admin.display(
        description="Key",
        ordering="entry__key",
    )
    def entry_key(self, obj):
        return obj.entry.key

    @admin.display(description="Old Value")
    def old_value_short(self, obj):
        if obj.old_value:
            return (
                obj.old_value[:50] + "..." if len(obj.old_value) > 50 else obj.old_value
            )
        return "-"

    @admin.display(description="New Value")
    def new_value_short(self, obj):
        if obj.new_value:
            return (
                obj.new_value[:50] + "..." if len(obj.new_value) > 50 else obj.new_value
            )
        return "-"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class TranslationValueInline(admin.TabularInline):
    model = TranslationValue
    extra = 0
    fields = ["language", "value", "verified"]


@admin.register(TranslationEntry)
class TranslationEntryAdmin(admin.ModelAdmin):
    list_display = [
        "key",
        "comment",
        "en_value",
        "lb_value",
        "fr_value",
        "de_value",
        "en_verified",
        "llm_translated",
        "source",
        "revision",
        "deleted",
    ]
    list_filter = ["source", "deleted", "llm_translated"]
    search_fields = ["key", "comment", "values__value"]
    change_list_template = "admin/translations/change_list_with_lang.html"
    actions = [translate_with_llm]
    inlines = [TranslationValueInline]

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("values")

    @admin.display(description="English")
    def en_value(self, obj):
        return obj.get_value("en")

    @admin.display(description="Luxembourgish")
    def lb_value(self, obj):
        return obj.get_value("lb")

    @admin.display(description="French")
    def fr_value(self, obj):
        return obj.get_value("fr")

    @admin.display(description="German")
    def de_value(self, obj):
        return obj.get_value("de")

    @admin.display(description="English verified", boolean=True)
    def en_verified(self, obj):
        return obj.get_verified("en")

    def changelist_view(self, request, extra_context=None):
        lang = cache.get("admin_translation_lang", "en")
        extra_context = extra_context or {}
        extra_context["current_language"] = lang
        extra_context["languages"] = [
            (code, LANGUAGE_NAMES.get(code, code)) for code in SUPPORTED_LANGUAGES
        ]
        return super().changelist_view(request, extra_context=extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "set_translation_lang/",
                self.admin_site.admin_view(self.set_translation_lang),
                name="set_translation_lang",
            ),
            path(
                "llm_status/",
                self.admin_site.admin_view(self.llm_status_view),
                name="llm_translation_status",
            ),
            path(
                "collect_keys/",
                self.admin_site.admin_view(self.collect_keys_view),
                name="collect_translation_keys",
            ),
        ]
        return custom_urls + urls

    def collect_keys_view(self, request):
        """Collect error and notification keys from other services."""
        if request.method != "POST":
            return redirect("..")
        if not request.user.is_superuser and not request.user.is_staff:
            messages.error(request, "Permission denied.")
            return redirect("..")

        from .error_collector import collect_error_keys_from_services
        from .notification_collector import collect_notification_keys

        try:
            err = collect_error_keys_from_services()
            failed = ", ".join(s["name"] for s in err["services_failed"]) or "none"
            messages.success(
                request,
                f"Errors: {err['total_keys']} keys "
                f"({err['created']} created, {err['updated']} updated). "
                f"Failed: {failed}.",
            )
        except Exception as e:
            logger.exception("Error keys collection failed")
            messages.error(request, f"Error keys collection failed: {e}")

        try:
            notif = collect_notification_keys()
            messages.success(
                request,
                f"Notifications: {notif['total_keys']} keys "
                f"({notif['created']} created, {notif['updated']} updated).",
            )
        except Exception as e:
            logger.exception("Notification keys collection failed")
            messages.error(request, f"Notification keys collection failed: {e}")

        return redirect("..")

    def llm_status_view(self, request):
        """Return current LLM translation task status."""
        status = cache.get(LLM_TASK_CACHE_KEY) or {
            "status": "idle",
            "message": "No translation task running",
        }
        return JsonResponse(status)

    def set_translation_lang(self, request):
        if request.method == "POST":
            lang = request.POST.get("language")
            if lang:
                cache.set("admin_translation_lang", lang, timeout=None)
        from stapel_core.django.mounts import admin_index_url

        return redirect(request.headers.get("referer", admin_index_url()))
