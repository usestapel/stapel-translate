"""Report missing (key, language) translation counts — the CI gate.

Exits 1 when the backlog is non-empty, so a pipeline step like

    manage.py collect_translations
    manage.py translation_backlog

fails the build until translations are filled (manually or via the
``translate.autofill`` task).
"""

import json
import sys

from django.core.management.base import BaseCommand

from stapel_translate.conf import get_supported_languages
from stapel_translate.models import TranslationEntry, TranslationValue


def backlog_counts(languages=None):
    """{lang: missing_count} plus the total number of active entries."""
    languages = languages or get_supported_languages()
    total_entries = TranslationEntry.objects.filter(deleted=False).count()
    rows = (
        TranslationValue.objects.filter(entry__deleted=False)
        .exclude(value="")
        .values_list("language", flat=True)
    )
    translated = {}
    for lang in rows:
        translated[lang] = translated.get(lang, 0) + 1
    return {
        lang: total_entries - translated.get(lang, 0) for lang in languages
    }, total_entries


class Command(BaseCommand):
    help = "Print missing (key, language) counts per language; exit 1 if non-empty."

    def add_arguments(self, parser):
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Machine-readable JSON output.",
        )
        parser.add_argument(
            "--languages",
            help="Comma-separated language codes to check (default: configured).",
        )

    def handle(self, *args, **options):
        languages = None
        if options["languages"]:
            languages = [
                lang.strip()
                for lang in options["languages"].split(",")
                if lang.strip()
            ]
        counts, total_entries = backlog_counts(languages)
        total_missing = sum(counts.values())

        if options["as_json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "total_entries": total_entries,
                        "total_missing": total_missing,
                        "languages": counts,
                    },
                    ensure_ascii=False,
                )
            )
        else:
            self.stdout.write(f"Translation entries: {total_entries}")
            for lang, missing in counts.items():
                mark = "OK " if missing == 0 else "MISS"
                self.stdout.write(f"  [{mark}] {lang}: {missing} missing")
            self.stdout.write(f"Total backlog: {total_missing}")

        if total_missing > 0:
            sys.exit(1)
