from django.contrib.auth.models import BaseUserManager


class UserManager(BaseUserManager):

    def create_superuser(self, email, password=None, **extra_fields):

        if not email:
            raise ValueError("User must have an email")
        if not password:
            raise ValueError("User must have a password")

        user = self.model(
            email=self.normalize_email(email)
        )
        user.username = email
        user.set_password(password)
        user.is_admin = True
        user.is_staff = True
        user.is_superuser = True
        user.active = True
        user.save(using=self._db)

        return user
