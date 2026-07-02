"""Run every registered translation-key collector.

CLI/CI counterpart of the dashboard's "Collect keys" button — runs the
same collector functions (error keys from all services, notification
templates) plus any project-registered collectors.
"""

import sys

from django.core.management.base import BaseCommand

from stapel_translate.collectors import get_collectors


class Command(BaseCommand):
    help = "Collect translation keys from all registered collectors."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            help="Comma-separated collector names to run (default: all).",
        )

    def handle(self, *args, **options):
        collectors = get_collectors()
        if options["only"]:
            wanted = [n.strip() for n in options["only"].split(",") if n.strip()]
            unknown = [n for n in wanted if n not in collectors]
            if unknown:
                self.stderr.write(
                    self.style.ERROR(
                        f"Unknown collector(s): {', '.join(unknown)}. "
                        f"Registered: {', '.join(collectors)}."
                    )
                )
                sys.exit(1)
            collectors = {n: collectors[n] for n in wanted}

        any_failed = False
        for name, collector in collectors.items():
            try:
                stats = collector()
            except Exception as exc:
                any_failed = True
                self.stderr.write(self.style.ERROR(f"{name}: FAILED — {exc}"))
                continue

            summary = ", ".join(
                f"{k}={v}"
                for k, v in stats.items()
                if isinstance(v, (int, str))
            )
            self.stdout.write(self.style.SUCCESS(f"{name}: {summary}"))
            failed_services = stats.get("services_failed") or []
            if failed_services:
                any_failed = True
                for row in failed_services:
                    self.stderr.write(
                        self.style.WARNING(
                            f"{name}: service {row.get('name')} failed — "
                            f"{row.get('error')}"
                        )
                    )

        if any_failed:
            sys.exit(1)
