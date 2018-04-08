from chezbob.finance.models import Account
from django.contrib import admin


class AccountAdmin(admin.ModelAdmin):
    ordering = ['name']


admin.site.register(Account, AccountAdmin)
