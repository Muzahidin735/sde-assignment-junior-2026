from django.db import models

# Create your models here.
class Campaign(models.Model):
    campaign_id = models.CharField(
        max_length=100,
        unique=True,
    )
    tenant = models.ForeignKey(
        "tenants.Tenant",
        on_delete=models.PROTECT,
        related_name="campaigns",
    )
    window_start = models.TimeField()
    window_end = models.TimeField()
    calling_days = models.JSONField()
    max_attempts = models.PositiveSmallIntegerField()

    webhook_secret = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    def __str__(self):
        return self.campaign_id

