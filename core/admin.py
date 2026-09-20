from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User


class CustomUserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'role_display')
    list_filter = ('groups', 'is_staff', 'is_superuser', 'is_active')

    def role_display(self, obj):
        return ', '.join(g.name for g in obj.groups.all()) or 'No role'
    role_display.short_description = 'Role'


admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
