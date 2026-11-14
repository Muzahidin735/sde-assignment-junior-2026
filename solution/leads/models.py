from django.db import models


class Lead(models.Model):

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        EXHAUSTED = "exhausted", "Exhausted"
        DND_BLOCKED = "dnd_blocked", "DND Blocked"

    campaign = models.ForeignKey(
        "campaigns.Campaign",
        on_delete=models.PROTECT,
        related_name="leads",
    )

    lead_id = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    customer_name = models.CharField(max_length=150)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    next_eligible_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    callback_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["campaign", "lead_id"],
                name="unique_lead_per_campaign",
            )
        ]

    def __str__(self):
        return f"{self.lead_id} - {self.customer_name}"

