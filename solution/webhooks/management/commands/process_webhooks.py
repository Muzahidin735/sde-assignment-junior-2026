from django.core.management.base import BaseCommand

from webhooks.models import WebhookEvent
from webhooks.processor import process_webhook_event


class Command(BaseCommand):
    help = "Process pending webhook events"

    def handle(self, *args, **options):
        events = WebhookEvent.objects.filter(
            processing_status=WebhookEvent.ProcessingStatus.PENDING
        ).order_by("received_at")

        processed_count = 0

        for event in events:
            process_webhook_event(event.id)
            processed_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Processed {processed_count} pending webhook events."
            )
        )