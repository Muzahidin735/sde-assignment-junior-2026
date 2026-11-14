
import uuid

from django.db import models


class CallAttempt(models.Model):

    class SubmissionState(models.TextChoices):
        PREPARED = "prepared", "Prepared"
        UNKNOWN = "unknown", "Unknown"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    class ProviderStatus(models.TextChoices):
        COMPLETED = "completed", "Completed"
        NO_ANSWER = "no_answer", "No Answer"
        BUSY = "busy", "Busy"
        FAILED = "failed", "Failed"

    class Disposition(models.TextChoices):
        INTERESTED = "interested", "Interested"
        NOT_INTERESTED = "not_interested", "Not Interested"
        WRONG_NUMBER = "wrong_number", "Wrong Number"
        DND = "dnd", "DND"
        CALLBACK_REQUESTED = "callback_requested", "Callback Requested"
        NO_ANSWER = "no_answer", "No Answer"
        BUSY = "busy", "Busy"
        FAILED = "failed", "Failed"

    lead = models.ForeignKey(
        "leads.Lead",
        on_delete=models.PROTECT,
        related_name="call_attempts",
    )

    request_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    call_sid = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
    )

    attempt_number = models.PositiveSmallIntegerField()

    submission_state = models.CharField(
        max_length=20,
        choices=SubmissionState.choices,
        default=SubmissionState.PREPARED,
    )

    provider_status = models.CharField(
        max_length=20,
        choices=ProviderStatus.choices,
        null=True,
        blank=True,
    )

    disposition = models.CharField(
        max_length=30,
        choices=Disposition.choices,
        null=True,
        blank=True,
    )

    callback_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    accepted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    ended_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.lead.lead_id} - Attempt {self.attempt_number}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lead", "attempt_number"],
                name="unique_attempt_number_per_lead",
            )
        ]



class ActiveCallReservation(models.Model):
    phone = models.CharField(
        max_length=20,
        unique=True,
    )

    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        related_name="active_call_reservations",
    )

    attempt = models.OneToOneField(
        CallAttempt,
        on_delete=models.PROTECT,
        related_name="reservation",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.phone} - {self.tenant.tenant_id}"


class DNDPhone(models.Model):
    phone = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.phone