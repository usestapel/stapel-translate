"""``user.merged`` — a declared no-op, and the check that keeps it declared.

stapel-auth absorbs an anonymous guest into an existing account and deletes
the guest row. Every other library in the fleet answers that by re-parenting
the guest's rows; this one answers "there are none", and the point of these
tests is that the claim is *checked* rather than asserted in prose:

* every model here is addressed by key, language, digest or email — never by
  a user id, so the payload names nothing this module could move;
* the handler accepts a well-formed and a malformed event without raising,
  because an escaping exception is a poison pill on an at-least-once bus;
* the subscription is really registered, which is what makes
  ``stapel_core.lifecycle.E001`` green for this app.
"""
import types

import pytest
from django.apps import apps
from django.core.exceptions import FieldDoesNotExist

from stapel_translate.actions import handle_user_merged


def _event(payload, event_id="evt-merge"):
    return types.SimpleNamespace(payload=payload, event_id=event_id)


def _merged(from_user_id="8f1d0d3e-0000-4000-8000-000000000001",
            into_user_id="8f1d0d3e-0000-4000-8000-000000000002"):
    return _event(
        {
            "from_user_id": from_user_id,
            "into_user_id": into_user_id,
            "reason": "anonymous_promotion",
        }
    )


class TestNothingHereIsKeyedByAUser:
    """The premise of the no-op, asserted against the models themselves."""

    def test_no_model_carries_a_user_column(self):
        from django.conf import settings

        offenders = []
        for model in apps.get_app_config("translate").get_models():
            for field in model._meta.get_fields():
                name = getattr(field, "name", "") or ""
                remote = getattr(field, "related_model", None)
                if remote is not None and remote._meta.label == settings.AUTH_USER_MODEL:
                    offenders.append(f"{model.__name__}.{name} -> AUTH_USER_MODEL")
                elif name in {"user_id", "owner_id", "author_id", "actor_id"}:
                    offenders.append(f"{model.__name__}.{name}")
        assert offenders == [], (
            "a user-keyed column appeared in stapel-translate: handle_user_merged "
            f"must re-parent it instead of returning, {offenders}"
        )

    def test_the_two_person_shaped_columns_are_emails_not_ids(self):
        """Which is why a payload of ids cannot address them."""
        from stapel_translate.models import AuthorizedTranslator, TranslationHistory

        assert AuthorizedTranslator._meta.get_field("email").unique is True
        assert TranslationHistory._meta.get_field("author_email")
        for model, column in (
            (AuthorizedTranslator, "user"),
            (TranslationHistory, "author"),
        ):
            with pytest.raises(FieldDoesNotExist):
                model._meta.get_field(column)


class TestTheHandlerNeverRaises:
    """A raise is redelivery forever; no payload may cause one."""

    @pytest.mark.django_db
    def test_a_well_formed_event_is_accepted(self):
        assert handle_user_merged(_merged()) is None

    @pytest.mark.django_db
    def test_a_malformed_id_is_accepted(self):
        """``not-a-uuid`` is the shape that raises ``ValidationError`` (not
        ``ValueError``) wherever a UUID column is filtered on it."""
        assert handle_user_merged(_merged(from_user_id="not-a-uuid")) is None
        assert handle_user_merged(_merged(into_user_id="not-a-uuid")) is None

    @pytest.mark.django_db
    def test_missing_ids_and_an_empty_payload_are_accepted(self):
        assert handle_user_merged(_event({"into_user_id": "x"})) is None
        assert handle_user_merged(_event({"from_user_id": "x"})) is None
        assert handle_user_merged(_event({})) is None

    @pytest.mark.django_db
    def test_a_redelivery_is_the_same_no_op(self):
        event = _merged()
        assert handle_user_merged(event) is None
        assert handle_user_merged(event) is None


class TestTheSubscriptionExists:
    def test_user_merged_is_registered(self):
        from stapel_core.comm import action_registry

        assert handle_user_merged in action_registry.handlers("user.merged")

    def test_the_lifecycle_pair_check_is_green(self):
        """``stapel_core.lifecycle.E001`` — one half of an account's life
        cycle answered and not the other is an ERROR as of core 0.52.x."""
        from stapel_core.comm.lifecycle_checks import check_lifecycle_pairs

        assert check_lifecycle_pairs() == []

    def test_the_consumes_schema_is_committed(self):
        import json
        from pathlib import Path

        path = (
            Path(__file__).resolve().parent.parent
            / "schemas" / "consumes" / "user.merged.json"
        )
        schema = json.loads(path.read_text())
        assert schema["title"] == "user.merged"
        assert set(schema["required"]) == {"from_user_id", "into_user_id"}
