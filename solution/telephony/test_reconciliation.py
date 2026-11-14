from unittest.mock import patch

from django.test import TestCase

from tenants.models import Tenant
from campaigns.models import Campaign
from leads.models import Lead
from telephony.models import CallAttempt
from telephony.dispatcher import CampaignDispatcher


class ActiveCallReconciliationTests(TestCase):

    def setUp(self):
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

        self.attempt = CallAttempt.objects.create(
            lead=lead,
            attempt_number=1,
            submission_state=CallAttempt.SubmissionState.ACCEPTED,
            call_sid="test_call_sid",
        )

        self.dispatcher = CampaignDispatcher()

    def tearDown(self):
        self.dispatcher.close()

    @patch.object(CampaignDispatcher, "reconcile_attempt")
    def test_reconciles_accepted_calls_without_final_status(self, mock_reconcile):
        self.dispatcher.reconcile_active_attempts()

        mock_reconcile.assert_called_once_with(self.attempt)