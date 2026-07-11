from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Group, Membership


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin config for the custom User model — inherits all Django defaults."""
    pass


class MembershipInline(admin.TabularInline):
    """Inline membership editing on the Group admin page."""
    model = Membership
    extra = 1


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'created_by', 'created_at')
    search_fields = ('name',)
    inlines = [MembershipInline]


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'group', 'joined_on', 'left_on')
    list_filter = ('group',)
