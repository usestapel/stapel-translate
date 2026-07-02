"""Dump translations from the DB into repo fixture files.

The inverse of ``load_builtin_translations``: writes one JSON file per
language (``{key: text}``, sorted keys, 2-space indent, UTF-8 with
``ensure_ascii=False``, trailing newline) so a repo diff is reviewable and
two consecutive dumps are byte-identical.

    manage.py dump_translations --out fixtures/builtin \
        [--source backend:notifications] [--languages en,de] [--verified-only]

Soft-deleted entries and empty values are never dumped, so
``dump_translations`` followed by ``load_builtin_translations`` on a clean
DB reproduces the same values.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stapel_translate.conf import get_supported_languages
from stapel_translate.models import TranslationEntry


class Command(BaseCommand):
    help = "Dump translations from the DB into per-language JSON fixture files."

    def add_arguments(self, parser):
        parser.add_argument(
            "--out",
            required=True,
            help="Output directory for the per-language JSON files.",
        )
        parser.add_argument(
            "--source",
            action="append",
            default=None,
            help=(
                "Only dump entries with this source (e.g. backend:notifications). "
                "May be given multiple times."
            ),
        )
        parser.add_argument(
            "--languages",
            default=None,
            help=(
                "Comma-separated language codes to dump "
                "(default: all configured languages)."
            ),
        )
        parser.add_argument(
            "--verified-only",
            action="store_true",
            help="Only dump values marked as verified.",
        )

    def handle(self, *args, **options):
        configured = get_supported_languages()
        if options["languages"]:
            languages = [
                lang.strip()
                for lang in options["languages"].split(",")
                if lang.strip()
            ]
            unknown = [lang for lang in languages if lang not in configured]
            if unknown:
                raise CommandError(
                    "unknown language(s): %s (configured: %s)"
                    % (", ".join(unknown), ", ".join(configured))
                )
        else:
            languages = list(configured)

        entries = TranslationEntry.objects.filter(deleted=False)
        if options["source"]:
            entries = entries.filter(source__in=options["source"])
        entries = entries.prefetch_related("values")

        catalogs: dict[str, dict[str, str]] = {lang: {} for lang in languages}
        for entry in entries:
            for lang in languages:
                if options["verified_only"] and not entry.get_verified(lang):
                    continue
                value = entry.get_value(lang)
                if value:
                    catalogs[lang][entry.key] = value

        out = Path(options["out"])
        out.mkdir(parents=True, exist_ok=True)

        files_written = 0
        values_dumped = 0
        for lang in languages:
            catalog = catalogs[lang]
            if not catalog:
                continue  # no file for a language without values
            content = (
                json.dumps(
                    dict(sorted(catalog.items())),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            (out / f"{lang}.json").write_text(content, encoding="utf-8")
            files_written += 1
            values_dumped += len(catalog)

        self.stdout.write(
            self.style.SUCCESS(
                f"Dumped {values_dumped} value(s) across "
                f"{files_written} language file(s) to {out}/"
            )
        )
        skipped = [lang for lang in languages if not catalogs[lang]]
        if skipped:
            self.stdout.write(
                self.style.WARNING(
                    "No values to dump for language(s): " + ", ".join(skipped)
                )
            )
