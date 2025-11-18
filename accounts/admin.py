from django.contrib import admin
from .models import User
from .models import SupportTicket
@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email","rol","is_active","is_staff")
    search_fields = ("email","rut","first_name","last_name")
    list_filter = ("rol","is_active","is_staff","is_superuser")
    
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "user", "tipo_consulta", "asunto", "estado")
    list_filter = ("estado", "tipo_consulta", "created_at")
    search_fields = ("asunto", "detalle", "user__email", "user__first_name", "user__last_name")