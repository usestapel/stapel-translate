"""Start (or run inline) the ``translate.autofill`` comm task.

Default mode enqueues the task through ``stapel_core.comm.start`` — the
work happens wherever the taskstore executor runs, so it goes through the
same caller check as any other peer and needs ``--caller-service``.
``--sync`` runs the autofill inline in this process, where the shell is
the authority, and prints the stats.
"""

from django.core.management.base import BaseCommand, CommandError

from stapel_translate.tasks import AUTOFILL_TASK, CallerNotAuthorized, authorize_caller


class Command(BaseCommand):
    help = "Fill missing translations via the configured LLM provider."

    def add_arguments(self, parser):
        parser.add_argument(
            "--languages",
            help="Comma-separated language codes to fill (default: all configured).",
        )
        parser.add_argument(
            "--keys",
            help="Comma-separated translation keys to restrict to.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of values to fill in this run.",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run inline in this process instead of starting a comm task.",
        )
        parser.add_argument(
            "--caller-service",
            help=(
                "Service name to start the comm task as; must be listed in "
                "STAPEL_TRANSLATE['INTERNAL_TRUSTED_SERVICES']. Not needed "
                "with --sync."
            ),
        )

    def handle(self, *args, **options):
        payload = {}
        if options["languages"]:
            payload["languages"] = [
                lang.strip()
                for lang in options["languages"].split(",")
                if lang.strip()
            ]
        if options["keys"]:
            payload["keys"] = [
                key.strip() for key in options["keys"].split(",") if key.strip()
            ]
        if options["limit"] is not None:
            payload["limit"] = options["limit"]

        if options["sync"]:
            from stapel_translate.autofill import autofill_missing

            stats = autofill_missing(
                languages=payload.get("languages"),
                keys=payload.get("keys"),
                limit=payload.get("limit"),
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Autofill done: {stats['filled']} filled, "
                    f"{stats['failed']} failed."
                )
            )
            for lang, count in sorted(stats["languages"].items()):
                self.stdout.write(f"  {lang}: {count} filled")
            for err in stats["errors"]:
                self.stderr.write(self.style.WARNING(f"  {err}"))
            return

        payload["caller_service"] = options["caller_service"] or ""
        # Decide here rather than let the refusal happen inside the task:
        # `start()` would report a task id and the work would simply never
        # run, which is the silent failure this check exists to prevent.
        try:
            authorize_caller(payload)
        except CallerNotAuthorized as exc:
            raise CommandError(f"{exc}. Use --sync to run inline instead.") from exc

        from stapel_core.comm import start

        task_id = start(AUTOFILL_TASK, payload)
        self.stdout.write(
            self.style.SUCCESS(f"Started task {AUTOFILL_TASK}: {task_id}")
        )
