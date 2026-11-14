from django.test import TestCase

# Create your tests here.

import uuid
from datetime import datetime, timedelta

from tenants.models import Tenant
from campaigns.models import Campaign
from leads.models import Lead
from webhooks.models import WebhookEvent
from webhooks.processor import process_webhook_event
from telephony.models import CallAttempt, ActiveCallReservation


class NoAnswerWebhookTests(TestCase):

    def test_no_answer_with_null_disposition_schedules_retry(self):
        tenant = Tenant.objects.create(
            tenant_id="test_tenant",
            max_concurrent_calls=2,
        )

        campaign = Campaign.objects.create(
            campaign_id="test_campaign",
            tenant=tenant,
            window_start="09:00",
            window_end="18:00",
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        lead = Lead.objects.create(
            campaign=campaign,
            lead_id="test_lead",
            phone="+911234567890",
            customer_name="Test User",
        )

        request_id = uuid.uuid4()
        ended_at = datetime.fromisoformat(
            "2026-11-12T17:35:17+05:30"
        )

        attempt = CallAttempt.objects.create(
            lead=lead,
            request_id=request_id,
            attempt_number=1,
            submission_state=CallAttempt.SubmissionState.ACCEPTED,
            call_sid="CA_test_no_answer",
        )

        payload = {
            "event": "call.completed",
            "request_id": str(request_id),
            "call_sid": "CA_test_no_answer",
            "campaign_id": campaign.campaign_id,
            "lead_id": lead.lead_id,
            "status": "no_answer",
            "disposition": None,
            "started_at": "2026-11-12T17:34:43+05:30",
            "ended_at": ended_at.isoformat(),
            "callback_at": None,
        }

        event = WebhookEvent.objects.create(
            payload_hash="a" * 64,
            event_type="call.completed",
            request_id=request_id,
            call_sid="CA_test_no_answer",
            payload=payload,
        )

        process_webhook_event(event.id)

        attempt.refresh_from_db()
        lead.refresh_from_db()

        self.assertEqual(
            attempt.disposition,
            CallAttempt.Disposition.NO_ANSWER,
        )
        self.assertEqual(
            lead.next_eligible_at,
            ended_at + timedelta(minutes=60),
        )
        self.assertEqual(lead.status, Lead.Status.PENDING)



class UnknownAttemptReconciliationTests(TestCase):

    def test_webhook_reconciles_unknown_attempt_and_releases_reservation(self):
        tenant = Tenant.objects.create(
            tenant_id="reconciliation_tenant",
            max_concurrent_calls=2,
        )

        campaign = Campaign.objects.create(
            campaign_id="reconciliation_campaign",
            tenant=tenant,
            window_start="09:00",
            window_end="18:00",
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        lead = Lead.objects.create(
            campaign=campaign,
            lead_id="reconciliation_lead",
            phone="+919876543210",
            customer_name="Reconciliation Customer",
        )

        attempt = CallAttempt.objects.create(
            lead=lead,
            attempt_number=1,
            submission_state=CallAttempt.SubmissionState.UNKNOWN,
        )

        ActiveCallReservation.objects.create(
            phone=lead.phone,
            tenant=tenant,
            attempt=attempt,
        )

        payload = {
            "event": "call.completed",
            "request_id": str(attempt.request_id),
            "call_sid": "CA_reconciled_call",
            "status": "completed",
            "disposition": "interested",
            "started_at": "2026-11-12T17:34:43+05:30",
            "ended_at": "2026-11-12T17:35:17+05:30",
            "callback_at": None,
        }

        event = WebhookEvent.objects.create(
            payload_hash="d" * 64,
            event_type=payload["event"],
            request_id=attempt.request_id,
            call_sid=payload["call_sid"],
            payload=payload,
        )

        process_webhook_event(event.id)

        attempt.refresh_from_db()
        lead.refresh_from_db()
        event.refresh_from_db()

        self.assertEqual(
            attempt.submission_state,
            CallAttempt.SubmissionState.ACCEPTED,
        )

        self.assertEqual(
            attempt.call_sid,
            "CA_reconciled_call",
        )

        self.assertFalse(
            ActiveCallReservation.objects.filter(
                attempt=attempt
            ).exists()
        )

        self.assertEqual(lead.status, Lead.Status.COMPLETED)

        self.assertEqual(
            event.processing_status,
            WebhookEvent.ProcessingStatus.PROCESSED,
        )
