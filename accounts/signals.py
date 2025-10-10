from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import Group
from django.contrib.auth import get_user_model

User = get_user_model()

@receiver(post_save, sender=User)
def ensure_groups_and_assign(sender, instance, **kwargs):
    # crea si faltan
    g_student, _  = Group.objects.get_or_create(name="Student")
    g_reviewer, _ = Group.objects.get_or_create(name="Reviewer")
    g_admin, _    = Group.objects.get_or_create(name="Admin")

    # limpia y asigna según el rol
    instance.groups.clear()
    if instance.rol == "STUDENT":
        instance.groups.add(g_student)
    elif instance.rol == "REVIEWER":
        instance.groups.add(g_reviewer)
    elif instance.rol == "ADMIN":
        instance.groups.add(g_admin)
