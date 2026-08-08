from django.db import models


class Customer(models.Model):
    class CustomerType(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        ORGANIZATION = "ORGANIZATION", "Organization"

    customer_type = models.CharField(
        max_length=20,
        choices=CustomerType.choices,
    )

    first_name = models.CharField(
        max_length=100,
        blank=True,
    )

    last_name = models.CharField(
        max_length=100,
        blank=True,
    )

    organization_name = models.CharField(
        max_length=255,
        blank=True,
    )

    national_id = models.CharField(
        max_length=20,
        blank=True,
    )

    address = models.TextField(
        blank=True,
    )

    postal_code = models.CharField(
        max_length=20,
        blank=True,
    )

    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        if self.customer_type == self.CustomerType.ORGANIZATION:
            return self.organization_name

        return f"{self.first_name} {self.last_name}".strip()


class ContactPoint(models.Model):
    class ContactType(models.TextChoices):
        PHONE = "PHONE", "Phone"
        MOBILE = "MOBILE", "Mobile"
        EMAIL = "EMAIL", "Email"

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="contact_points",
    )

    type = models.CharField(
        max_length=20,
        choices=ContactType.choices,
    )

    value = models.CharField(
        max_length=255,
    )

    title = models.CharField(
        max_length=100,
        blank=True,
    )

    is_primary = models.BooleanField(
        default=False,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return f"{self.customer} - {self.value}"


# Create your models here.
