import httpx

from django.db import IntegrityError, transaction

from leads.models import Lead
from tenants.models import Tenant
from telephony.models import CallAttempt, ActiveCallReservation, DNDPhone
from telephony.clock import get_simulated_now
from telephony.scheduling import (
    get_next_eligible_time,
    get_priority,
)

import hashlib
import json

from webhooks.models import WebhookEvent
from webhooks.processor import process_webhook_event


class CampaignDispatcher:
    PROVIDER_URL = "http://127.0.0.1:8099"

    def __init__(self):
        self.client = httpx.Client(
            base_url=self.PROVIDER_URL,
            timeout=10.0,
        )

    def close(self):
        self.client.close()

    def get_current_time(self):
        return get_simulated_now()
    
    def get_eligible_leads(self):
        blocked_phones = DNDPhone.objects.values_list("phone", flat=True)

        return (
            Lead.objects.filter(status=Lead.Status.PENDING)
            .exclude(phone__in=blocked_phones)
            .select_related("campaign", "campaign__tenant")
            .order_by("created_at")
        )

    def get_next_eligible_lead(self):
        now = self.get_current_time()
        candidates = []

        for lead in self.get_eligible_leads():
            has_active_call = ActiveCallReservation.objects.filter(
                phone=lead.phone
            ).exists()

            if has_active_call:
                continue
            eligible_at = lead.callback_at or lead.next_eligible_at

            scheduled_at = get_next_eligible_time(
                lead.campaign,
                now,
                eligible_at,
            )

            if scheduled_at is None or scheduled_at > now:
                continue

            candidates.append((
                get_priority(lead),
                lead.created_at,
                lead,
            ))

        if not candidates:
            return None

        candidates.sort(key=lambda item: (item[0], item[1]))

        return candidates[0][2]

    def get_accepted_attempt_count(self, lead):
        return lead.call_attempts.filter(
            submission_state=CallAttempt.SubmissionState.ACCEPTED
        ).count()

    def has_attempts_remaining(self, lead):
        accepted_attempts = self.get_accepted_attempt_count(lead)

        return accepted_attempts < lead.campaign.max_attempts

    def get_next_attempt_number(self, lead):
        last_attempt = lead.call_attempts.order_by(
            "-attempt_number"
        ).first()

        if last_attempt is None:
            return 1

        if last_attempt.submission_state in (
            CallAttempt.SubmissionState.PREPARED,
            CallAttempt.SubmissionState.UNKNOWN,
        ):
            return last_attempt.attempt_number

        return last_attempt.attempt_number + 1

    def get_or_create_attempt(self, lead):
        attempt_number = self.get_next_attempt_number(lead)

        attempt, created = CallAttempt.objects.get_or_create(
            lead=lead,
            attempt_number=attempt_number,
        )

        return attempt

    def reserve_call(self, lead, attempt):
        with transaction.atomic():
            tenant = Tenant.objects.select_for_update().get(
                pk=lead.campaign.tenant_id
            )

            # Reuse an existing reservation after a restart.
            existing_reservation = ActiveCallReservation.objects.filter(
                attempt=attempt
            ).exists()

            if existing_reservation:
                return True

            # Check tenant-wide concurrency across all campaigns.
            active_count = ActiveCallReservation.objects.filter(
                tenant=tenant
            ).count()

            if active_count >= tenant.max_concurrent_calls:
                return False

            # Reserve the phone number globally.
            try:
                with transaction.atomic():
                    ActiveCallReservation.objects.create(
                        phone=lead.phone,
                        tenant=tenant,
                        attempt=attempt,
                    )
            except IntegrityError:
                return False

            return True

    def release_reservation(self, attempt):
        ActiveCallReservation.objects.filter(
            attempt=attempt
        ).delete()

    def get_webhook_url(self):
        return "http://127.0.0.1:8000/webhooks/call-result/"

    def submit_call(self, attempt):
        lead = attempt.lead

        payload = {
            "request_id": str(attempt.request_id),
            "campaign_id": lead.campaign.campaign_id,
            "lead_id": lead.lead_id,
            "phone": lead.phone,
            "callback_url": self.get_webhook_url(),
        }

        try:
            return self.client.post("/v1/calls", json=payload)
        except httpx.RequestError:
            self.handle_unknown_response(attempt)
            return None

    def handle_accepted_response(self, attempt, response_data):
        with transaction.atomic():
            attempt = CallAttempt.objects.select_for_update().get(
                pk=attempt.pk
            )

            attempt.call_sid = response_data["call_sid"]
            attempt.submission_state = CallAttempt.SubmissionState.ACCEPTED

            if attempt.accepted_at is None:
                attempt.accepted_at = self.get_current_time()

            attempt.save(
                update_fields=[
                    "call_sid",
                    "submission_state",
                    "accepted_at",
                    "updated_at",
                ]
            )

    def handle_unknown_response(self, attempt):
        with transaction.atomic():
            attempt = CallAttempt.objects.select_for_update().get(
                pk=attempt.pk
            )

            # A webhook may already have confirmed provider acceptance.
            # Never overwrite that confirmed state with UNKNOWN.
            if attempt.submission_state == CallAttempt.SubmissionState.ACCEPTED:
                return

            attempt.submission_state = CallAttempt.SubmissionState.UNKNOWN
            attempt.save(
                update_fields=["submission_state", "updated_at"]
            )

    def reconcile_attempt(self, attempt):
        if not attempt.call_sid:
            response = self.client.get(
                "/v1/calls",
                params={"request_id": str(attempt.request_id)},
            )

            if response.status_code == 404:
                return False

            response.raise_for_status()
            call_data = response.json()
            self.handle_accepted_response(attempt, call_data)
            attempt.refresh_from_db()

        response = self.client.get(
            f"/v1/calls/{attempt.call_sid}"
        )

        if response.status_code == 404:
            return False

        response.raise_for_status()
        call_data = response.json()

        if call_data["state"] == "active":
            return True

        if call_data["state"] == "ended":
            result = call_data["result"]

            payload_hash = hashlib.sha256(
                json.dumps(result, sort_keys=True).encode("utf-8")
            ).hexdigest()

            event, _ = WebhookEvent.objects.get_or_create(
                request_id=result["request_id"],
                call_sid=result["call_sid"],
                event_type=result["event"],
                defaults={
                    "payload_hash": payload_hash,
                    "payload": result,
                },
            )

            process_webhook_event(event.id)
            return True

    def handle_rejected_response(self, attempt):
        attempt.submission_state = CallAttempt.SubmissionState.REJECTED
        attempt.save(
            update_fields=["submission_state", "updated_at"]
        )

        self.release_reservation(attempt)

    def process_provider_response(self, attempt, response):
        if response is None:
            return

        if response.status_code in (200, 201):
            self.handle_accepted_response(attempt, response.json())

        elif response.status_code in (409, 422, 429, 503):
            self.handle_rejected_response(attempt)

        elif response.status_code == 504:
            self.handle_unknown_response(attempt)

        else:
            response.raise_for_status()

    def reconcile_unknown_attempts(self):
        attempts = CallAttempt.objects.filter(
            submission_state=CallAttempt.SubmissionState.UNKNOWN
        ).select_related("lead", "lead__campaign")

        for attempt in attempts:
            found = self.reconcile_attempt(attempt)

            if not found:
                attempt.submission_state = CallAttempt.SubmissionState.PREPARED
                attempt.save(
                    update_fields=["submission_state", "updated_at"]
                )

                response = self.submit_call(attempt)
                self.process_provider_response(attempt, response)
    def dispatch_lead(self, lead):
        if not self.has_attempts_remaining(lead):
            return False

        attempt = self.get_or_create_attempt(lead)

        if attempt.submission_state == CallAttempt.SubmissionState.UNKNOWN:
            if self.reconcile_attempt(attempt):
                return True

            # Provider confirmed that the request does not exist.
            # Retry using the same request_id.
            attempt.submission_state = CallAttempt.SubmissionState.PREPARED
            attempt.save(
                update_fields=["submission_state", "updated_at"]
            )

        if not self.reserve_call(lead, attempt):
            return False

        # Mark the request as potentially submitted before contacting the provider.
        attempt.submission_state = CallAttempt.SubmissionState.UNKNOWN
        attempt.save(update_fields=["submission_state", "updated_at"])

        response = self.submit_call(attempt)
        self.process_provider_response(attempt, response)

        return True

    def reconcile_active_attempts(self):
        attempts = CallAttempt.objects.filter(
            submission_state=CallAttempt.SubmissionState.ACCEPTED,
            call_sid__isnull=False,
            provider_status__isnull=True,
        ).select_related("lead", "lead__campaign")

        for attempt in attempts:
            self.reconcile_attempt(attempt)