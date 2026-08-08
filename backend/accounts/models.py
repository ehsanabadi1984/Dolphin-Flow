from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        SYSTEM_ADMIN = "SYSTEM_ADMIN", "System Admin"
        OPERATOR = "OPERATOR", "Operator"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.OPERATOR,
    )

    def __str__(self):
        return self.get_full_name() or self.username
# Create your models here.
