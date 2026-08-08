from django.conf import settings
from django.db import models


class RepairForm(models.Model):
    customer = models.ForeignKey(
        "customers.Customer",
        on_delete=models.PROTECT,
        related_name="repair_forms",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_repair_forms",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    notes = models.TextField(
        blank=True,
    )

    def __str__(self):
        return f"Repair Form #{self.pk}"


class RepairDevice(models.Model):
    repair_form = models.ForeignKey(
        RepairForm,
        on_delete=models.CASCADE,
        related_name="devices",
    )

    imei = models.CharField(
        max_length=20,
    )

    problem_description = models.TextField(
        blank=True,
    )

    accessories = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return self.imei


# Create your models here.
