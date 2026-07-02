"""Load Stapel's builtin translation fixtures.

Idempotent upsert of the framework's own string catalog (error keys,
notification templates) with curated translations for every default
language — so users never re-run AI over Stapel's builtin strings.

- Creates missing TranslationEntry rows with ``source="stapel:builtin"``.
- Creates missing/empty TranslationValue rows with ``verified=True``.
- NEVER overwrites an existing value that differs from the fixture
  (user edits win). ``--force`` overwrites values of builtin-sourced
  entries only.
- Loads only languages present in ``translate_settings.LANGUAGES``.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from stapel_translate.conf import get_supported_languages
from stapel_translate.models import TranslationEntry

BUILTIN_SOURCE = "stapel:builtin"
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "builtin"


class Command(BaseCommand):
    help = "Load Stapel's builtin translation fixtures (idempotent upsert)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Overwrite differing values on builtin-sourced entries "
                "(entries with source=%r). User-created/collected entries "
                "are never overwritten." % BUILTIN_SOURCE
            ),
        )

    def handle(self, *args, **options):
        force = options["force"]

        en_path = FIXTURES_DIR / "en.json"
        if not en_path.exists():
            raise CommandError(f"builtin fixtures not found at {FIXTURES_DIR}")
        catalog = json.loads(en_path.read_text(encoding="utf-8"))

        configured = get_supported_languages()
        fixtures = {}
        skipped_languages = []
        for lang in configured:
            path = FIXTURES_DIR / f"{lang}.json"
            if path.exists():
                fixtures[lang] = json.loads(path.read_text(encoding="utf-8"))
            else:
                skipped_languages.append(lang)

        entries_created = 0
        entries_skipped_deleted = 0
        values_created = 0
        values_overwritten = 0
        values_skipped = 0

        for key, english_text in catalog.items():
            entry, created = TranslationEntry.objects.get_or_create(
                key=key,
                defaults={
                    "source": BUILTIN_SOURCE,
                    "comment": "Stapel builtin",
                },
            )
            if created:
                entries_created += 1
            elif entry.deleted:
                # The project deliberately removed this key — leave it alone.
                entries_skipped_deleted += 1
                continue

            builtin_owned = entry.source == BUILTIN_SOURCE
            for lang, translations in fixtures.items():
                fixture_value = translations.get(key)
                if not fixture_value:
                    continue
                current = entry.get_value(lang)
                if not current:
                    entry.set_value(lang, fixture_value, verified=True)
                    values_created += 1
                elif current == fixture_value:
                    continue  # already loaded — idempotent no-op
                elif force and builtin_owned:
                    entry.set_value(lang, fixture_value, verified=True)
                    values_overwritten += 1
                else:
                    values_skipped += 1  # user edit wins

        self.stdout.write(
            self.style.SUCCESS(
                f"Builtin translations loaded: {len(catalog)} keys, "
                f"{len(fixtures)} languages ({', '.join(fixtures)})."
            )
        )
        self.stdout.write(
            f"Entries: {entries_created} created, "
            f"{entries_skipped_deleted} skipped (soft-deleted)."
        )
        self.stdout.write(
            f"Values: {values_created} created, "
            f"{values_overwritten} overwritten (--force), "
            f"{values_skipped} kept (user edits win)."
        )
        if skipped_languages:
            self.stdout.write(
                self.style.WARNING(
                    "No builtin fixture for configured language(s): "
                    + ", ".join(skipped_languages)
                )
            )
