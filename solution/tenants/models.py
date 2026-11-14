from django.db import models

# Create your models here.


class Tenant(models.Model):
    tenant_id = models.CharField(
        max_length=100,
        unique=True,
    )
    max_concurrent_calls = models.PositiveIntegerField()

    def __str__(self):
        return self.tenant_id
