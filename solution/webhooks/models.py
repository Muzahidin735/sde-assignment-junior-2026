from django.db import models

# Create your models here.


class WebhookEvent(models.Model):

    class ProcessingStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    payload_hash = models.CharField(
        max_length=64,
        unique=True,
    )

    event_type = models.CharField(max_length=100)

    request_id = models.UUIDField()

    call_sid = models.CharField(max_length=100)

    payload = models.JSONField()

    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
    )

    received_at = models.DateTimeField(auto_now_add=True)

    processed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    error_message = models.TextField(
        blank=True,
    )

    def __str__(self):
        return f"{self.event_type} - {self.call_sid}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["request_id", "call_sid", "event_type"],
                name="unique_webhook_event_identity",
            )
        ]