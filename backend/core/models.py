from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user extending Django's AbstractUser.

    Using AbstractUser (rather than the default auth.User) so we can add
    fields later without a painful migration. For now it's identical to
    Django's User — username, email, password, first_name, last_name are
    all inherited.
    """

    class Meta:
        db_table = 'core_user'
        ordering = ['username']

    def __str__(self):
        return self.username
