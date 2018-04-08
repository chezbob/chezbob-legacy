from chezbob.bobdb.models import BulkItem, Product
from django.contrib import admin


class ProductInline(admin.TabularInline):
    model = Product


class BulkItemAdmin(admin.ModelAdmin):
    search_fields = ['description', 'product_id']
    fieldsets = [
        ("Details", {'fields': ('description', 'product_id', 'quantity',
                                'updated', 'source', 'reserve', 'active',
                                'floor_location', 'bulkbarcode')}),
        ("Pricing", {'fields': (('price', 'taxable'),
                                ('crv_per_unit', 'crv_taxable'))}),
    ]
    ordering = ['description']
    list_filter = ['updated', 'active', 'source', 'floor_location']
    list_display = ['description', 'product_id', 'quantity', 'price',
                    'taxable', 'crv_per_unit', 'crv_taxable', 'updated',
                    'active', 'source', 'floor_location', 'bulkbarcode']
    inlines = [ProductInline]


class ProductAdmin(admin.ModelAdmin):
    ordering = ['name']
    search_fields = ['barcode', 'name']
    list_display = ['barcode', 'name', 'price']


admin.site.register(BulkItem, BulkItemAdmin)
admin.site.register(Product, ProductAdmin)

#class OrderAdmin(admin.ModelAdmin):
#    ordering = ['date', 'description']
#    search_fields = ['date', 'description']
#    list_display = ['date', 'amount', 'tax_rate', 'description']
#admin.site.register(Order, OrderAdmin)
