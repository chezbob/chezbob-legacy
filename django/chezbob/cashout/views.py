import datetime
from decimal import Decimal, InvalidOperation
import time
#from time import strptime
from django.shortcuts import render_to_response, get_object_or_404
from django.core.exceptions import ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf.urls import *
from django.http import HttpResponse, HttpResponseRedirect
from chezbob.cashout.models import CashOut, Entity, CashCount

import chezbob.finance.models as finance
from django.core.paginator import Paginator, InvalidPage, EmptyPage

import re

view_perm_required = \
        user_passes_test(lambda u: u.has_perm('cashout.view_cashouts'))
edit_perm_required = \
        user_passes_test(lambda u: u.has_perm('cashout.change_cashout'))

time_format = "%Y-%m-%d %H:%M"
time_format2 = "%Y-%m-%d %H:%M:%S"

count_per_page = 25

def parse_datetime(datetimestr):
    try:
        return time.strftime(time_format,(time.strptime(datetimestr, time_format)))
    except ValueError:
        pass

    return time.strftime(time_format2,(time.strptime(datetimestr, time_format2)))

def datetimetodate(datetimestr):
    try:
        return time.strftime("%Y-%m-%d",(time.strptime(datetimestr, time_format)))
    except ValueError:
        pass

    return time.strftime("%Y-%m-%d",(time.strptime(datetimestr, time_format2)))


@view_perm_required
def ledger(request):
    title = 'Cashouts'

    cashout_count = CashOut.objects.count()
    all_cashouts = CashOut.objects.all().order_by('datetime')
    paginator = Paginator(range(0, cashout_count), count_per_page)

    default_pagenum = paginator.num_pages
    try:
        pagenum = int(request.GET.get('page', default_pagenum))
    except:
        pagenum = default_pagenum

    try:
        page = paginator.page(pagenum)
    except (EmptyPage, InvalidPage):
        page = paginator.page(paginator.num_pages)

    # Slice
    page_cashouts = all_cashouts[page.object_list[0]:page.object_list[-1]+1]

    cashouts = []
    balance = CashOut.balance_before(page_cashouts[0])

    for c in page_cashouts:
        total = 0
        cashcount_list = []

        for s in CashCount.objects.filter(cashout=c):
            cashcount = {'memo': s.memo,
                         'entity': s.entity,
                         'total': s.total}
            total += s.total

            cashcount_list.append(cashcount)

        balance += total

        cashouts.append({
            'info': c, 
            'counts': cashcount_list,
            'total':total,
            'balance':balance
            })



    return render_to_response('cashout/cashouts.html',
                              {'title': title,
                               'cashouts': cashouts,
                               'page': page
                               })

@view_perm_required
def cashonhand(request):
    title = 'Cashouts'

    cashout_count = CashOut.objects.count()
    all_cashouts = CashOut.objects.all().order_by('datetime')
    paginator = Paginator(range(0, cashout_count), count_per_page)

    default_pagenum = paginator.num_pages
    try:
        pagenum = int(request.GET.get('page', default_pagenum))
    except:
        pagenum = default_pagenum

    try:
        page = paginator.page(pagenum)
    except (EmptyPage, InvalidPage):
        page = paginator.page(paginator.num_pages)

    # Slice
    page_cashouts = all_cashouts[page.object_list[0]:page.object_list[-1]+1]

    fields = CashCount.fields
    field_names = CashCount.field_names
    cashouts = []

    onhand_total = CashCount.totals_before(page_cashouts[0])
    for f in fields:
        if not onhand_total.has_key(f) or onhand_total[f] is None:
            onhand_total[f] = 0

    m = re.compile(r'^(?:bill|coin)')

    for c in page_cashouts:
        cashcount_list = [];

        for s in CashCount.objects.filter(cashout=c):
            cashcount = []
            for f in fields:
                try:
                    onhand_total[f] += s.__dict__[f]
                except TypeError:
                    pass # Probably 0 anyway.

                if m.search(f):
                    cashcount.append("%d" % (s.__dict__[f]))
                else:
                    cashcount.append("%.2f" % (s.__dict__[f]))

            cashcount_list.append({'count':cashcount, 
                                   'entity':s.entity})

        total = []
        for f in fields:
            total.append(onhand_total[f])

        cashouts.append({
                         'info': c,
                         'counts': cashcount_list,
                         'total':total,
                         })

    return render_to_response('cashout/cashonhand.html',
                              {'title': title,
                               'cashouts': cashouts,
                               'fields': fields,
                               'field_names': field_names,
                               'page': page
                               })

@edit_perm_required
def edit_cashout(request, cashout=None):
    load_from_database = True

    if cashout == None:
        cashout = CashOut(datetime=time.strftime(time_format,time.localtime()))
        load_from_database = False
    else:
        cashout = get_object_or_404(CashOut, id=int(cashout))

    counts = []

    commit = True

    fields = CashCount.fields
    field_values = CashCount.field_values
    field_names = CashCount.field_names

    if request.POST.has_key("_update"):
        commit = False

    try:
        cashout.notes = request.POST['notes']
        cashout.datetime = parse_datetime(request.POST['datetime'])

        n = 0
        while True:
            n = str(int(n) + 1)
            memo = request.POST['memo.' + n]
            entity = request.POST['entity.' + n]

            values = {}

            for f in fields[:-1]:
                try:
                    if f != 'other':
                        values[f] = int(request.POST[f + '.' + n])
                    else:
                        values[f] = Decimal(request.POST[f + '.' + n])
                except (ValueError, InvalidOperation): values[f] = 0

            total = 0

            for f in fields[:-1]:
                total += values[f] * field_values[f]

            if entity == "":
                entity = None
            else:
                entity = Entity.objects.get(id=int(entity))

            load_from_database = False

            if entity and total != 0:
                count_count = []

                count = {
                         'memo' : memo,
                         'entity' : entity,
                         'total' : total
                         }

                for f in fields[:-1]:
                    count[f] = values[f]
                    count_count.append(values[f])

                count_count.append(total)
                count['count_value'] = count_count

                counts.append(count)
    except KeyError:
        # Assume we hit the end of the inputs
        pass

    if len(counts) == 0:
        commit = False

    if load_from_database:
        for c in cashout.cashcount_set.all().order_by('entity'):
            count = {
                   'id':c.id,
                   'memo':c.memo,
                   'entity':c.entity
                   }
            count_count = []
            for f in fields:
                count[f] = c.__dict__[f]
                count_count.append(count[f])

            count['count_value'] = count_count
            counts.append(count)

            commit = False

    if commit:
        cashout.save()
        CashCount.objects.filter(cashout=cashout).delete()
        for c in counts:
            count = CashCount(
                              cashout=cashout,
                              entity=c['entity'],
                              memo=c['memo'],
                              bill100=c['bill100'],
                              bill50=c['bill50'],
                              bill20=c['bill20'],
                              bill10=c['bill10'],
                              bill5=c['bill5'],
                              bill1=c['bill1'],
                              coin100=c['coin100'],
                              coin50=c['coin50'],
                              coin25=c['coin25'],
                              coin10=c['coin10'],
                              coin5=c['coin5'],
                              coin1=c['coin1'],
                              other=c['other']
                              )
            count.save()

        return HttpResponseRedirect(reverse(ledger) + ('#c%d' % cashout.id))

    blank_values = []
    for f in fields:
        blank_values.append("")

    # Include blank entities?
    entitys = Entity.objects.order_by('name')
    if len(counts) == 0:
        for e in entitys:
            if not e in map(lambda s:s['entity'], counts):
                counts.append({'memo': "", 
                              'entity': e,
                              'count_value':blank_values})

    for i in range(1):
        counts.append({'memo': "", 'count_value':blank_values})

    return render_to_response('cashout/cashout_update.html',
                              {
                               'user': request.user,
                               'entitys': entitys,
                               'cashout': cashout,
                               'cashcounts': counts,
                               'fields' : CashCount.fields,
                               'field_names': CashCount.field_names,
                               'field_index' : range(0,
                                                     len(CashCount.fields[:-1]))
                              }
                              )

@edit_perm_required
def gen_transaction(request, cashout):
    cashout = get_object_or_404(CashOut, id=int(cashout))
   
    transaction = finance.Transaction(date=datetimetodate(
                                                str(cashout.datetime)
                                                         ), 
                                      auto_generated=False)


    splits = []

    account_name = {
            'cash' : 7,
            'collected' : 24,
            'bank' : 1,
            'inventory' : 5
            }

    balance = 0
    for c in cashout.cashcount_set.all().order_by('entity'):
        total = c.total
        balance += total
        split = {}

        if c.entity.name in ("Soda Machine", "Cash Box"):
            transaction.description = "Cash Collected"
            split['account'] = finance.Account.objects.get(
                                        id=int(account_name['cash'])
                                                          )

            split['memo'] = c.entity.name 

        elif c.entity.name in ("To Bank"):
            split['account'] = finance.Account.objects.get(
                                        id=int(account_name['bank'])
                                                          )
            split['memo'] = ""
            transaction.description = "Cash Deposit"

        elif c.entity.name in ("Payment"):
            transaction.description = cashout.notes
            split['account'] = finance.Account.objects.get(
                                        id=int(account_name['inventory'])
                                                          )
            split['memo'] = ""


        if total < 0: split['debit'] = -total
        if total > 0: split['credit'] = total

        splits.append(split)

    s = {
          'account':
                finance.Account.objects.get(id=int(account_name['collected'])),
           'amount':balance
        }
    if balance > 0: s['debit'] = balance
    if balance < 0: s['credit'] = -balance

    splits.append(s)
                

    return render_to_response('finance/transaction_update.html',
                              {
                          'user': request.user,
                          'accounts': finance.Account.objects.order_by('name'),
                          'transaction': transaction,
                          'splits': splits,
                          'action':'/admin/finance/transaction/new/'
                               })

@view_perm_required
def show_losses(request):
    title = 'Cash Losses'
    transcript = ""
    summary = []

    from django.db import connection
    cursor = connection.cursor()

    def add_amt(dict, key, value):
        # Add the given value into a dictionary, adding it to any existing
        # value.
        if key not in dict: dict[key] = Decimal("0.00")
        dict[key] += value

    def show_dict(dict):
        # Convert a dictionary to a format more suitable for display in a
        # Django template.
        val = [{'key': k, 'value': v} for (k, v) in sorted(dict.items())]
        val.append({'key': 'TOTAL',
                    'value': sum(dict.values(), Decimal("0.00"))})
        return val

    # FIXME: These ought to not be hard-coded
    acct_cash = finance.Account.objects.get(id=7)
    acct_adjustments = finance.Account.objects.get(id=23)
    cashout_entity_soda = Entity.objects.get(id=1)
    cashout_entity_box = Entity.objects.get(id=2)

    cursor.execute("""SELECT MIN(xacttime::date) FROM transactions""")
    (last_date,) = cursor.fetchone()

    cursor.execute("""SELECT sum(amount)
                      FROM finance_splits s JOIN finance_transactions t
                           ON (s.transaction_id = t.id)
                      WHERE account_id = %s AND date < %s""",
                   [acct_cash.id, last_date])
    (balance,) = cursor.fetchone()

    cash_deltas = {'soda': Decimal("0.00"), 'chezbob': Decimal("0.00")}

    transcript += "Starting cash: %s on %s\n\n" % (balance, last_date)

    source_totals = {}
    for cashout in CashOut.objects.filter(datetime__gte=last_date).order_by('datetime'):
        transcript += str(cashout) + "\n"
        cursor.execute("""SELECT source, sum(xactvalue)
                          FROM transactions
                          WHERE (xacttype = 'ADD' OR xacttype = 'REFUND')
                            AND xacttime >= %s AND xacttime < %s
                          GROUP BY source""",
                       [last_date, cashout.datetime])
        for (source, amt) in cursor.fetchall():
            transcript += "    Deposit: %s (%s)\n" % (amt, source)
            add_amt(source_totals, source, amt)
            balance += amt

        cursor.execute("""SELECT s.amount, t.description
                          FROM finance_splits s JOIN finance_transactions t
                               ON (s.transaction_id = t.id)
                          WHERE account_id = %s AND NOT auto_generated
                            AND date::timestamp >= %s
                            AND date::timestamp < %s
                          ORDER BY date, t.id""",
                       [acct_cash.id, last_date, cashout.datetime])
        other_transactions = []
        other_total = Decimal("0.00")
        for (a, d) in cursor.fetchall():
            other_transactions.append({'key': d, 'value': -a})
            other_total -= a
            balance += a
        other_transactions.append({'key': "TOTAL", 'value': other_total})

        cashcount = False
        collected = {}
        for c in cashout.cashcount_set.all():
            if c.entity in (cashout_entity_soda, cashout_entity_box) \
                and c.total > 0:
                add_amt(collected, c.entity.name, c.total)
                transcript += "  Cash Count: %s (%s)\n" % (c.total, c.entity.name)
                cashcount = True
                if c.entity == cashout_entity_soda:
                    cash_deltas['soda'] += c.total
                else:
                    cash_deltas['chezbob'] += c.total
        if cashcount:
            transcript += "  Expected:\n"
            for (s, t) in source_totals.items():
                transcript += "    %s %s\n" % (t, s)
                if s not in cash_deltas:
                    cash_deltas[s] = Decimal("0.00")
                cash_deltas[s] -= t

            transcript += "  Cumulative Errors:\n"
            for (s, t) in cash_deltas.items():
                transcript += "    %s %s\n" % (t, s)

            transcript += "  BALANCE: %s\n" % (balance,)
            summary.append({'date': cashout.datetime,
                            'deposits': show_dict(source_totals),
                            'collected': show_dict(collected),
                            'extra': other_transactions,
                            'error': balance})

            source_totals = {}

        last_date = cashout.datetime

    return render_to_response('cashout/losses.html',
                              {'summary': summary, 'debug': transcript})
