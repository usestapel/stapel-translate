"""Action subscriptions of the translate module.

Handlers must be idempotent: delivery is at-least-once (outbox retries,
broker redelivery). Consumes contracts live in ``schemas/consumes/``.

- ``user.deleted`` (from stapel-auth/gdpr) — erase the translator record the
  deleted account's email owns.
- ``user.merged`` (from stapel-auth) — an explicit no-op; see
  :func:`handle_user_merged` for why this module holds nothing to re-parent.
"""
import logging

from stapel_core.comm import on_action

logger = logging.getLogger(__name__)


@on_action("user.deleted")
def handle_user_deleted(event):
    """Erase this module's PII when an account deletion is executed."""
    from .gdpr import TranslateGDPRProvider

    user_id = event.payload.get("user_id")
    if not user_id:
        logger.error("user.deleted event without user_id: %s", event.event_id)
        return
    TranslateGDPRProvider().delete(user_id)
    logger.info("translate data erased for deleted user %s", user_id)


@on_action("user.merged")
def handle_user_merged(event):
    """No rows are keyed by a user id here — nothing to re-parent.

    Written down rather than left out, because an absent handler and a
    deliberate no-op read the same from outside (``stapel_core.lifecycle.E001``).

    Every model in this module is addressed by something other than an
    account: ``TranslationEntry`` / ``TranslationValue`` by key and language,
    ``FigmaApiKey`` by its own digest, and the two that name a person —
    ``AuthorizedTranslator`` and ``TranslationHistory`` — by **email**, not by
    user id. The merge payload carries ids only, and ``from_user_id`` is
    already gone from auth by the time this arrives, so the guest's email is
    not even resolvable. Nor would it name anything: a translator record is
    granted to a staff address, which an anonymous guest session never has,
    and ``AuthorizedTranslator.email`` is unique — the survivor's own record,
    if any, already stands under the survivor's own address and a merge does
    not touch it.

    That makes this the honest answer rather than a convenient one: this
    module's data is not partitioned by account, so an account ceasing to
    exist moves nothing.
    """
    return None
