from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import User
from .models import Profile, Account, MT5Account, CTraderAccount, ProfitTakingProfile

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profile'
    fk_name = 'user'

class CustomUserAdmin(BaseUserAdmin):
    inlines = (ProfileInline,)
    list_display = ('username', 'email', 'is_staff', 'is_active', 'get_is_approved')
    list_select_related = ('profile',)
    actions = ['approve_users']

    def get_is_approved(self, instance):
        return instance.profile.is_approved
    get_is_approved.short_description = 'Approved'
    get_is_approved.boolean = True

    def approve_users(self, request, queryset):
        for user in queryset:
            user.is_active = True
            user.profile.is_approved = True
            user.save()
    approve_users.short_description = "Approve selected users"

admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)

# Register other models if they are not already registered
if not admin.site.is_registered(Account):
    admin.site.register(Account)
if not admin.site.is_registered(MT5Account):
    admin.site.register(MT5Account)
if not admin.site.is_registered(CTraderAccount):
    admin.site.register(CTraderAccount)
if not admin.site.is_registered(ProfitTakingProfile):
    admin.site.register(ProfitTakingProfile)
