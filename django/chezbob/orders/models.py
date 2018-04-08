from decimal import Decimal
from django.db import models
from chezbob.bobdb.models import BulkItem
from chezbob.finance.models import Transaction

# Current tax rate.  This is only used to compute current item prices.  For any
# historical analysis, the per-order tax rate stored with each order is used
# instead.
TAX_RATE = Decimal("0.0775")


class Order(models.Model):
    class Meta:
        db_table = 'orders'
        permissions = [("edit_orders", "Enter Order Information")]

    date = models.DateField()
    description = models.CharField(max_length=256)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    tax_rate = models.DecimalField(max_digits=6, decimal_places=4)

    # Keep track of relevant financial gook
    inventory_adjust = models.DecimalField(max_digits=12, decimal_places=2)
    supplies_adjust = models.DecimalField(max_digits=12, decimal_places=2)
    supplies_taxed = models.DecimalField(max_digits=12, decimal_places=2)
    supplies_nontaxed = models.DecimalField(max_digits=12, decimal_places=2)
    returns_taxed = models.DecimalField(max_digits=12, decimal_places=2)
    returns_nontaxed = models.DecimalField(max_digits=12, decimal_places=2)

    finance_transaction = models.ForeignKey(Transaction)

    def __str__(self):
        return "%s %s" % (self.date, self.description)


class OrderItem(models.Model):
    class Meta:
        db_table = 'order_items'

    # What order is this line item part of?
    order = models.ForeignKey(Order)

    # What was ordered?  This refers to BulkItem rather than Product since a
    # single unit ordered might contain multiple items with different UPC
    # barcodes.
    bulk_type = models.ForeignKey(BulkItem)

    # Number of individual items that come in each unit ordered.  Should match
    # bulk_type.quantity except in unusual cases.
    units_per_case = models.IntegerField(db_column='quantity')

    # Number of units ordered.  The total number of individual items received
    # will be number*quantity.
    cases_ordered = models.IntegerField(db_column='number')

    # Cost for each unit ordered.
    case_cost = models.DecimalField(max_digits=12, decimal_places=2)

    # The value of the CRV per unit
    crv_per_unit = models.DecimalField(max_digits=12, decimal_places=2)

    # Flags to indicate if the product or the CRV is taxed (sales)
    # Unfortunatly, the rules in CA for which products are taxed, and which
    # product's CRV is taxed are different.
    is_cost_taxed = models.BooleanField()
    is_crv_taxed = models.BooleanField()

    # Number of units scanned. Any time cases_scanned != cases_ordered, this
    # order_item has a problem that needs resolution.
    cases_scanned = models.IntegerField(db_column='n_scanned')

    def __str__(self):
        return "%d %s" % (self.cases_ordered, self.bulk_type)
