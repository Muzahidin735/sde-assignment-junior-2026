from datetime import timedelta

from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from webhooks.models import WebhookEvent
from telephony.models import CallAttempt, ActiveCallReservation, DNDPhone
from leads.models import Lead
from telephony.clock import get_simulated_now



def process_webhook_event(event_id):
    with transaction.atomic():
        event = WebhookEvent.objects.select_for_update().get(
            pk=event_id
        )

        if event.processing_status == WebhookEvent.ProcessingStatus.PROCESSED:
            return

        attempt = CallAttempt.objects.select_for_update().filter(
            request_id=event.request_id
        ).first()

        if attempt is None:
            return

        payload = event.payload

        attempt.call_sid = payload["call_sid"]
        attempt.submission_state = CallAttempt.SubmissionState.ACCEPTED
        attempt.provider_status = payload["status"]

        effective_disposition = (
            payload.get("disposition") or payload.get("status")
        )

        attempt.disposition = effective_disposition
        attempt.started_at = parse_datetime(payload["started_at"]) if payload.get("started_at") else None
        attempt.ended_at = parse_datetime(payload["ended_at"]) if payload.get("ended_at") else None
        attempt.callback_at = parse_datetime(payload["callback_at"]) if payload.get("callback_at") else None
        attempt.save()

        ActiveCallReservation.objects.filter(
            attempt=attempt
        ).delete()

        lead = attempt.lead
        disposition = attempt.disposition
        ended_at = attempt.ended_at or get_simulated_now()

        if disposition == CallAttempt.Disposition.DND:
            DNDPhone.objects.get_or_create(phone=lead.phone)

            Lead.objects.filter(
                phone=lead.phone,
                status=Lead.Status.PENDING,
            ).exclude(pk=lead.pk).update(
                status=Lead.Status.DND_BLOCKED,
                callback_at=None,
                next_eligible_at=None,
            )
        # Terminal outcomes
        if disposition in (
            CallAttempt.Disposition.INTERESTED,
            CallAttempt.Disposition.NOT_INTERESTED,
            CallAttempt.Disposition.WRONG_NUMBER,
            CallAttempt.Disposition.DND,
        ):
            lead.status = Lead.Status.COMPLETED
            lead.callback_at = None
            lead.next_eligible_at = None
            lead.save()

        # Retry outcomes
        elif disposition in (
            CallAttempt.Disposition.NO_ANSWER,
            CallAttempt.Disposition.BUSY,
            CallAttempt.Disposition.FAILED,
        ):
            delay = (
                timedelta(minutes=15)
                if disposition == CallAttempt.Disposition.FAILED
                else timedelta(minutes=60)
            )
            lead.next_eligible_at = ended_at + delay
            lead.callback_at = None
            lead.save()

        # Callback requested
        elif disposition == CallAttempt.Disposition.CALLBACK_REQUESTED:
            lead.callback_at = attempt.callback_at
            lead.next_eligible_at = None
            lead.save()

        if (
            lead.status == Lead.Status.PENDING
            and lead.call_attempts.filter(
                submission_state=CallAttempt.SubmissionState.ACCEPTED
            ).count() >= lead.campaign.max_attempts
        ):
            lead.status = Lead.Status.EXHAUSTED
            lead.callback_at = None
            lead.next_eligible_at = None
            lead.save()
        event.processing_status = WebhookEvent.ProcessingStatus.PROCESSED
        event.processed_at = timezone.now()
        event.save(update_fields=["processing_status", "processed_at"])

