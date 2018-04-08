from __future__ import print_function

import datetime
from decimal import Decimal

from django import forms
from django.shortcuts import render_to_response, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from chezbob.bobdb.models import BulkItem
from chezbob.finance.models import Transaction, Split
from chezbob.orders.models import Order, OrderItem
import chezbob.shortcuts as bobcuts

from django.core.urlresolvers import reverse

DEFAULT_SALES_TAX = 0.0775


def coerce_boolean(s):
    """Convert a string to a boolean value.

    For handling AJAX inputs, we probably only need to handle 'true' and
    'false', but for robustness accept a few other strings that might be used
    to represent a boolean."""

    s = str(s).lower().strip()
    if s in ('', 'f', 'false', '0', 'off'):
        return False
    elif s in ('t', 'true', '1', 'on'):
        return True
    else:
        # Perhaps ought to raise an error?
        return True


# Order tracking #
edit_orders_required = user_passes_test(
    lambda u: u.has_perm('bobdb.edit_orders'))


@edit_orders_required
def order_list(request):
    mes = bobcuts.BobMessages()
    mes['orders'] = Order.objects.all().order_by('-date')
    mes['title']    = "List of Orders"
    reverse(order_summary, args=(167,))
    return render_to_response('orders/order_list.html', mes)


class OrderForm(forms.Form):
    date                     = forms.DateField(initial=datetime.date.today())
    description        = forms.CharField()
    amount                 = forms.DecimalField()
    sales_tax_rate = forms.DecimalField(initial=DEFAULT_SALES_TAX)


@edit_orders_required
def order_summary(request, order):
    messages = bobcuts.BobMessages()
    order = get_object_or_404(Order, id=int(order))

    # helper methods
    def simp(obj):
        new = {}
        for key in obj.__dict__:
            if not key.startswith("_"):
                new[key] = obj.__dict__[key]
        return new

    def order_item_expand(oi):
        oi.amount = oi.case_cost * oi.cases_ordered
        oi.crv_amount = oi.crv_per_unit * oi.units_per_case * oi.cases_ordered
        oi.price_differs = (
            oi.case_cost != oi.bulk_type.price or
            oi.is_cost_taxed != oi.bulk_type.taxable)
        oi.crv_differes = (
            oi.crv_per_unit != oi.bulk_type.crv_per_unit or
            oi.is_crv_taxed != oi.bulk_type.crv_taxable)
        oi.quantity_differs = oi.units_per_case != oi.bulk_type.quantity

    # handle ajax requests
    if 'ajax' in request.POST:
        if request.POST['ajax'] == 'update_bulk_price':
            bulk_id     = request.POST['bulk_id']
            new_price   = request.POST['new_price']
            is_taxed    = request.POST['is_taxed']
            date        = request.POST['date']
            bulk_item   = BulkItem.objects.get(bulkid=bulk_id)
            bulk_item.price = new_price
            bulk_item.taxable = coerce_boolean(is_taxed)
            bulk_item.updated = date
            bulk_item.save()
            messages['new_bulk'] = simp(bulk_item)
        elif request.POST['ajax'] == 'update_bulk_quantity':
            bulk_id   = request.POST['bulk_id']
            new_count = request.POST['new_count']
            date      = request.POST['date']
            bulk_item = BulkItem.objects.get(bulkid=bulk_id)
            bulk_item.quantity = new_count
            bulk_item.updated = date
            bulk_item.save()
            messages['new_bulk'] = simp(bulk_item)
        elif request.POST['ajax'] == 'new_order_item':
            bulk_id = int(request.POST['bulk_id'])
            count     = int(request.POST['count'])
            bulk_item = BulkItem.objects.get(bulkid=bulk_id)
            item = OrderItem(order=order,
                             bulk_type=bulk_item,
                             units_per_case=bulk_item.quantity,
                             cases_ordered=count,
                             case_cost=bulk_item.price,
                             crv_per_unit=bulk_item.crv_per_unit,
                             is_cost_taxed=bulk_item.taxable,
                             is_crv_taxed=bulk_item.crv_taxable)
            item.save()
            order_item_expand(item)
            messages['new_order_item'] = simp(item)
        elif request.POST['ajax'] == 'delete_order_item':
            item_id = request.POST['item_id']
            item = OrderItem.objects.get(id=item_id)
            if item.order.id == order.id:
                order_item_expand(item)
                messages['deleted_order_item'] = simp(item)
                item.delete()
            else:
                messages.add(
                    "Can only delete items that are part of this order")
        elif request.POST['ajax'] == 'update_order_item':
            item_id = request.POST['id']
            item = OrderItem.objects.get(id=item_id)
            messages['old_order_item'] = simp(item)
            item.cases_ordered  = int(request.POST['cases_ordered'])
            item.units_per_case = int(request.POST['units_per_case'])
            item.case_cost      = Decimal(request.POST['case_cost'])
            item.is_cost_taxed  = coerce_boolean(request.POST['is_cost_taxed'])
            item.crv_per_unit   = Decimal(request.POST['crv_per_unit'])
            item.is_crv_taxed   = coerce_boolean(request.POST['is_crv_taxed'])
            item.save()
            order_item_expand(item)
            messages['new_order_item'] = simp(item)
        elif request.POST['ajax'] == 'update_details':
            order_form = OrderForm(request.POST)
            if order_form.is_valid():
                order.date          = order_form.cleaned_data['date']
                order.description   = order_form.cleaned_data['description']
                order.amount        = order_form.cleaned_data['amount']
                order.tax_rate      = order_form.cleaned_data['sales_tax_rate']
                order.save()
            else:
                for error_field in order_form.errors:
                    messages.error(
                        "Field '%s': %s"
                        % (error_field, order_form[error_field].errors))
        elif request.POST['ajax'] == 'update_finance_details':
            print(repr(request.POST))
            order.inventory_adjust  = request.POST['inventory_adjust']
            order.supplies_taxed    = request.POST['supply_taxed']
            order.supplies_nontaxed = request.POST['supply_nontaxed']
            order.supplies_adjust   = request.POST['supply_adjust']
            order.returns_taxed     = request.POST['refund_taxed']
            order.returns_nontaxed  = request.POST['refund_nontaxed']
            order.save()
        elif request.POST['ajax'] == 'get_bulk_items':
            bulk_items = BulkItem.objects.all().order_by('description')
            simp_bulk_items = []
            for item in bulk_items:
                simp_bulk_items.append(simp(item))
            messages['bulk_items'] = simp_bulk_items
        elif request.POST['ajax'] == 'create_transaction':
            bank = request.POST['bank']
            inventory = request.POST['inventory']
            supplies = request.POST['supplies']
            newTran = Transaction()
            newTran.date = order.date
            newTran.description = order.description
            newTran.save()
            Split(  # bank
                transaction=newTran, amount=bank, account_id=1).save()
            Split(  # inventory
                transaction=newTran, amount=inventory, account_id=5).save()
            Split(  # lounge supplies
                transaction=newTran, amount=supplies, account_id=8).save()
            order.finance_transaction = newTran

            messages['new_tran_id'] = newTran.id
        elif request.POST['ajax'] == 'sync_transaction':
            bank = request.POST['bank']
            inventory = request.POST['inventory']
            supplies = request.POST['supplies']
            for split in order.finance_transaction.split_set.all():
                if split.account_id == 1:  # bank
                    split.amount = bank
                if split.account_id == 5:  # inventory
                    split.amount = inventory
                if split.account_id == 8:  # lounge supplies
                    split.amount = supplies
                split.save()
        else:
            messages.error("unknown ajax command '%s'" % request.POST['ajax'])
        return bobcuts.JsonResponse(messages)

    order_form = OrderForm({'date': order.date,
                            'amount': order.amount,
                            'description': order.description,
                            'sales_tax_rate': order.tax_rate})

    if 'save_details' in request.POST:
        order_form = OrderForm(request.POST)
        if order_form.is_valid():
            order.date = order_form.cleaned_data['date']
            order.description = order_form.cleaned_data['description']
            order.amount = order_form.cleaned_data['amount']
            order.tax_rate = order_form.cleaned_data['sales_tax_rate']
            order.save()
        else:
            for error_field in order_form.errors:
                messages.error(
                    "Field %s: %s"
                    % (error_field, order_form[error_field].errors))

    if 'add_item' in request.POST:
        bulk_id = int(request.POST['new_item'])
        cases_count = int(request.POST['new_count'])
        bulk_item = BulkItem.objects.get(bulkid=bulk_id)
        item = OrderItem(order=order,
                         bulk_type=bulk_item,
                         units_per_case=bulk_item.quantity,
                         cases_ordered=cases_count,
                         case_cost=bulk_item.price,
                         crv_per_unit=bulk_item.crv_per_unit,
                         is_cost_taxed=bulk_item.taxable,
                         is_crv_taxed=bulk_item.crv_taxable)
        item.save()
        messages.note("New item(s) added to order: %s." % (item,))

    new_items = []  # New entries not yet written to database

    # If any POST data was submitted, process it, since it might include
    # updates to existing items or new items.    We can distinguish the two
    # because existing items will include an "id." field.
    try:
        n = 0
        while True:
            n = str(int(n) + 1)

            try:
                number = int(request.POST['number.' + n])
            except ValueError:
                number = 0
            if number < 0:
                number = 0

            # Update to existing item in the database.    If quantity has
            # been cleared, then delete this item.    Otherwise, make any
            # appropriate edits.
            order_item = None
            try:
                id = int(request.POST['id.' + n])
                order_item = OrderItem.objects.get(id=id)
            except:  # noqa
                pass

            if order_item:
                if not number:
                    order_item.delete()
                else:
                    order_item.number = number
                    order_item.quantity = int(request.POST['quantity.' + n])
                    order_item.cost_taxable = Decimal(
                        request.POST['taxable.' + n])
                    order_item.cost_nontaxable = Decimal(
                        request.POST['nontaxable.' + n])
                    order_item.save()
                continue

            # Filling in details for an entry.    If complete, save to the
            # database.
            if ('type_code.' + n) in request.POST:
                if not number:
                    continue

                try:
                    bulk_code = int(request.POST['type_code.' + n])
                    bulk_type = BulkItem.objects.get(bulkid=bulk_code)
                    quantity = int(request.POST['quantity.' + n])
                    nontaxable = Decimal(request.POST['nontaxable.' + n])
                    taxable = Decimal(request.POST['taxable.' + n])
                    order_item = OrderItem(order=order,
                                           bulk_type=bulk_type,
                                           quantity=quantity,
                                           number=number,
                                           cost_taxable=taxable,
                                           cost_nontaxable=nontaxable)
                    order_item.save()
                except:  # noqa
                    pass

                continue

            # New entry.    Perform a search based on the name for matching
            # items, and add them to new_items so the user can fill in the rest
            # of the details.
            name = request.POST['type.' + n]
            if not name:
                continue

            if not number:
                number = ""
            matches = BulkItem.objects.filter(description__icontains=name)

            # If there were no matches, re-present the query to the user.
            if len(matches) == 0:
                new_items.append({'blank': True, 'type': name})

            # Force user to re-enter numbers if multiple matches occurred.
            if len(matches) > 1:
                number = ""

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
    total_taxed        = Decimal("0.00")
    total_nontaxed = Decimal("0.00")

    items = order.orderitem_set.order_by('id')
    for i in items:
        order_item_expand(i)
        if i.is_cost_taxed:
            total_taxed += i.amount
        else:
            total_nontaxed += i.amount
        if i.is_crv_taxed:
            total_taxed += i.crv_amount
        else:
            total_nontaxed += i.crv_amount

    total = total_nontaxed + total_taxed * (1 + order.tax_rate)
    total = total.quantize(Decimal("0.01"))

    bulk_items = BulkItem.objects.all().order_by('-active', 'description')
    simp_bulk_items = []
    for bi in bulk_items:
        sbi = simp(bi)
        if not bi.active:
            sbi["description"] = '[inactive] ' + sbi["description"]
        simp_bulk_items.append(sbi)

    messages['transaction'] = False
    messages['transaction_complicated'] = False
    messages['transaction_bank'] = 0
    messages['transaction_inventory'] = 0
    messages['transaction_supplies'] = 0

    if order.finance_transaction_id is not None:
        messages['transaction'] = True
        splits = order.finance_transaction.split_set.all()
        if len(splits) != 3:
            messages['transaction_complicated'] = True
        else:
            for split in splits:
                if split.account_id == 1:
                    messages['transaction_bank'] = split.amount
                elif split.account_id == 5:
                    messages['transaction_inventory'] = split.amount
                elif split.account_id == 8:
                    messages['transaction_supplies'] = split.amount
                else:
                    messages['transaction_complicated'] = True

    messages.extend({'user': request.user,
                     'title': 'Order Summary - ' + str(order.date),
                     'details_form': order_form,
                     'order': order,
                     'items': items,
                     'total_notax': total_nontaxed,
                     'total_tax': total_taxed,
                     'total': total,
                     'bulk_items': simp_bulk_items})

    return render_to_response('orders/order_summery.html', messages)


@edit_orders_required
def new_order(request):
    order_form = OrderForm()
    messages = bobcuts.BobMessages()
    if 'save_details' in request.POST:
        order_form = OrderForm(request.POST)
        if order_form.is_valid():
            newOrder = Order(
                date=order_form.cleaned_data['date'],
                description=order_form.cleaned_data['description'],
                amount=order_form.cleaned_data['amount'],
                tax_rate=order_form.cleaned_data['sales_tax_rate'])
            newOrder.save()
            newId = newOrder.id
            return bobcuts.redirect_or_error(
                reverse(order_summary, args=(newId,)), messages)
        else:
            for error_field in order_form.errors:
                messages.error("Field %s: %s"
                               % (error_field, order_form[error_field].errors))
            return bobcuts.error(messages)
    messages.extend({'user': request.user,
                     'title': 'New Order',
                     'details_form': OrderForm(),
                     'order': {},
                     'items': [],
                     'total_notax': 0,
                     'total_tax': 0,
                     'total': 0,
                     'bulk_items': BulkItem.objects.all().order_by(
                         'description')})
    return render_to_response('orders/order_summery.html', messages)
