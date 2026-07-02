"""Edge-case tests for the dashboard export/import views."""

import json
import zipfile
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from stapel_core.django.users.models import User
from stapel_translate import dashboard_views
from stapel_translate.dashboard_views import DashboardExportView, DashboardImportView
from stapel_translate.models import TranslationEntry


@pytest.fixture
def staff_user(db):
    return User.objects.create_user(
        username="exportstaff", email="export@example.com", password="x", is_staff=True
    )


@pytest.fixture
def factory():
    return RequestFactory()


@pytest.fixture
def mock_messages(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(dashboard_views, "messages", mock)
    return mock


def _post(factory, user, path, data=None):
    request = factory.post(path, data or {})
    request.user = user
    return request


@pytest.mark.django_db
class TestDashboardExport:
    def test_json_export_zip_contains_all_languages(self, factory, staff_user):
        entry = TranslationEntry.objects.create(key="exp.key", source="app:x")
        entry.set_value("en", "Hello")

        request = _post(factory, staff_user, "/translate/dashboard/export/", {"format": "json"})
        response = DashboardExportView.as_view()(request)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/zip"
        zf = zipfile.ZipFile(BytesIO(response.content))
        assert "en.json" in zf.namelist()
        data = json.loads(zf.read("en.json"))
        assert data == {"exp.key": "Hello"}
        # language without values exports as an empty dict, not a crash
        assert json.loads(zf.read("de.json")) == {}

    def test_xml_export_escapes_and_uses_default_locale_for_en(self, factory, staff_user):
        entry = TranslationEntry.objects.create(key="exp.xml key!")
        entry.set_value("en", "It's \"quoted\"\nnew line")

        request = _post(factory, staff_user, "/translate/dashboard/export/", {"format": "xml"})
        response = DashboardExportView.as_view()(request)

        zf = zipfile.ZipFile(BytesIO(response.content))
        assert "values/strings.xml" in zf.namelist()  # en is the default locale
        assert "values-de/strings.xml" in zf.namelist()
        xml = zf.read("values/strings.xml").decode()
        assert 'name="exp_xml_key"' in xml
        assert "\\'" in xml and "\\n" in xml

    def test_fixture_export_inlines_language_columns(self, factory, staff_user):
        entry = TranslationEntry.objects.create(key="exp.fixture")
        entry.set_value("en", "Hello", verified=True)

        request = _post(
            factory, staff_user, "/translate/dashboard/export/", {"format": "fixture"}
        )
        response = DashboardExportView.as_view()(request)

        assert response["Content-Type"] == "application/json"
        data = json.loads(response.content)
        fields = data[0]["fields"]
        assert fields["en"] == "Hello"
        assert fields["en_verified"] is True


@pytest.mark.django_db
class TestDashboardImport:
    def test_import_without_file_reports_error(self, factory, staff_user, mock_messages):
        request = _post(factory, staff_user, "/translate/dashboard/import/")
        response = DashboardImportView.as_view()(request)

        assert response.status_code == 302
        mock_messages.error.assert_called_once()
        assert "No file uploaded" in mock_messages.error.call_args[0][1]

    def test_import_malformed_json_reports_error(self, factory, staff_user, mock_messages):
        upload = SimpleUploadedFile("fixture.json", b"{not json")
        request = factory.post("/translate/dashboard/import/", {"fixture_file": upload})
        request.user = staff_user
        response = DashboardImportView.as_view()(request)

        assert response.status_code == 302
        assert "Invalid JSON file" in mock_messages.error.call_args[0][1]
        assert TranslationEntry.objects.count() == 0

    def test_import_empty_file_reports_error(self, factory, staff_user, mock_messages):
        upload = SimpleUploadedFile("fixture.json", b"")
        request = factory.post("/translate/dashboard/import/", {"fixture_file": upload})
        request.user = staff_user
        response = DashboardImportView.as_view()(request)

        assert response.status_code == 302
        assert "Invalid JSON file" in mock_messages.error.call_args[0][1]

    def test_import_counts_good_rows_unknown_languages_and_errors(
        self, factory, staff_user, mock_messages
    ):
        existing = TranslationEntry.objects.create(key="imp.existing", deleted=True)
        payload = [
            {
                "model": "translate.translationentry",
                "fields": {
                    "key": "imp.new",
                    "source": "app:x",
                    "en": "Hello",
                    "en_verified": True,
                    "xx": "unknown language column is ignored",
                    "id": 424242,  # excluded field, must not break the row
                },
            },
            {"model": "translate.translationentry", "fields": {"key": "imp.existing"}},
            {"model": "translate.translationentry", "fields": {"no_key": True}},
        ]
        upload = SimpleUploadedFile(
            "fixture.json", json.dumps(payload).encode("utf-8")
        )
        request = factory.post("/translate/dashboard/import/", {"fixture_file": upload})
        request.user = staff_user
        response = DashboardImportView.as_view()(request)

        assert response.status_code == 302
        summary = mock_messages.success.call_args[0][1]
        assert "1 created" in summary
        assert "1 updated" in summary
        assert "1 errors" in summary

        created = TranslationEntry.objects.get(key="imp.new")
        assert created.source == "app:x"
        assert created.get_value("en") == "Hello"
        assert created.get_verified("en") is True
        assert created.get_value("xx") is None

        existing.refresh_from_db()
        assert existing.deleted is False  # import reactivates entries
