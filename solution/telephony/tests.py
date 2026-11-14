from django.test import TestCase

# Create your tests here.
from datetime import datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from unittest.mock import patch
from django.test import SimpleTestCase

from telephony.scheduling import (
    is_within_calling_window,
    get_next_window_opening,
    get_next_eligible_time,
    get_retry_time,
    get_callback_time,
    get_priority,
)


from django.db import IntegrityError, transaction
from django.test import TestCase
from tenants.models import Tenant
from campaigns.models import Campaign
from leads.models import Lead
from telephony.models import CallAttempt, ActiveCallReservation, DNDPhone

from django.utils.dateparse import parse_datetime
from webhooks.processor import process_webhook_event
from webhooks.models import WebhookEvent

from unittest.mock import Mock

IST = ZoneInfo("Asia/Kolkata")


def make_campaign(
    window_start=time(10, 0),
    window_end=time(19, 0),
    calling_days=None,
):
    return SimpleNamespace(
        window_start=window_start,
        window_end=window_end,
        calling_days=calling_days or [
            "mon", "tue", "wed", "thu", "fri", "sat"
        ],
    )


class CallingWindowTests(SimpleTestCase):

    def setUp(self):
        self.campaign = make_campaign()

    def test_call_inside_campaign_window(self):
        now = datetime(2026, 11, 16, 10, 30, tzinfo=IST)

        self.assertTrue(
            is_within_calling_window(self.campaign, now)
        )

    def test_call_before_campaign_window(self):
        now = datetime(2026, 11, 16, 9, 30, tzinfo=IST)

        self.assertFalse(
            is_within_calling_window(self.campaign, now)
        )

    def test_call_at_campaign_closing_time_is_not_allowed(self):
        now = datetime(2026, 11, 16, 19, 0, tzinfo=IST)

        self.assertFalse(
            is_within_calling_window(self.campaign, now)
        )

    def test_call_outside_regulatory_window(self):
        now = datetime(2026, 11, 16, 21, 30, tzinfo=IST)

        self.assertFalse(
            is_within_calling_window(self.campaign, now)
        )

    def test_call_on_disallowed_day(self):
        now = datetime(2026, 11, 15, 11, 0, tzinfo=IST)

        self.assertFalse(
            is_within_calling_window(self.campaign, now)
        )

    def test_next_window_opening_after_closing(self):
        now = datetime(2026, 11, 16, 20, 0, tzinfo=IST)

        expected = datetime(2026, 11, 17, 10, 0, tzinfo=IST)

        self.assertEqual(
            get_next_window_opening(self.campaign, now),
            expected,
        )

    def test_next_window_skips_disallowed_days(self):
        campaign = make_campaign(
            calling_days=["mon", "tue", "wed", "thu", "fri"]
        )

        now = datetime(2026, 11, 13, 20, 0, tzinfo=IST)

        expected = datetime(2026, 11, 16, 10, 0, tzinfo=IST)

        self.assertEqual(
            get_next_window_opening(campaign, now),
            expected,
        )

    def test_eligible_time_inside_window(self):
        now = datetime(2026, 11, 16, 10, 30, tzinfo=IST)
        eligible_at = datetime(2026, 11, 16, 11, 0, tzinfo=IST)

        self.assertEqual(
            get_next_eligible_time(
                self.campaign,
                now,
                eligible_at,
            ),
            eligible_at,
        )


class RetrySchedulingTests(SimpleTestCase):

    def setUp(self):
        self.retry_policy = {
            "no_answer_minutes": 60,
            "busy_minutes": 60,
            "failed_minutes": 15,
        }

        self.ended_at = datetime(
            2026, 11, 16, 12, 0, tzinfo=IST
        )

    def test_no_answer_retry_after_60_minutes(self):
        expected = self.ended_at + timedelta(minutes=60)

        self.assertEqual(
            get_retry_time(
                "no_answer",
                self.ended_at,
                self.retry_policy,
            ),
            expected,
        )

    def test_busy_retry_after_60_minutes(self):
        expected = self.ended_at + timedelta(minutes=60)

        self.assertEqual(
            get_retry_time(
                "busy",
                self.ended_at,
                self.retry_policy,
            ),
            expected,
        )

    def test_failed_retry_after_15_minutes(self):
        expected = self.ended_at + timedelta(minutes=15)

        self.assertEqual(
            get_retry_time(
                "failed",
                self.ended_at,
                self.retry_policy,
            ),
            expected,
        )

    def test_terminal_disposition_has_no_retry(self):
        self.assertIsNone(
            get_retry_time(
                "interested",
                self.ended_at,
                self.retry_policy,
            )
        )


class CallbackSchedulingTests(SimpleTestCase):

    def setUp(self):
        self.campaign = make_campaign()

    def test_callback_at_requested_time(self):
        now = datetime(2026, 11, 16, 10, 0, tzinfo=IST)
        callback_at = datetime(2026, 11, 16, 11, 0, tzinfo=IST)

        self.assertEqual(
            get_callback_time(
                callback_at,
                self.campaign,
                now,
            ),
            callback_at,
        )

    def test_callback_outside_window_moves_to_next_opening(self):
        now = datetime(2026, 11, 16, 18, 0, tzinfo=IST)
        callback_at = datetime(2026, 11, 16, 20, 0, tzinfo=IST)

        expected = datetime(2026, 11, 17, 10, 0, tzinfo=IST)

        self.assertEqual(
            get_callback_time(
                callback_at,
                self.campaign,
                now,
            ),
            expected,
        )


class LeadPriorityTests(SimpleTestCase):

    def test_callback_has_highest_priority(self):
        lead = SimpleNamespace(
            callback_at=datetime(2026, 11, 16, 11, 0, tzinfo=IST),
            next_eligible_at=None,
        )

        self.assertEqual(get_priority(lead), 1)

    def test_retry_has_second_priority(self):
        lead = SimpleNamespace(
            callback_at=None,
            next_eligible_at=datetime(
                2026, 11, 16, 11, 0, tzinfo=IST
            ),
        )

        self.assertEqual(get_priority(lead), 2)

    def test_fresh_lead_has_third_priority(self):
        lead = SimpleNamespace(
            callback_at=None,
            next_eligible_at=None,
        )

        self.assertEqual(get_priority(lead), 3)


class TelephonyModelTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            tenant_id="test_tenant",
            max_concurrent_calls=2,
        )

        self.campaign = Campaign.objects.create(
            campaign_id="test_campaign",
            tenant=self.tenant,
            window_start=time(10, 0),
            window_end=time(19, 0),
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        self.lead = Lead.objects.create(
            campaign=self.campaign,
            lead_id="test_lead_1",
            phone="+911234567890",
            customer_name="Test Customer",
        )

    def test_call_attempt_is_created(self):
        attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
        )

        self.assertEqual(attempt.attempt_number, 1)
        self.assertEqual(
            attempt.submission_state,
            CallAttempt.SubmissionState.PREPARED,
        )

    def test_accepted_attempt_count(self):
        CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
            submission_state=CallAttempt.SubmissionState.ACCEPTED,
        )

        CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=2,
            submission_state=CallAttempt.SubmissionState.REJECTED,
        )

        accepted_count = self.lead.call_attempts.filter(
            submission_state=CallAttempt.SubmissionState.ACCEPTED
        ).count()

        self.assertEqual(accepted_count, 1)

    def test_active_call_reservation_is_created(self):
        attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
        )

        reservation = ActiveCallReservation.objects.create(
            phone=self.lead.phone,
            tenant=self.tenant,
            attempt=attempt,
        )

        self.assertEqual(reservation.phone, self.lead.phone)

    def test_phone_cannot_have_two_active_reservations(self):
        first_attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
        )

        second_lead = Lead.objects.create(
            campaign=self.campaign,
            lead_id="test_lead_2",
            phone=self.lead.phone,
            customer_name="Another Customer",
        )

        second_attempt = CallAttempt.objects.create(
            lead=second_lead,
            attempt_number=1,
        )

        ActiveCallReservation.objects.create(
            phone=self.lead.phone,
            tenant=self.tenant,
            attempt=first_attempt,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ActiveCallReservation.objects.create(
                    phone=self.lead.phone,
                    tenant=self.tenant,
                    attempt=second_attempt,
                )

    def test_dnd_phone_is_unique(self):
        DNDPhone.objects.create(phone=self.lead.phone)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                DNDPhone.objects.create(phone=self.lead.phone)


from webhooks.models import WebhookEvent
from webhooks.processor import process_webhook_event

class WebhookIdempotencyTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            tenant_id="webhook_test_tenant",
            max_concurrent_calls=2,
        )

        self.campaign = Campaign.objects.create(
            campaign_id="webhook_test_campaign",
            tenant=self.tenant,
            window_start=time(10, 0),
            window_end=time(19, 0),
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        self.lead = Lead.objects.create(
            campaign=self.campaign,
            lead_id="webhook_test_lead",
            phone="+919876543210",
            customer_name="Webhook Test Customer",
        )

        self.attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
        )

        self.event = WebhookEvent.objects.create(
            payload_hash="a" * 64,
            event_type="call.completed",
            request_id=self.attempt.request_id,
            call_sid="test_call_sid",
            payload={
                "event": "call.completed",
                "request_id": str(self.attempt.request_id),
                "call_sid": "test_call_sid",
                "status": "completed",
                "disposition": "interested",
                "started_at": "2026-11-16T10:00:00+05:30",
                "ended_at": "2026-11-16T10:01:00+05:30",
                "callback_at": None,
            },
        )

    def test_duplicate_processing_does_not_repeat_updates(self):
        process_webhook_event(self.event.id)
        process_webhook_event(self.event.id)

        self.attempt.refresh_from_db()
        self.lead.refresh_from_db()
        self.event.refresh_from_db()

        self.assertEqual(
            self.attempt.submission_state,
            CallAttempt.SubmissionState.ACCEPTED,
        )
        self.assertEqual(self.lead.status, Lead.Status.COMPLETED)
        self.assertEqual(
            self.event.processing_status,
            WebhookEvent.ProcessingStatus.PROCESSED,
        )
        self.assertEqual(self.lead.call_attempts.count(), 1)


class DispatcherAttemptTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            tenant_id="dispatcher_test_tenant",
            max_concurrent_calls=2,
        )

        self.campaign = Campaign.objects.create(
            campaign_id="dispatcher_test_campaign",
            tenant=self.tenant,
            window_start=time(10, 0),
            window_end=time(19, 0),
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        self.lead = Lead.objects.create(
            campaign=self.campaign,
            lead_id="dispatcher_test_lead",
            phone="+911111111111",
            customer_name="Dispatcher Test Customer",
        )

        from telephony.dispatcher import CampaignDispatcher
        self.dispatcher = CampaignDispatcher()

    def tearDown(self):
        self.dispatcher.close()

    def test_first_attempt_number_is_one(self):
        self.assertEqual(
            self.dispatcher.get_next_attempt_number(self.lead),
            1,
        )

    def test_prepared_attempt_is_reused(self):
        CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
            submission_state=CallAttempt.SubmissionState.PREPARED,
        )

        self.assertEqual(
            self.dispatcher.get_next_attempt_number(self.lead),
            1,
        )

    def test_unknown_attempt_is_reused(self):
        CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
            submission_state=CallAttempt.SubmissionState.UNKNOWN,
        )

        self.assertEqual(
            self.dispatcher.get_next_attempt_number(self.lead),
            1,
        )

    def test_accepted_attempt_gets_new_attempt_number(self):
        CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
            submission_state=CallAttempt.SubmissionState.ACCEPTED,
        )

        self.assertEqual(
            self.dispatcher.get_next_attempt_number(self.lead),
            2,
        )

    def test_rejected_attempt_gets_new_attempt_number(self):
        CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
            submission_state=CallAttempt.SubmissionState.REJECTED,
        )

        self.assertEqual(
            self.dispatcher.get_next_attempt_number(self.lead),
            2,
        )

    def test_rejected_attempt_does_not_count_toward_limit(self):
        for number, state in [
            (1, CallAttempt.SubmissionState.ACCEPTED),
            (2, CallAttempt.SubmissionState.REJECTED),
            (3, CallAttempt.SubmissionState.ACCEPTED),
        ]:
            CallAttempt.objects.create(
                lead=self.lead,
                attempt_number=number,
                submission_state=state,
            )

        self.assertEqual(
            self.dispatcher.get_accepted_attempt_count(self.lead),
            2,
        )

        self.assertTrue(
            self.dispatcher.has_attempts_remaining(self.lead)
        )
    
    def test_422_response_rejects_attempt_and_releases_reservation(self):
        attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
        )

        self.assertTrue(
            self.dispatcher.reserve_call(self.lead, attempt)
        )

        response = SimpleNamespace(status_code=422)

        self.dispatcher.process_provider_response(attempt, response)

        attempt.refresh_from_db()

        self.assertEqual(
            attempt.submission_state,
            CallAttempt.SubmissionState.REJECTED,
        )

        self.assertFalse(
            ActiveCallReservation.objects.filter(
                attempt=attempt
            ).exists()
        )

    
    def test_503_response_rejects_attempt_and_releases_reservation(self):
        attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
        )

        self.assertTrue(
            self.dispatcher.reserve_call(self.lead, attempt)
        )

        response = SimpleNamespace(status_code=503)

        self.dispatcher.process_provider_response(attempt, response)

        attempt.refresh_from_db()

        self.assertEqual(
            attempt.submission_state,
            CallAttempt.SubmissionState.REJECTED,
        )

        self.assertFalse(
            ActiveCallReservation.objects.filter(
                attempt=attempt
            ).exists()
        )

        self.assertEqual(
            self.dispatcher.get_accepted_attempt_count(self.lead),
            0,
        )

        self.assertEqual(
            self.dispatcher.get_next_attempt_number(self.lead),
            2,
        )

    
    def test_504_response_marks_attempt_unknown_and_keeps_reservation(self):
        attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
        )

        self.assertTrue(
            self.dispatcher.reserve_call(self.lead, attempt)
        )

        response = SimpleNamespace(status_code=504)

        self.dispatcher.process_provider_response(attempt, response)

        attempt.refresh_from_db()

        self.assertEqual(
            attempt.submission_state,
            CallAttempt.SubmissionState.UNKNOWN,
        )

        self.assertTrue(
            ActiveCallReservation.objects.filter(
                attempt=attempt
            ).exists()
        )

        self.assertEqual(
            self.dispatcher.get_accepted_attempt_count(self.lead),
            0,
        )

        self.assertEqual(
            self.dispatcher.get_next_attempt_number(self.lead),
            1,
        )

    
    def test_reconcile_attempt_processes_lost_webhook(self):
        attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
            submission_state=CallAttempt.SubmissionState.ACCEPTED,
            call_sid="CA_lost_webhook",
        )

        result = {
            "event": "call.completed",
            "request_id": str(attempt.request_id),
            "call_sid": "CA_lost_webhook",
            "status": "completed",
            "disposition": "interested",
            "started_at": "2026-11-16T10:00:00+05:30",
            "ended_at": "2026-11-16T10:01:00+05:30",
            "callback_at": None,
        }

        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "state": "ended",
            "result": result,
        }

        self.dispatcher.client.get = Mock(return_value=response)

        found = self.dispatcher.reconcile_attempt(attempt)

        self.assertTrue(found)

        self.assertTrue(
            WebhookEvent.objects.filter(
                request_id=attempt.request_id,
                event_type="call.completed",
            ).exists()
        )

        attempt.refresh_from_db()
        self.lead.refresh_from_db()

        self.assertEqual(
            attempt.disposition,
            CallAttempt.Disposition.INTERESTED,
        )

        self.assertEqual(
            self.lead.status,
            Lead.Status.COMPLETED,
        )


    def test_unknown_attempt_is_resubmitted_when_provider_returns_404(self):
        attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
            submission_state=CallAttempt.SubmissionState.UNKNOWN,
        )

        get_response = SimpleNamespace(status_code=404)

        post_response = SimpleNamespace(status_code=503)

        self.dispatcher.client.get = Mock(return_value=get_response)
        self.dispatcher.client.post = Mock(return_value=post_response)

        self.dispatcher.reconcile_unknown_attempts()

        attempt.refresh_from_db()

        self.assertEqual(
            attempt.submission_state,
            CallAttempt.SubmissionState.REJECTED,
        )

        self.assertEqual(
            self.dispatcher.client.post.call_count,
            1,
        )

        submitted_payload = self.dispatcher.client.post.call_args.kwargs["json"]

        self.assertEqual(
            submitted_payload["request_id"],
            str(attempt.request_id),
        )

        self.assertEqual(
            CallAttempt.objects.filter(lead=self.lead).count(),
            1,
        )



class TenantConcurrencyTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            tenant_id="concurrency_test_tenant",
            max_concurrent_calls=1,
        )

        self.campaign = Campaign.objects.create(
            campaign_id="concurrency_test_campaign",
            tenant=self.tenant,
            window_start=time(10, 0),
            window_end=time(19, 0),
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        self.lead_one = Lead.objects.create(
            campaign=self.campaign,
            lead_id="concurrency_lead_1",
            phone="+911234567801",
            customer_name="Customer One",
        )

        self.lead_two = Lead.objects.create(
            campaign=self.campaign,
            lead_id="concurrency_lead_2",
            phone="+911234567802",
            customer_name="Customer Two",
        )

        from telephony.dispatcher import CampaignDispatcher
        self.dispatcher = CampaignDispatcher()

    def tearDown(self):
        self.dispatcher.close()

    def test_tenant_concurrency_limit_is_enforced(self):
        attempt_one = CallAttempt.objects.create(
            lead=self.lead_one,
            attempt_number=1,
        )

        attempt_two = CallAttempt.objects.create(
            lead=self.lead_two,
            attempt_number=1,
        )

        self.assertTrue(
            self.dispatcher.reserve_call(self.lead_one, attempt_one)
        )

        self.assertFalse(
            self.dispatcher.reserve_call(self.lead_two, attempt_two)
        )

    def test_phone_cannot_be_reserved_by_another_tenant(self):
        another_tenant = Tenant.objects.create(
            tenant_id="another_concurrency_tenant",
            max_concurrent_calls=2,
        )

        another_campaign = Campaign.objects.create(
            campaign_id="another_concurrency_campaign",
            tenant=another_tenant,
            window_start=time(10, 0),
            window_end=time(19, 0),
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        another_lead = Lead.objects.create(
            campaign=another_campaign,
            lead_id="another_concurrency_lead",
            phone=self.lead_one.phone,
            customer_name="Another Customer",
        )

        first_attempt = CallAttempt.objects.create(
            lead=self.lead_one,
            attempt_number=1,
        )

        second_attempt = CallAttempt.objects.create(
            lead=another_lead,
            attempt_number=1,
        )

        self.assertTrue(
            self.dispatcher.reserve_call(self.lead_one, first_attempt)
        )

        self.assertFalse(
            self.dispatcher.reserve_call(another_lead, second_attempt)
        )

class DNDProtectionTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            tenant_id="dnd_test_tenant",
            max_concurrent_calls=2,
        )

        self.campaign = Campaign.objects.create(
            campaign_id="dnd_test_campaign",
            tenant=self.tenant,
            window_start=time(10, 0),
            window_end=time(19, 0),
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        self.lead = Lead.objects.create(
            campaign=self.campaign,
            lead_id="dnd_lead_1",
            phone="+919999999999",
            customer_name="DND Customer",
        )

        from telephony.dispatcher import CampaignDispatcher
        self.dispatcher = CampaignDispatcher()

    def tearDown(self):
        self.dispatcher.close()

    def test_dnd_phone_is_excluded_from_eligible_leads(self):
        DNDPhone.objects.create(phone=self.lead.phone)

        eligible_leads = self.dispatcher.get_eligible_leads()

        self.assertFalse(
            eligible_leads.filter(pk=self.lead.pk).exists()
        )


class WebhookRetrySchedulingTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            tenant_id="retry_test_tenant",
            max_concurrent_calls=2,
        )

        self.campaign = Campaign.objects.create(
            campaign_id="retry_test_campaign",
            tenant=self.tenant,
            window_start=time(10, 0),
            window_end=time(19, 0),
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        self.lead = Lead.objects.create(
            campaign=self.campaign,
            lead_id="retry_test_lead",
            phone="+918888888888",
            customer_name="Retry Test Customer",
        )

        self.attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
        )

        self.ended_at = "2026-11-16T12:00:00+05:30"

    def process_disposition(self, disposition):
        payload = {
            "event": "call.completed",
            "request_id": str(self.attempt.request_id),
            "call_sid": "retry_test_call",
            "status": disposition,
            "disposition": disposition,
            "started_at": "2026-11-16T11:59:00+05:30",
            "ended_at": self.ended_at,
            "callback_at": None,
        }

        event = WebhookEvent.objects.create(
            payload_hash=disposition.ljust(64, "0"),
            event_type=payload["event"],
            request_id=self.attempt.request_id,
            call_sid=payload["call_sid"],
            payload=payload,
        )

        process_webhook_event(event.id)
        self.lead.refresh_from_db()

    def test_no_answer_retry_after_60_minutes(self):
        self.process_disposition("no_answer")

        expected = parse_datetime(self.ended_at) + timedelta(minutes=60)
        self.assertEqual(self.lead.next_eligible_at, expected)

    def test_busy_retry_after_60_minutes(self):
        self.process_disposition("busy")

        expected = parse_datetime(self.ended_at) + timedelta(minutes=60)
        self.assertEqual(self.lead.next_eligible_at, expected)

    def test_failed_retry_after_15_minutes(self):
        self.process_disposition("failed")

        expected = parse_datetime(self.ended_at) + timedelta(minutes=15)
        self.assertEqual(self.lead.next_eligible_at, expected)

class WebhookCallbackTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            tenant_id="callback_test_tenant",
            max_concurrent_calls=2,
        )

        self.campaign = Campaign.objects.create(
            campaign_id="callback_test_campaign",
            tenant=self.tenant,
            window_start=time(10, 0),
            window_end=time(19, 0),
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        self.lead = Lead.objects.create(
            campaign=self.campaign,
            lead_id="callback_test_lead",
            phone="+917777777777",
            customer_name="Callback Test Customer",
        )

        self.attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
        )

    def test_callback_time_is_saved_from_webhook(self):
        callback_at = "2026-11-16T15:00:00+05:30"

        payload = {
            "event": "call.completed",
            "request_id": str(self.attempt.request_id),
            "call_sid": "callback_test_call",
            "status": "completed",
            "disposition": "callback_requested",
            "started_at": "2026-11-16T11:00:00+05:30",
            "ended_at": "2026-11-16T11:01:00+05:30",
            "callback_at": callback_at,
        }

        event = WebhookEvent.objects.create(
            payload_hash="b" * 64,
            event_type=payload["event"],
            request_id=self.attempt.request_id,
            call_sid=payload["call_sid"],
            payload=payload,
        )

        process_webhook_event(event.id)
        self.lead.refresh_from_db()

        self.assertEqual(
            self.lead.callback_at,
            parse_datetime(callback_at),
        )
        self.assertIsNone(self.lead.next_eligible_at)
        self.assertEqual(self.lead.status, Lead.Status.PENDING)


class WebhookDNDTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            tenant_id="webhook_dnd_tenant",
            max_concurrent_calls=2,
        )

        self.campaign = Campaign.objects.create(
            campaign_id="webhook_dnd_campaign",
            tenant=self.tenant,
            window_start=time(10, 0),
            window_end=time(19, 0),
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        self.lead = Lead.objects.create(
            campaign=self.campaign,
            lead_id="dnd_source_lead",
            phone="+916666666666",
            customer_name="DND Customer",
        )

        self.other_lead = Lead.objects.create(
            campaign=self.campaign,
            lead_id="dnd_other_lead",
            phone=self.lead.phone,
            customer_name="Another Customer",
        )

        self.attempt = CallAttempt.objects.create(
            lead=self.lead,
            attempt_number=1,
        )

    def test_dnd_blocks_matching_pending_leads(self):
        payload = {
            "event": "call.completed",
            "request_id": str(self.attempt.request_id),
            "call_sid": "dnd_test_call",
            "status": "completed",
            "disposition": "dnd",
            "started_at": "2026-11-16T11:00:00+05:30",
            "ended_at": "2026-11-16T11:01:00+05:30",
            "callback_at": None,
        }

        event = WebhookEvent.objects.create(
            payload_hash="c" * 64,
            event_type=payload["event"],
            request_id=self.attempt.request_id,
            call_sid=payload["call_sid"],
            payload=payload,
        )

        process_webhook_event(event.id)

        self.lead.refresh_from_db()
        self.other_lead.refresh_from_db()

        self.assertEqual(self.lead.status, Lead.Status.COMPLETED)
        self.assertEqual(
            self.other_lead.status,
            Lead.Status.DND_BLOCKED,
        )
        self.assertTrue(
            DNDPhone.objects.filter(phone=self.lead.phone).exists()
        )


class LeadExhaustionTests(TestCase):

    def setUp(self):
        self.tenant = Tenant.objects.create(
            tenant_id="exhaustion_test_tenant",
            max_concurrent_calls=2,
        )

        self.campaign = Campaign.objects.create(
            campaign_id="exhaustion_test_campaign",
            tenant=self.tenant,
            window_start=time(10, 0),
            window_end=time(19, 0),
            calling_days=["mon", "tue", "wed", "thu", "fri"],
            max_attempts=3,
        )

        self.lead = Lead.objects.create(
            campaign=self.campaign,
            lead_id="exhaustion_test_lead",
            phone="+915555555555",
            customer_name="Exhaustion Customer",
        )

    def test_lead_becomes_exhausted_after_third_accepted_call(self):
        for number in range(1, 4):
            attempt = CallAttempt.objects.create(
                lead=self.lead,
                attempt_number=number,
            )

            payload = {
                "event": "call.completed",
                "request_id": str(attempt.request_id),
                "call_sid": f"exhaustion_call_{number}",
                "status": "completed",
                "disposition": "no_answer",
                "started_at": "2026-11-16T11:00:00+05:30",
                "ended_at": "2026-11-16T11:01:00+05:30",
                "callback_at": None,
            }

            event = WebhookEvent.objects.create(
                payload_hash=f"{number}" * 64,
                event_type=payload["event"],
                request_id=attempt.request_id,
                call_sid=payload["call_sid"],
                payload=payload,
            )

            process_webhook_event(event.id)

        self.lead.refresh_from_db()

        self.assertEqual(
            self.lead.status,
            Lead.Status.EXHAUSTED,
        )