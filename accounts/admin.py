from django.contrib import admin
from .models import User

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email","rol","is_active","is_staff")
    search_fields = ("email","rut","first_name","last_name")
    list_filter = ("rol","is_active","is_staff","is_superuser")
