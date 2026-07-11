from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    User, Group, Membership, Expense, ExpenseSplit,
    Settlement, ImportBatch, ImportAnomaly,
)


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


class ExpenseSplitInline(admin.TabularInline):
    model = ExpenseSplit
    extra = 0


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('description', 'amount', 'currency', 'paid_by', 'group', 'date', 'split_type')
    list_filter = ('group', 'split_type', 'currency')
    search_fields = ('description',)
    inlines = [ExpenseSplitInline]


@admin.register(Settlement)
class SettlementAdmin(admin.ModelAdmin):
    list_display = ('from_user', 'to_user', 'amount', 'group', 'date')
    list_filter = ('group',)


class ImportAnomalyInline(admin.TabularInline):
    model = ImportAnomaly
    extra = 0
    readonly_fields = ('row_number', 'raw_data', 'problem_type', 'detection_method')


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ('filename', 'group', 'imported_by', 'total_rows', 'imported_rows', 'anomaly_rows', 'created_at')
    inlines = [ImportAnomalyInline]


@admin.register(ImportAnomaly)
class ImportAnomalyAdmin(admin.ModelAdmin):
    list_display = ('batch', 'row_number', 'problem_type', 'status')
    list_filter = ('problem_type', 'status')
