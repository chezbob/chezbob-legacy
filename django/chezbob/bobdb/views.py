import base64, datetime, math
from time import strptime

from django.shortcuts import render_to_response, get_object_or_404
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse, HttpResponseRedirect
from chezbob.bobdb.models import BulkItem, Inventory, Product, Order, OrderItem, ProductSource, TAX_RATE

def parse_date(datestr):
    """Parse a string representation of a date into a datetime.Date object.

    At the moment this only supports ISO-style dates (2007-01-31).  In the
    future it might be extended to other formats, and auto-detect.
    """

    if isinstance(datestr, datetime.date): return datestr
    return datetime.date(*strptime(datestr, "%Y-%m-%d")[0:3])

# It may be better to switch to a per-form key rather than a per-session key,
# but this should provide some protection for now.
def get_session_key(request):
    """Return a session key associated with this user.

    If a session key does not yet exist, one will be generated and saved with
    the session state in the database.  The session key can be used as a second
    form of authorization in addition to the session cookie--it should be
    included as a hidden field in any form which makes any changes, and
    verified before committing any changes.  Doing so will guard against
    cross-site request forgery attacks.
    """

    session = request.session

    KEY_FIELD = 'chezbob_session_key'
    if KEY_FIELD not in session:
        random_bytes = open('/dev/urandom').read(9)
        session[KEY_FIELD] = base64.b64encode(random_bytes)

    return session[KEY_FIELD]

##### Product summary information #####
@login_required
def products(request):
    products = list(Product.objects.all())

    for p in products:
        try:
            p.markup_amt = p.price - p.bulk.unit_price()
            p.markup_pct = ((p.price / p.bulk.unit_price()) - 1.0) * 100
        except ObjectDoesNotExist:
            pass

    if request.GET.has_key('short'):
        def filter(p):
            try:
                if not p.bulk.active: return False
            except ObjectDoesNotExist:
                return False
            return True
        products = [p for p in products if filter(p)]

    def sort_field(p):
        try:
            key = int(request.GET.get("o", 0))
            if key == 0:
                return p.name
            elif key == 1:
                return p.price
            elif key == 2:
                return p.bulk.unit_price()
            elif key == 3:
                return p.markup_amt
            elif key == 4:
                return p.markup_pct
        except:
            return None
    products.sort(lambda x, y: cmp(sort_field(x), sort_field(y)))

    return render_to_response('bobdb/product_list.html',
                              {'user': request.user,
                               'title': "Products Overview",
                               'products': products})

@login_required
def product_detail(request, barcode):
    product = get_object_or_404(Product, barcode=barcode)

    try:
        product.markup_amt = product.price - product.bulk.unit_price()
        product.markup_pct = ((product.price / product.bulk.unit_price()) - 1.0) * 100
    except ObjectDoesNotExist:
        pass

    return render_to_response('bobdb/product_detail.html',
                              {'user': request.user,
                               'title': "Product Detail",
                               'product': product})

##### Order tracking #####
edit_orders_required = \
    user_passes_test(lambda u: u.has_perm('bobdb.edit_orders'))

@login_required
def view_order(request, order):
    order = get_object_or_404(Order, id=int(order))
    items = order.orderitem_set.all()

    return render_to_response('bobdb/order_info.html',
                              {'user': request.user,
                               'title': "Order Summary",
                               'order': order,
                               'items': items})

@edit_orders_required
def update_order(request, order):
    order = get_object_or_404(Order, id=int(order))

    item_list = []              # Items stored in the database
    new_items = []              # New entries not yet written to database

    # If any POST data was submitted, process it, since it might include
    # updates to existing items or new items.  We can distinguish the two
    # because existing items will include an "id." field.
    try:
        n = 0
        while True:
            n = str(int(n) + 1)

            try: number = int(request.POST['number.' + n])
            except ValueError: number = 0
            if number < 0: number = 0

            # Update to existing item in the database.  If quantity has
            # been cleared, then delete this item.  Otherwise, make any
            # appropriate edits.
            order_item = None
            try:
                id = int(request.POST['id.' + n])
                order_item = OrderItem.objects.get(id=id)
            except: pass

            if order_item:
                if not number:
                    order_item.delete()
                else:
                    order_item.number = number
                    order_item.quantity \
                        = int(request.POST['quantity.' + n])
                    order_item.cost_taxable \
                        = float(request.POST['taxable.' + n])
                    order_item.cost_nontaxable \
                        = float(request.POST['nontaxable.' + n])
                    order_item.save()
                continue

            # Filling in details for an entry.  If complete, save to the
            # database.
            if request.POST.has_key('type_code.' + n):
                if not number: continue

                try:
                    bulk_code = int(request.POST['type_code.' + n])
                    bulk_type = BulkItem.objects.get(bulkid=bulk_code)
                    quantity = int(request.POST['quantity.' + n])
                    nontaxable = float(request.POST['nontaxable.' + n])
                    taxable = float(request.POST['taxable.' + n])
                    order_item = OrderItem(order=order,
                                           bulk_type=bulk_type,
                                           quantity=quantity,
                                           number=number,
                                           cost_taxable=taxable,
                                           cost_nontaxable=nontaxable)
                    order_item.save()
                except:
                    pass

                continue

            # New entry.  Perform a search based on the name for matching
            # items, and add them to new_items so the user can fill in the rest
            # of the details.
            name = request.POST['type.' + n]
            if not name: continue

            if not number: number = ""
            matches = BulkItem.objects.filter(description__icontains=name)

            # If there were no matches, re-present the query to the user.
            if len(matches) == 0:
                new_items.append({'blank': True,
                                  'type': name})

            # Force user to re-enter numbers if multiple matches occurred.
            if len(matches) > 1: number = ""

            for m in matches:
                new_items.append({'blank': False,
                                  'type': m,
                                  'number': number,
                                  'quantity': m.quantity,
                                  'nontaxable': m.cost_nontaxable(),
                                  'taxable': m.cost_taxable()})
    except KeyError:
        # Assume we hit the end of the inputs
        pass

    # Include all items listed in the database for this order.
    total_notax = 0.0
    total_tax = 0.0
    for i in order.orderitem_set.order_by('id'):
        item = {'blank': False,
                'id': i.id,
                'number': i.number,
                'quantity': i.quantity,
                'type': i.bulk_type,
                'nontaxable': i.cost_nontaxable,
                'taxable': i.cost_taxable}
        if abs(i.cost_nontaxable - i.bulk_type.cost_nontaxable()) \
                + abs(i.cost_taxable - i.bulk_type.cost_taxable()) > 0.005:
            item['message'] = "Price differs from bulk data"
        item_list.append(item)
        total_notax += i.cost_nontaxable * i.number
        total_tax += i.cost_taxable * i.number

    total = round(total_notax + total_tax * (1 + TAX_RATE), 2)

    for i in range(5):
        new_items.append({'blank': True})

    return render_to_response('bobdb/order_update.html',
                              {'user': request.user,
                               'title': "Update Order",
                               'order': order,
                               'items': item_list + new_items,
                               'total_notax': total_notax,
                               'total_tax': total_tax,
                               'total': total})

##### Sales Stats by Bulk Type #####
@login_required
def inventory(request):
    bulk = BulkItem.objects.order_by('description')

    return render_to_response('bobdb/inventory_list.html',
                              {'user': request.user,
                               'title': "Inventory Overview",
                               'items': bulk})

@login_required
def inventory_detail(request, bulkid):
    item = get_object_or_404(BulkItem, bulkid=bulkid)

    # The individual products sold that fall under this bulk item--for example,
    # the bulk item might be a variety pack, and the individual products are
    # each of the flavors (assuming a separate barcode for each).
    products = item.product_set.all()

    # Construct a table giving both aggregate daily sales statistics for this
    # item, and records of purchases made.  Dictionary is keyed by date.  Each
    # value is a tuple (sales, received).
    daily_stats = {}
    for p in products:
        for (date, sales) in p.sales_stats():
            if not daily_stats.has_key(date): daily_stats[date] = [0, 0]
            daily_stats[date][0] += sales

    for order in item.orderitem_set.all():
        date = order.order.date
        if not daily_stats.has_key(date): daily_stats[date] = [0, 0]
        daily_stats[date][1] += order.number * order.quantity

    # Produce a flattened version of the daily sales stats: convert it to a
    # list, sorted by date, of dictionaries with keys ('date', 'sales',
    # 'purchases').
    daily_stats_list = []
    dates = daily_stats.keys()
    dates.sort()
    for d in dates:
        stats = daily_stats[d]
        daily_stats_list.append({'date': d,
                                 'sales': stats[0], 'purchases': stats[1]})

    # If a starting date was provided, drop any statistics before that point in
    # time.
    try:
        since = datetime.date(*strptime(request.GET['since'], "%Y-%m-%d")[0:3])
    except:
        since = None

    if since:
        daily_stats_list = [d for d in daily_stats_list
                            if d['date'] >= since]

    # Produce cumulative sales statistics.  Store them under keys 'sales_sum'
    # and 'purchases_sum'.
    sales_sum = 0
    purchases_sum = 0
    for day in daily_stats_list:
        sales_sum += day['sales']
        purchases_sum += day['purchases']
        day['sales_sum'] = sales_sum
        day['purchases_sum'] = purchases_sum
        day['inventory'] = purchases_sum - sales_sum

    return render_to_response('bobdb/inventory_detail.html',
                              {'user': request.user,
                               'title': "Inventory Detail",
                               'item': item,
                               'raw_stats': daily_stats,
                               'stats': daily_stats_list})

##### Inventory Tracking and Order Estimation #####
inventory_perm_required = \
    user_passes_test(lambda u: u.has_perm('bobdb.change_inventory'))

@inventory_perm_required
def list_inventories(request):
    return render_to_response('bobdb/list_inventories.html',
                              {'user': request.user,
                               'title': "Available Inventories",
                               'today': datetime.date.today(),
                               'dates': Inventory.all_inventories()})

@inventory_perm_required
def take_inventory(request, date):
    date = parse_date(date)

    # If a POST request was submitted, apply any updates to the inventory data
    # in the database before rendering the response.
    if request.method == 'POST':
        if request.POST.get('session_key') != get_session_key(request):
            raise PermissionDenied

    try:
        n = 0
        while True:
            n = str(int(n) + 1)

            bulkid = int(request.POST['id.' + n])

            count = 0
            count_valid = False
            try:
                count = float(request.POST['cases.' + n]) \
                        * int(request.POST['multiplier.' + n])
                count = int(round(count))
                count_valid = True
            except:
                pass

            try:
                count += int(request.POST['items.' + n])
                count_valid = True
            except:
                pass

            if not count_valid: count = None

            exact = request.POST.has_key('exact.' + n)

            # Compare with previous values, and only update database if there
            # was a change.
            old_exact = request.POST.has_key('old_exact.' + n)
            try:
                old_count = int(request.POST['old_count.' + n])
            except:
                old_count = None

            if old_exact != exact or old_count != count:
                Inventory.set_inventory(date, bulkid, count, exact)

    except KeyError:
        # Assume we hit the end of the POST inputs
        pass

    counts = Inventory.get_inventory(date)
    previous = Inventory.last_inventory(date - datetime.timedelta(days=1))

    items = []
    for i in BulkItem.objects.order_by('description'):
        # active is set to True if the count for this item is non-zero, or if
        # there have been any purchases or sales since the last inventory.
        active = False

        d = {'type': i, 'count_unit': "", 'count_item': "", 'exact': True}
        if i.bulkid in counts:
            inv = counts[i.bulkid]
            d.update({'count': inv[0],
                      'count_unit': inv[0] // i.quantity,
                      'count_item': inv[0] % i.quantity,
                      'exact': inv[1]})
            if inv[0]: active = True
        if i.bulkid in previous:
            d.update({'prev_date': previous[i.bulkid][0],
                      'prev_count': previous[i.bulkid][1]})
            start_date = previous[i.bulkid][0] + datetime.timedelta(days=1)
        else:
            d['prev_count'] = 0
            start_date = None
        if d['prev_count']: active = True
        (sales, purchases) = Inventory.estimate_change(i.bulkid,
                                                       start_date, date)
        d.update({'est_add': purchases, 'est_sub': sales})
        d['estimate'] = d['prev_count'] + purchases - sales
        if sales or purchases: active = True
        d['active'] = active
        items.append(d)

    return render_to_response('bobdb/take_inventory.html',
                              {'user': request.user,
                               'title': "Take Inventory",
                               'date': date,
                               'items': items,
                               'session_key': get_session_key(request)})

@inventory_perm_required
def estimate_order(request):
    products = BulkItem.objects.order_by('description')
    inventory = Inventory.get_inventory_estimate(datetime.date.today(), True)

    source = int(request.GET.get("source", 1))
    date_to = parse_date(request.GET.get("to", datetime.date.today()))
    date_from = parse_date(request.GET.get("from", date_to - datetime.timedelta(days=14)))
    sales = Inventory.get_sales(date_from, date_to)

    cost = 0.0
    items = []
    for p in products:
        if p.source.id != source: continue
        info = {'type': p,
                'inventory': inventory[p.bulkid],
                'sales': sales.get(p.bulkid, 0)}

        needed = info['sales'] - max(info['inventory']['estimate'], 0)
        needed += p.reserve
        needed = float(needed) / p.quantity
        if info['inventory']['estimate'] <= 0 and info['sales'] > 0:
            needed += 0.5
        needed = max(int(math.ceil(needed)), 0)
        info['order'] = needed
        info['cost'] = needed * p.total_price()
        cost += info['cost']

        items.append(info)

    return render_to_response('bobdb/estimate_order.html',
                              {'user': request.user,
                               'title': "Order Estimatation",
                               'source': source,
                               'sources': ProductSource.objects.order_by('description'),
                               'date_from': date_from,
                               'date_to': date_to,
                               'items': items,
                               'cost': cost})

@inventory_perm_required
def display_order(request):
    response = HttpResponse(mimetype="text/plain")

    cost = 0.0

    try:
        n = 0
        while True:
            n = str(int(n) + 1)

            bulkid = int(request.POST['id.' + n])
            quantity = int(request.POST['order.' + n])

            if quantity > 0:
                product = BulkItem.objects.get(bulkid=bulkid)
                response.write("%-4d %s\n" % (quantity, product.description))
                cost += quantity * product.total_price()

    except KeyError:
        # Assume we hit the end of the POST inputs
        pass

    response.write("\nEstimated Cost: $%.2f\n" % (cost,))

    return response