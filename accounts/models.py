from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError("Email requerido")
        email = self.normalize_email(email)
        u = self.model(email=email, **extra)
        u.set_password(password)
        u.save(using=self._db)
        return u

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create(email, password, **extra)

class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True, db_index=True)
    ROL_CHOICES = [("STUDENT","Estudiante"),("REVIEWER","Revisor"),("ADMIN","Admin")]
    rol = models.CharField(max_length=10, choices=ROL_CHOICES, db_index=True, default="STUDENT")
    rut = models.CharField(max_length=20, blank=True, null=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["rol"]

    objects = UserManager()

    def __str__(self):
        return f"{self.email} ({self.rol})"
