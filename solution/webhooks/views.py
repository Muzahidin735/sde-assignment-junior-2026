from django.shortcuts import render

# Create your views here.
import hashlib
import hmac
import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from webhooks.models import WebhookEvent
from telephony.models import CallAttempt

from campaigns.models import Campaign

from webhooks.processor import process_webhook_event


def verify_webhook_signature(request, secret):
    received_signature = request.headers.get("X-AU-Signature", "")

    expected_signature = hmac.new(
        secret.encode("utf-8"),
        request.body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(
        received_signature,
        expected_signature,
    )

@csrf_exempt
def call_result_webhook(request):
    if request.method != "POST":
        return JsonResponse(
            {"error": "Method not allowed"},
            status=405,
        )

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse(
            {"error": "Invalid JSON"},
            status=400,
        )

    campaign = Campaign.objects.filter(
        campaign_id=payload.get("campaign_id")
    ).first()

    if campaign is None:
        return JsonResponse(
            {"error": "Campaign not found"},
            status=404,
        )

    if not verify_webhook_signature(request, campaign.webhook_secret):
        return JsonResponse(
            {"error": "Invalid signature"},
            status=401,
        )

    payload_hash = hashlib.sha256(request.body).hexdigest()

    event, created = WebhookEvent.objects.get_or_create(
    request_id=payload["request_id"],
    call_sid=payload["call_sid"],
    event_type=payload["event"],
    defaults={
        "payload_hash": payload_hash,
        "payload": payload,
    },
)

    process_webhook_event(event.id)

    return JsonResponse({"message": "Webhook received"})