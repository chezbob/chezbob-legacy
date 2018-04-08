from chezbob.cashout.models import Entity
from django.contrib import admin


class EntityAdmin(admin.ModelAdmin):
    ordering = ['name']


admin.site.register(Entity, EntityAdmin)
