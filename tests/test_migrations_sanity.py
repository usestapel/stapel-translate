"""Sanity checks on the row-per-language migration plan.

The test settings disable migrations (tables come straight from models), so
the data migration cannot be exercised against a live DB here. These tests
statically verify the plan: model creation, reversible data copy, and the
exact set of removed columns.
"""

import importlib

from django.db import migrations as dj_migrations

LEGACY_LANGUAGES = [
    'en', 'lb', 'fr', 'de', 'es', 'pt', 'it', 'ru', 'uk', 'pl',
    'ar', 'hi', 'zh', 'tr', 'ko', 'ja', 'sr', 'hr', 'hu', 'he',
]


def _load(name):
    return importlib.import_module(f'stapel_translate.migrations.{name}')


class TestTranslationValueMigrations:
    def test_0017_creates_translationvalue_with_unique_constraint(self):
        module = _load('0017_translationvalue')
        ops = module.Migration.operations

        create = next(
            op for op in ops
            if isinstance(op, dj_migrations.CreateModel)
            and op.name == 'TranslationValue'
        )
        field_names = {name for name, _ in create.fields}
        assert {'entry', 'language', 'value', 'verified'} <= field_names

        constraint_ops = [
            op for op in ops if isinstance(op, dj_migrations.AddConstraint)
        ]
        assert constraint_ops, 'unique(entry, language) constraint missing'
        constraint = constraint_ops[0].constraint
        assert tuple(constraint.fields) == ('entry', 'language')

    def test_0018_data_migration_is_reversible(self):
        module = _load('0018_copy_language_columns_to_values')
        ops = module.Migration.operations
        assert len(ops) == 1
        op = ops[0]
        assert isinstance(op, dj_migrations.RunPython)
        assert op.code is module.copy_columns_to_rows
        assert op.reverse_code is module.copy_rows_to_columns
        assert module.LEGACY_LANGUAGES == LEGACY_LANGUAGES

    def test_0019_removes_exactly_the_40_columns(self):
        module = _load('0019_remove_language_columns')
        ops = module.Migration.operations
        assert all(isinstance(op, dj_migrations.RemoveField) for op in ops)
        assert all(op.model_name == 'translationentry' for op in ops)
        removed = {op.name for op in ops}
        expected = set(LEGACY_LANGUAGES) | {
            f'{lang}_verified' for lang in LEGACY_LANGUAGES
        }
        assert removed == expected
        assert len(ops) == 40

    def test_0020_wipes_keys_and_adds_hash_columns(self):
        module = _load('0020_figmaapikey_hashed_keys')
        ops = module.Migration.operations
        assert isinstance(ops[0], dj_migrations.RunPython)
        assert ops[0].code is module.wipe_existing_keys

        added = {
            op.name for op in ops if isinstance(op, dj_migrations.AddField)
        }
        assert added == {'key_hash', 'prefix'}

    def test_dependency_chain(self):
        assert _load('0018_copy_language_columns_to_values').Migration.dependencies == [
            ('translate', '0017_translationvalue')
        ]
        assert _load('0019_remove_language_columns').Migration.dependencies == [
            ('translate', '0018_copy_language_columns_to_values')
        ]
        assert _load('0020_figmaapikey_hashed_keys').Migration.dependencies == [
            ('translate', '0019_remove_language_columns')
        ]
