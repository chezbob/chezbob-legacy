from decimal import Decimal
from django.db import models

# The core of the double-entry bookkeeping system is in the three tables
# Account, Transaction, and Split.  A transaction consists of a set of splits,
# each of which represents money flowing into or out of a single account.  A
# transaction must be balanced--the sum of the values of all the splits in a
# transaction must be zero.  This constraint is not currently enforced by the
# database, and so must be maintained by any code editing the database.


class Account(models.Model):
    class Meta:
        db_table = 'finance_accounts'

    ASSET = 'A'
    EQUITY = 'Q'
    EXPENSE = 'E'
    INCOME = 'I'
    LIABILITY = 'L'

    TYPES = {
        ASSET: "Asset",
        EQUITY: "Equity",
        EXPENSE: "Expense",
        INCOME: "Income",
        LIABILITY: "Liability",
    }

    type = models.CharField(max_length=1, choices=list(TYPES.items()))
    name = models.CharField(max_length=256)

    def __str__(self):
        return "%s [%s]" % (self.name, self.TYPES[self.type])

    def is_reversed(self):
        return self.type in ('Q', 'I', 'L')

    @classmethod
    def get_balances(cls, date=None):
        """Return a list of all accounts, and their current balances."""

        from django.db import connection
        cursor = connection.cursor()

        balances = {}
        if date is None:
            cursor.execute("""SELECT account_id, sum(amount)
                              FROM finance_splits GROUP BY account_id""")
        else:
            cursor.execute("""SELECT account_id, sum(amount)
                              FROM finance_splits
                              WHERE transaction_id in
                                  (SELECT id FROM finance_transactions
                                   WHERE date <= %s)
                              GROUP BY account_id""", (date,))
        for (id, balance) in cursor.fetchall():
            balances[id] = balance

        result = []
        for a in Account.objects.order_by('name'):
            result.append((a, balances.get(a.id, Decimal("0.00"))))

        return result


class Transaction(models.Model):
    class Meta:
        db_table = 'finance_transactions'
        permissions = [("view_transactions", "View Chez Bob Ledger"),
                       ("edit_transactions", "Update Chez Bob Ledger")]

    date = models.DateField()
    description = models.TextField()

    # The auto_generated field is used to mark transactions that have been
    # created automatically by copying data from the Chez Bob transactions
    # table.  These transactions may be inserted, deleted, or updated by
    # scripts without warning the user.  A transaction with auto_generated set
    # to false will never be touched by the automated systems.
    auto_generated = models.BooleanField()

    def __str__(self):
        return "%s %s" % (self.date, self.description)

    @classmethod
    def fetch_all(cls, account=None, include_auto=True, end_date=None):
        """Return a list of all transactions and splits in the database.

        The result is a sequence of tuples: (transaction, [split list]).
        Transactions are sorted by date.
        """

        from django.db import connection
        cursor = connection.cursor()

        accounts = {}
        for a in Account.objects.all():
            accounts[a.id] = a

        result = []
        extra_conditions = ""
        extra_arguments = []

        if not include_auto:
            extra_conditions += "AND NOT finance_transactions.auto_generated "
        if account is not None:
            extra_conditions += (
                "AND finance_transactions.id IN (SELECT transaction_id FROM"
                " finance_splits WHERE account_id = %s) ")
            extra_arguments.append(account.id)
        if end_date is not None:
            extra_conditions += "AND finance_transactions.date <= %s "
            extra_arguments.append(end_date)
        query = """SELECT finance_transactions.id,
                          finance_transactions.date,
                          finance_transactions.description,
                          finance_transactions.auto_generated,
                          finance_splits.id,
                          finance_splits.account_id,
                          finance_splits.amount,
                          finance_splits.memo
                   FROM finance_transactions, finance_splits
                   WHERE
                        finance_splits.transaction_id = finance_transactions.id
                         %s
                   ORDER BY finance_transactions.date,
                            finance_transactions.id""" % (extra_conditions,)
        cursor.execute(query, extra_arguments)

        transaction = None
        for (id, date, desc, auto, split_id, acct, amt, memo
             ) in cursor.fetchall():
            if transaction is None or transaction[0].id != id:
                if transaction is not None:
                    result.append(transaction)
                transaction = (Transaction(id=id, date=date, description=desc,
                                           auto_generated=auto),
                               [])
            transaction[1].append(Split(id=split_id,
                                        transaction=transaction[0],
                                        account=accounts[acct],
                                        amount=amt, memo=memo))

            # FIXME: This is to prevent a lookup of split.account for having to
            # go back to the database later, which is expensive.  But it messes
            # with Django internals.  There must be a cleaner way to accomplish
            # this.
            transaction[1][-1]._account_cache = accounts[acct]

        if transaction is not None:
            result.append(transaction)

        for (t, splits) in result:
            splits.sort(key=lambda s: -s.amount)
        return result

    @classmethod
    def balance_before(cls, trans, account):
        balance = Decimal("0.00")

        objects = val = Split.objects.filter(account=account).exclude(
            transaction__date__gt=trans.date).exclude(
                transaction__date__exact=trans.date,
                transaction__pk__gte=trans.pk)

        val = objects.aggregate(amount_total=models.Sum('amount'))
        if val['amount_total'] is not None:
            balance = val['amount_total']

        if account.is_reversed():
            return -balance
        else:
            return balance


class Split(models.Model):
    class Meta:
        db_table = 'finance_splits'

    transaction = models.ForeignKey(Transaction)
    account = models.ForeignKey(Account)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    memo = models.CharField(max_length=256, blank=True)

    def __str__(self):
        return "%.2f %s" % (self.amount, self.account)


# The "Bank of Bob Liabilities" account does not separate out positive-balance
# accounts from negative- ones, and merely records the total.  But this
# information is still useful to have.  We use an auxiliary table to store the
# separated values for each date.  The sum (positive - negative) should be
# equal to the true Bank of Bob account balance at each date, but this
# constraint is not currently enforced by the database.
class DepositBalances(models.Model):
    class Meta:
        db_table = 'finance_deposit_summary'

    date = models.DateField(primary_key=True)
    positive = models.DecimalField(max_digits=12, decimal_places=2)
    negative = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return "%s +%.2f -%.2f" % (self.date, self.positive, self.negative)


# Estimated value of Chez Bob inventory is not tracked as a core part of the
# finance system.  We can compute it (approximately) from inventory data and
# sales, but this is expensive.  Allow these inventory value calculations to be
# cached, so that they can be reported in some of the financial reports.
# Warning: Inventory values are just estimates, and are not as precise as most
# values in the finance system--they might vary based on adjustments to
# algorithms, starting point for measurements, etc.
class InventorySummary(models.Model):
    class Meta:
        db_table = 'finance_inventory_summary'

    date = models.DateField(primary_key=True)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    shrinkage = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return "%s value=%.2f shrinkage=%.2f" % (
            self.date, self.value, self.shrinkage)
