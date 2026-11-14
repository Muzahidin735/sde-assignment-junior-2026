import time

from django.core.management.base import BaseCommand

from telephony.dispatcher import CampaignDispatcher
from webhooks.models import WebhookEvent
from webhooks.processor import process_webhook_event
from leads.models import Lead

class Command(BaseCommand):
    help = "Run the durable campaign dispatcher"

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run one dispatch cycle and exit",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="Seconds to wait between polling cycles",
        )

    def handle(self, *args, **options):
        dispatcher = CampaignDispatcher()
        run_once = options["once"]
        interval = options["interval"]

        try:
            self.stdout.write(
                self.style.SUCCESS("Campaign dispatcher started.")
            )

            while True:
                pending_events = WebhookEvent.objects.filter(
                    processing_status=WebhookEvent.ProcessingStatus.PENDING
                ).order_by("received_at")

                for event in pending_events:
                    process_webhook_event(event.id)

                dispatcher.reconcile_unknown_attempts()
                dispatcher.reconcile_active_attempts()

                all_finished = not Lead.objects.exclude(
                    status__in=[
                        Lead.Status.COMPLETED,
                        Lead.Status.EXHAUSTED,
                        Lead.Status.DND_BLOCKED,
                    ]
                ).exists()

                if all_finished:
                    self.stdout.write(
                        self.style.SUCCESS("All leads have reached final states.")
                    )
                    break

                lead = dispatcher.get_next_eligible_lead()

                if lead:
                    dispatcher.dispatch_lead(lead)
                    continue

                if run_once:
                    break

                time.sleep(interval)

        except KeyboardInterrupt:
            self.stdout.write("Dispatcher stopped.")

        finally:
            dispatcher.close()