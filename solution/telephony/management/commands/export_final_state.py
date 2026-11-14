import csv

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from leads.models import Lead
from telephony.models import CallAttempt


class Command(BaseCommand):
    help = "Export final campaign and lead states to CSV"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="final_state.csv",
            help="Output CSV file path",
        )

    def handle(self, *args, **options):
        pending_count = Lead.objects.filter(
            status=Lead.Status.PENDING
        ).count()

        if pending_count:
            raise CommandError(
                f"Cannot export: {pending_count} leads are still pending."
            )

        output_path = Path(options["output"])

        leads = Lead.objects.select_related(
            "campaign"
        ).prefetch_related(
            "call_attempts"
        ).order_by(
            "campaign__campaign_id",
            "lead_id",
        )

        with output_path.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as csvfile:
            writer = csv.writer(csvfile)

            writer.writerow([
                "campaign_id",
                "lead_id",
                "final_state",
                "attempts",
                "last_status",
                "last_disposition",
            ])

            for lead in leads:
                attempts = list(lead.call_attempts.all())

                accepted_attempts = [
                    attempt
                    for attempt in attempts
                    if attempt.submission_state
                    == CallAttempt.SubmissionState.ACCEPTED
                ]

                last_attempt = max(
                    accepted_attempts,
                    key=lambda attempt: attempt.attempt_number,
                    default=None,
                )

                writer.writerow([
                    lead.campaign.campaign_id,
                    lead.lead_id,
                    lead.status,
                    len(accepted_attempts),
                    last_attempt.provider_status if last_attempt else "",
                    last_attempt.disposition if last_attempt else "",
                ])

        self.stdout.write(
            self.style.SUCCESS(
                f"Final state exported to: {output_path.resolve()}"
            )
        )