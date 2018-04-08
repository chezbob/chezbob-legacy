import datetime
import re
from decimal import Decimal
from time import strptime

from django.shortcuts import render_to_response, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse, HttpResponseRedirect
from chezbob.finance.models import Account, Transaction, Split
from chezbob.finance.models import DepositBalances, InventorySummary
from django.core.paginator import Paginator, InvalidPage, EmptyPage
from django.core.urlresolvers import reverse

view_perm_required = \
    user_passes_test(lambda u: u.has_perm('finance.view_transactions'))
edit_perm_required = \
    user_passes_test(lambda u: u.has_perm('finance.edit_transactions'))


def parse_date(datestr):
    """Parse a string representation of a date into a datetime.Date object.

    At the moment this only supports ISO-style dates (2007-01-31).  In the
    future it might be extended to other formats, and auto-detect.
    """

    return datetime.date(*strptime(datestr, "%Y-%m-%d")[0:3])


XML_ESCAPES = {'"': "quot", "'": "apos", '<': "lt", '>': "gt", "&": "amp"}


def xml_escape(s):
    """Escape a string so it can be written to an XML document."""

    def e(c):
        c = c.group()
        return "&" + XML_ESCAPES.get(c, "#%d" % (ord(c),)) + ";"
    return re.sub("['\"<>&]", e, s)


@view_perm_required
def account_list(request):
    accounts = {}
    for t in Account.TYPES:
        accounts[t] = []
    totals = {}

    try:
        date = parse_date(request.GET['date'])
    except:  # noqa
        date = None

    try:
        since = parse_date(request.GET['since'])
        start_balances = {}
        for (a, b) in Account.get_balances(date=since):
            start_balances[a.id] = b
    except:  # noqa
        start_balances = None

    for (a, b) in Account.get_balances(date=date):
        if start_balances is not None:
            b -= start_balances[a.id]
        if a.is_reversed():
            b = -b
        a.balance = b
        accounts[a.type].append(a)
        totals[a.type] = totals.get(a.type, Decimal("0.00")) + b

    account_groups = []
    for t in ('A', 'L', 'I', 'E', 'Q'):
        account_groups.append({'group': Account.TYPES[t],
                               'accounts': accounts[t],
                               'total': totals[t]})
    return render_to_response('finance/accounts.html',
                              {'account_groups': account_groups,
                               'date': date})


@view_perm_required
def redirect(request):
    return HttpResponseRedirect(reverse(account_list))


@view_perm_required
def ledger(request, account=None):
    if account:
        account = Account.objects.get(id=account)
        title = account.name
    else:
        title = "General Ledger"

    transactions = []

    transaction_filter = {}

    # default include_auto, not for general ledger
    include_auto = True
    if account is None:
        include_auto = False

    # parameter override
    if 'all' in request.GET:
        if request.GET['all'] != '0':
            include_auto = True
        else:
            include_auto = False

    if not include_auto:
        transaction_filter['auto_generated'] = False

    if account is not None:
        transaction_filter['split__account'] = account

    count_per_page = 25
    all_transactions = Transaction.objects.filter(**transaction_filter)\
                                          .order_by('date', 'id')\
                                          .distinct()

    transaction_count = all_transactions.count()
    paginator = Paginator(list(range(0, transaction_count)), count_per_page)

    default_pagenum = paginator.num_pages
    try:
        pagenum = int(request.GET.get('page', default_pagenum))
    except:  # noqa
        pagenum = default_pagenum

    try:
        page = paginator.page(pagenum)
    except (EmptyPage, InvalidPage):
        page = paginator.page(paginator.num_pages)

    # Slice
    if len(page.object_list) > 2:
        page_transactions = (
            all_transactions[page.object_list[0]:page.object_list[-1] + 1])
    else:
        page_transactions = all_transactions

    if account is not None and len(page_transactions) > 0:
        balance = Transaction.balance_before(page_transactions[0],
                                             account)
    else:
        balance = Decimal("0.00")

    for t in page_transactions:
        split_list = []
        for s in Split.objects.filter(transaction=t):
            split = {'memo': s.memo,
                     'account': s.account,
                     'debit': "",
                     'credit': ""}
            if s.amount >= 0:
                split['debit'] = s.amount
            else:
                split['credit'] = -s.amount
            split_list.append(split)
            if account is not None and s.account.id == account.id:
                balance += s.amount
        if account is None:
            transactions.append({'info': t, 'splits': split_list})
        else:
            transactions.append({'info': t, 'splits': split_list,
                                 'balance': balance})

    if account:
        for t in transactions:
            if account.is_reversed():
                t['balance'] *= -1

    if include_auto:
        extra_page_params = "all=1&"
    else:
        extra_page_params = ""

    return render_to_response('finance/transactions.html',
                              {'title': title,
                               'transactions': transactions,
                               'balances': account is not None,
                               'page': page,
                               'extra_page_params': extra_page_params})


@edit_perm_required
def edit_transaction(request, transaction=None):
    load_from_database = True

    if transaction is None:
        transaction = Transaction(date=datetime.date.today(),
                                  auto_generated=False)
        load_from_database = False
    else:
        transaction = get_object_or_404(Transaction, id=int(transaction))
    splits = []

    commit = True               # Is it safe to commit this transaction?

    # If the user clicked the "Update" button, don't commit yet.
    if "_update" in request.POST:
        commit = False

    # If POST data was submitted, we're in the middle of editing a transaction.
    # Pull the transaction data out of the POST data.  Otherwise, we need to
    # load the initial data from the database.
    try:
        transaction.date = parse_date(request.POST['date'])
        transaction.description = request.POST['desc']
        transaction.auto_generated = "auto_generated" in request.POST

        n = 0
        while True:
            n = str(int(n) + 1)
            note = request.POST['note.' + n]
            account = request.POST['account.' + n]
            if account == "":
                account = None
            else:
                account = Account.objects.get(id=int(account))

            amount = Decimal("0.00")
            if request.POST['debit.' + n] != "":
                amount += Decimal(request.POST['debit.' + n])
            if request.POST['credit.' + n] != "":
                amount -= Decimal(request.POST['credit.' + n])

            load_from_database = False

            if account:
                splits.append({'memo': note,
                               'account': account,
                               'amount': amount})
    except KeyError:
        # Assume we hit the end of the inputs
        pass

    if len(splits) == 0:
        commit = False

    # Load initial splits from the database, if needed
    if load_from_database:
        for s in transaction.split_set.all().order_by('-amount'):
            splits.append({'id': s.id,
                           'memo': s.memo,
                           'account': s.account,
                           'amount': s.amount})
        commit = False

    # Check if the transaction is balanced.  If not, add a balancing split to
    # be filled in by the user.
    total = Decimal("0.00")
    for s in splits:
        total += s['amount']
    if total != Decimal("0.00"):
        splits.append({'memo': "", 'account': None, 'amount': -total})
        commit = False

    # Has the transaction been fully filled-in, with no problems found?  If so,
    # commit to the database.
    if commit:
        transaction.save()
        Split.objects.filter(transaction=transaction).delete()
        for s in splits:
            split = Split(transaction=transaction,
                          account=s['account'],
                          memo=s['memo'],
                          amount=s['amount'])
            split.save()
        if transaction.auto_generated:
            url = "%s?all#t%d" % (reverse(ledger), transaction.id,)
        else:
            url = "%s#t%d" % (reverse(ledger), transaction.id,)
        return HttpResponseRedirect(url)

    # Include a few blank splits at the end of the transaction for entering
    # additional data.
    for i in range(4):
        splits.append({'memo': "", 'account': None, 'amount': Decimal("0.00")})

    # Convert splits to a separated debit/credit format
    for s in splits:
        s['debit'] = Decimal("0.00")
        s['credit'] = Decimal("0.00")
        if s['amount'] > 0:
            s['debit'] = s['amount']
        if s['amount'] < 0:
            s['credit'] = -s['amount']

    return render_to_response('finance/transaction_update.html',
                              {'user': request.user,
                               'accounts': Account.objects.order_by('name'),
                               'transaction': transaction,
                               'splits': splits})


def gen_gnuplot_dump():
    columns = {}

    yield "# Chez Bob Account Balances Dump\n#\n"
    yield "# 1: Date\n"
    i = 0
    yield "#\n# Accounts:\n"
    for a in Account.objects.order_by('name'):
        yield "# %d: %s\n" % (i + 2, a)
        columns[a.id] = i
        i += 1
    yield "#\n# Additional Data:\n"
    for t in sorted(Account.TYPES.keys()):
        yield "# %d: %s Total\n" % (i + 2, Account.TYPES[t])
        i += 1
    yield "# %d: %s\n" % (i + 2, "Bank of Bob Accounts: Positive")
    yield "# %d: %s\n" % (i + 3, "Bank of Bob Accounts: Negative")
    yield "# %d: %s\n" % (i + 4, "Inventory: Value at Cost")
    yield "# %d: %s\n" % (i + 5, "Inventory: Shrinkage")
    yield "# %d: %s\n" % (i + 6, "Inventory: Cumulative Shrinkage")

    balances = [Decimal("0.00")] * len(columns)
    date = None
    multiplier = [1] * len(columns)

    totals = {}
    for t in Account.TYPES:
        totals[t] = Decimal("0.00")
    totals['shrinkage'] = Decimal("0.00")

    for (id, i) in columns.items():
        if Account.objects.get(id=id).is_reversed():
            multiplier[i] = -1

    def dump_row():
        line = str(date) + "\t"

        # Accounts
        for i in range(len(balances)):
            balances[i] = balances[i]
        line += "\t".join(["%.2f" % (b,) for b in balances])

        # Totals
        for t in sorted(Account.TYPES.keys()):
            line += "\t%.2f" % (totals[t],)

        # Positive/negative BoB balances
        try:
            d = DepositBalances.objects.get(date=date)
            line += "\t%.2f\t%.2f" % (d.positive, d.negative)
        except DepositBalances.DoesNotExist:
            pass

        # Inventory value and shrinkage
        try:
            d = InventorySummary.objects.get(date=date)
            totals['shrinkage'] += d.shrinkage
            line += "\t%.2f\t%.2f\t%.2f" \
                    % (d.value, d.shrinkage, totals['shrinkage'])
        except InventorySummary.DoesNotExist:
            pass

        return line + "\n"

    for t in Transaction.objects.order_by('date'):
        if t.date != date:
            if date is not None:
                yield dump_row()
            date = t.date
        for s in t.split_set.all():
            i = columns[s.account.id]
            balances[i] += s.amount * multiplier[i]
            totals[s.account.type] += s.amount * multiplier[i]
    yield dump_row()


@view_perm_required
def gnuplot_dump(request):
    response = HttpResponse(mimetype="text/plain")

    for line in gen_gnuplot_dump():
        response.write(line)

    return response


@view_perm_required
def transaction_dump(request):
    response = HttpResponse(mimetype="text/plain")

    response.write('<?xml version="1.0" encoding="utf-8"?>\n')
    response.write('<?xml-stylesheet type="text/xsl" href="finance.xsl"?>\n\n')

    response.write('<finances>\n  <accounts>\n')
    TYPE_MAP = {'A': 'asset', 'L': 'liability', 'I': 'income', 'E': 'expense',
                'Q': 'equity'}
    for a in Account.objects.order_by('name'):
        response.write('    <account id="acct%d" type="%s">%s</account>\n'
                       % (a.id, TYPE_MAP[a.type], xml_escape(a.name)))

    response.write('  </accounts>\n\n  <transactions>')

    for (t, splits) in Transaction.fetch_all(include_auto=True):
        auto = ''
        if t.auto_generated:
            auto = ' auto="true"'
        response.write(
            '\n    <transaction id="t%d"%s>\n      <date>%s</date>\n'
            % (t.id, auto, t.date))
        response.write('      <description>%s</description>\n      <splits>\n'
                       % (xml_escape(t.description),))
        for s in splits:
            response.write(
                '        <split account="acct%d" value="%.02f">%s</split>\n'
                % (s.account.id, s.amount, xml_escape(s.memo)))
        response.write('      </splits>\n    </transaction>\n')

    response.write('  </transactions>\n</finances>\n')

    return response
