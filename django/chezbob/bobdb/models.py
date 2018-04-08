import datetime
from decimal import Decimal
from django.db import models, connection, transaction

# Current tax rate.  This is only used to compute current item prices.  For any
# historical analysis, the per-order tax rate stored with each order is used
# instead.
TAX_RATE = Decimal("0.0775")


class CharNullField(models.CharField):
    """Courtesy of https://code.djangoproject.com/ticket/9590."""
    description = "CharField that stores NULL but returns ''"

    def to_python(self, value):
        if isinstance(value, models.CharField):
            return value
        if value is None:
            return ""
        else:
            return value

    def get_db_prep_value(self, value, connection, prepared=False):
        if value == "":
            return None
        else:
            return value


class ProductSource(models.Model):
    class Meta:
        db_table = 'product_source'

    id = models.AutoField(db_column='sourceid', primary_key=True)
    description = models.CharField(db_column='source_description',
                                   max_length=255)

    def __str__(self):
        return self.description


class FloorLocations(models.Model):
    class Meta:
        db_table = 'floor_locations'

    id = models.AutoField(db_column='id', primary_key=True)
    name = models.CharField(db_column='name', max_length=255)
    markup = models.FloatField(db_column='markup')

    def __str__(self):
        return self.name

    @classmethod
    def get_all_locations(cls):
        """Return basic information about all floor locations.

        The returned value is a list of dictionaries. Each dictionary has keys
        for id, name and markup. id is also its index in the list.
        """
        cursor = connection.cursor()
        cursor.execute("""SELECT id, name, markup
                          FROM floor_locations ORDER BY id ASC""")

        locations = []
        for (fid, name, markup) in cursor.fetchall():
            locations.append({'id': fid, 'name': name, 'markup': markup})
        return locations


class BulkItem(models.Model):
    class Meta:
        db_table = 'bulk_items'

    bulkid = models.AutoField(primary_key=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=12, decimal_places=2)
    taxable = models.BooleanField()
    crv_per_unit = models.DecimalField(max_digits=12, decimal_places=2,
                                       verbose_name="CRV per-unit")
    crv_taxable = models.BooleanField()
    quantity = models.IntegerField()

    # For Django 1.2+, add auto_now=True to automatically update field when
    # record updated
    updated = models.DateField()
    source = models.ForeignKey(ProductSource, db_column='source')
    reserve = models.IntegerField()
    active = models.BooleanField(default=True)
    floor_location = models.ForeignKey(FloorLocations,
                                       db_column='floor_location')
    product_id = models.CharField(max_length=255, blank=True)

    bulkbarcode = CharNullField(max_length=32,
                                verbose_name="Bulk item barcode",
                                null=True, blank=True)

    def __str__(self):
        return self.description

    def cost_taxable(self):
        """Portion of total price which is taxed."""
        amt = Decimal("0.00")
        if self.taxable:
            amt += self.price
        if self.crv_taxable:
            amt += self.quantity * self.crv_per_unit
        return amt

    def cost_nontaxable(self):
        """Portion of total price which is not taxed."""

        amt = Decimal("0.00")
        if not self.taxable:
            amt += self.price
        if not self.crv_taxable:
            amt += self.quantity * self.crv_per_unit
        return amt

    def total_price(self):
        """Total price of a product, including all applicable tax and CRV."""
        amt = (1 + TAX_RATE) * self.cost_taxable() + self.cost_nontaxable()
        return amt.quantize(Decimal("0.01"))

    def unit_price(self):
        """Total price (including all taxes) for each individual item."""
        return (self.total_price() / self.quantity).quantize(Decimal("0.0001"))


class Product(models.Model):
    class Meta:
        db_table = 'products'

    barcode = models.CharField(max_length=32, primary_key=True)
    name = models.CharField(max_length=256)
    phonetic_name = models.CharField(max_length=256)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    bulk = models.ForeignKey(
        BulkItem, db_column='bulkid', null=True, blank=True)

    def __str__(self):
        return "%s [%s]" % (self.name, self.barcode)

    def get_absolute_url(self):
        return "/admin/products/%s/" % (self.barcode)

    def sales_stats(self):
        """Return a list with historical sales per day."""

        cursor = connection.cursor()
        cursor.execute("""SELECT date, sum(quantity) FROM aggregate_purchases
                          WHERE barcode = %s GROUP BY date ORDER BY date""",
                       [self.barcode])
        return cursor.fetchall()


class DynamicProduct(models.Model):
    """This is a view, and needs a userid specified to be tractable."""
    class Meta:
        db_table = 'dynamic_barcode_lookup'

    barcode = models.CharField(max_length=32, primary_key=True)
    name = models.CharField(max_length=256)
    phonetic_name = models.CharField(max_length=256)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    bulk = models.ForeignKey(
        BulkItem, db_column='bulkid', null=True, blank=True)
    userid = models.IntegerField(null=False, blank=False)

    def __str__(self):
        return "%s [%s]" % (self.name, self.barcode)


class HistoricalPrice(models.Model):
    class Meta:
        db_table = 'historical_prices'

    id = models.AutoField(primary_key=True)
    bulkid = models.ForeignKey(BulkItem, db_column='bulkid', blank=True)
    date = models.DateField()
    price = models.DecimalField(max_digits=12, decimal_places=2)

#class Order(models.Model):
#    class Meta:
#        db_table = 'orders'
#        permissions = [("edit_orders", "Enter Order Information")]
#
#    date = models.DateField()
#    description = models.CharField(max_length=256)
#    amount = models.DecimalField(max_digits=12, decimal_places=2)
#    tax_rate = models.DecimalField(max_digits=6, decimal_places=4)
#
#    def __str__(self):
#        return "%s %s" % (self.date, self.description)
#
#class OrderItem(models.Model):
#    class Meta:
#        db_table = 'order_items'
#
#    # What order is this line item part of?
#    order = models.ForeignKey(Order)
#
#    # What was ordered?  This refers to BulkItem rather than Product since a
#    # single unit ordered might contain multiple items with different UPC
#    # barcodes.
#    bulk_type = models.ForeignKey(BulkItem)
#
#    # Number of individual items that come in each unit ordered.  Should match
#    # bulk_type.quantity except in unusual cases.
#    quantity = models.IntegerField()
#
#    # Number of units ordered.  The total number of individual items received
#    # will be number*quantity.
#    number = models.IntegerField()
#
#    # Cost for each unit ordered.  To get the total cost, multiply by number.
#    # The cost is split into taxable and non-taxable components; we do this
#    # instead of using a "taxable" boolean since both could be present (for
#    # example, item is not taxable but the CRV on the item is).  In most
#    # cases, one of the costs will be zero.
#    cost_taxable = models.DecimalField(max_digits=12, decimal_places=2)
#    cost_nontaxable = models.DecimalField(max_digits=12, decimal_places=2)
#
#    def __str__(self):
#        return "%d %s" % (self.number, self.bulk_type)


# This class doesn't actually connect directly with the underlying database
# table, but the class methods provided do perform useful queries.
class Inventory(models.Model):
    class Meta:
        db_table = 'inventory'

    inventoryid = models.AutoField(primary_key=True)
    inventory_time = models.DateTimeField()

    def __str__(self):
        return "#%d %s" % (self.inventoryid, self.inventory_time)

    @classmethod
    def all_inventories(cls):
        cursor = connection.cursor()
        cursor.execute(
            "SELECT DISTINCT date::date AS date FROM inventory ORDER BY date")
        return [r[0] for r in cursor.fetchall()]

    @classmethod
    def get_inventory(cls, date):
        """Returns counts for all items with inventory taken on the given day.

        The returned value is a dictionary mapping a bulkid to a tuple (count,
        cases, loose, case_size).  count is the number of the item at the time
        of inventory, and cases is the number of full cases, and loose is the
        number of loose units of the item.  case_size is the number of units in
        a case (at the time the inventory was taken).
        """

        cursor = connection.cursor()
        cursor.execute("""SELECT bulkid, units, cases, loose_units, case_size
                          FROM inventory
                          WHERE date::date = %s""", [date])

        inventory = {}
        for (bulkid, units, cases, loose, case_size) in cursor.fetchall():
            inventory[bulkid] = (units, cases, loose, case_size)
        return inventory

    @classmethod
    def set_inventory(cls, date, bulkid, count, cases, loose, case_size):
        """Insert a record with an inventory estimate for a product.

        Create a record of the inventory count for the given product on the
        given day.  If a record already exists, it is overwritten.  If count is
        None, then any existing inventory count for the given day is deleted.
        """

        cursor = connection.cursor()

        cursor.execute("""DELETE FROM inventory
                          WHERE date::date = %s AND bulkid = %s""",
                       (date, bulkid))

        if count is not None:
            cursor.execute("""INSERT INTO inventory(date, bulkid, units, cases, loose_units, case_size)
                              VALUES (%s, %s, %s, %s, %s, %s)""",
                           (date, bulkid, count, cases, loose, case_size))

        transaction.commit_unless_managed()

    @classmethod
    def get_inventory_summary(cls, date, include_latest=True):
        """Returns a summary of estimated inventory of all items on the given date.\

        The returned value is a dictionary mapping a bulkid to a second
        per-item dictionary with the following keys:
            estimate: estimate for the inventory
            date: date last inventory was taken for this item
            old_count: count at last inventory
            activity: has this product inventory changed
            sales: number of this item sold since last inventory
            purchases: number of this item received since last inventory

        If include_latest is True and an inventory was taken on the specified
        date, that value is returned.  If include_latest is False, then the
        returned value reports the previous inventory and sales/purchases since
        then.  Generally include_latest=True gives better results, but
        include_latest=False is useful for the inventory-taking page itself to
        report what would be expected in the absence of the new inventory data.
        """

        inventory_date = date

        if not include_latest:
            inventory_date -= datetime.timedelta(days=1)

#
# TODO - Use this version of the query once postgre 8.4+ is installed
#

#        sql = """
#with start_dates as
#   (select bulkid, max(date::date) as date from inventory
#       where date::date <= %s group by bulkid)
#select * from
#   (select bulkid, date::date, units
#       from start_dates natural join inventory) s1
#natural full outer join
#   (select a.bulkid, sum(quantity) as sales
#       from aggregate_purchases a left join start_dates using (bulkid)
#       where coalesce(a.date::date > start_dates.date, true)
#         and a.date::date <= %s
#       group by bulkid) s2
#natural full outer join
#   (select oi.bulk_type_id as bulkid,
#           sum(oi.quantity * oi.number) as purchases
#       from orders o
#           join order_items oi on o.id = oi.order_id
#           left join start_dates on start_dates.bulkid = oi.bulk_type_id
#       where coalesce(o.date::date > start_dates.date, true)
#         and o.date::date <= %s
#       group by oi.bulk_type_id) s3
#where bulkid is not null
#order by bulkid;"""
#
#        args = (inventory_date, date, date)

#
# This version compatable with postgre <8.4
#
        sql = """
select *
from (select bulkid, date, units
      from (select bulkid, max(date::date) as date
            from inventory
            where date::date <= %s
            group by bulkid) s1a
      natural join inventory) s1
natural full outer join
    (select a.bulkid, sum(quantity) as sales
     from aggregate_purchases a
     left join
         (select bulkid, max(date::date) as date
          from inventory
          where date::date <= %s
          group by bulkid) s2a using (bulkid)
     where coalesce(a.date::date > s2a.date, true) and a.date::date <= %s
     group by bulkid) s2
natural full outer join
    (select oi.bulk_type_id as bulkid,
     sum(oi.quantity * oi.number) as purchases
     from orders o
     join order_items oi on o.id = oi.order_id
     left join
         (select bulkid, max(date::date) as date
          from inventory
          where date::date <= %s
          group by bulkid) s3a on s3a.bulkid = oi.bulk_type_id
     where coalesce(o.date::date > s3a.date, true) and o.date::date <= %s
     group by oi.bulk_type_id) s3
where bulkid is not null
"""
        args = (inventory_date, inventory_date, date, inventory_date, date)

#
# End postgre <8.4 code
#

        cursor = connection.cursor()

        cursor.execute(sql, args)

        summary = {}
        for (bulkid, date, units, sales, purchases) in cursor.fetchall():
            if sales is None:
                sales = 0
            if purchases is None:
                purchases = 0
            if units is None:
                units = 0

            summary[bulkid] = {'estimate': units + purchases - sales,
                               'date': date,
                               'old_count': units,
                               'activity': sales > 0 or purchases > 0,
                               'sales': sales,
                               'purchases': purchases}

        return summary

    @classmethod
    def get_sales(cls, date_from, date_to):
        """Returns total sales of each bulk item in the given date range."""

        cursor = connection.cursor()

        cursor.execute("""SELECT bulkid, sum(aggregate_purchases.quantity)
                          FROM aggregate_purchases
                          WHERE date::date >= %s AND date::date <= %s
                                AND bulkid is not NULL
                          GROUP BY bulkid""", [date_from, date_to])
        return dict(cursor.fetchall())
