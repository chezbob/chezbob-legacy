"""Utility code for parsing Chez Bob transaction logs into finance records.

Parse the CSV-style files used for archival Chez Bob transaction records, and
compute daily aggregate purchase/deposit records for insertion into the Chez
Bob finance system.
"""

from __future__ import print_function

import datetime, time, re, sys

from chezbob.finance.models import Account, Split, Transaction

# Transaction log parsers
class GenericTransactionParser:
    """Class for parsing a CSV-style input file with a list of transactions.

    Different ChezBob data is logged in different formats; this class is
    intended to make it easier to combine the data from all these logs and
    abstract away some of the details of parsing the data."""

    def __init__(self, fp):
        """Create a new parser reading data from the given file object.

        The only required method of the file object is readline()."""

        self.fp = fp
        self.saved_lines = []

    def next_line(self):
        """Return the next line of the input file, or None at end."""

        if len(self.saved_lines) > 0:
            return self.saved_lines.pop()
        else:
            line = self.fp.readline()
            if line == "": line = None
            return line

    def push_line(self, line):
        """Undo a read of the input file.

        The next call to next_line will return the specified value instead of
        the actual next line."""

        self.saved_lines.append(line)

    def csv_escape(self, line):
        """Escape commas within quoted strings in a line from a CSV file."""

        in_quote = False
        result = ""
        for p in re.split('(")', line):
            if p == '"': in_quote = not in_quote
            if in_quote:
                p = re.sub(r',', r'\\054', p)
            result += p

        return result

    def preprocess_date(self, datestr):
        """Method used to preprocess a date before parsing.

        Defaults to no processing, but may be overridden."""

        return datestr

    def parse_line(self, line):
        """Parse a given line to a tuple (date, description, amt)."""

        def decode_item(i):
            i = i.strip()
            if len(i) > 0 and i[0] == '"':
                i = re.sub(r'"', "", i)
                i = re.sub(r"\\(\d{1,3})", lambda m: chr(int(m.group(1), 8)), i)
            return i

        row = [decode_item(i) for i in re.split(r", *", self.csv_escape(line))]

        ts = self.preprocess_date(row[self.date_column])
        ts = time.mktime(time.strptime(ts, self.date_fmt))
        date = datetime.date.fromtimestamp(ts)
        desc = row[self.desc_column]
        amt = float(row[self.amt_column])
        amt = int(round(amt * 100, 0))

        return (date, desc, amt)

    def next_row(self):
        """Return the next row of data, or None at end."""

        # Implemented by peeking at the next row to be returned, then throwing
        # away a line of input (that is, the line we just peeked at)
        row = self.peek_row()
        self.next_line()
        return row

    def peek_row(self):
        """Return the next row of data but do not remove from the input."""

        line = self.next_line()
        if line is None: return None

        # On error parsing this line, try to peek again; since we haven't
        # pushed the current line back onto the input queue yet, this
        # effectively discards the current (malformed) line and attempts to
        # parse the next one.
        try:
            row = self.parse_line(line)
        except ValueError:
            return self.peek_row()

        self.push_line(line)
        return row

class TransactionParser(GenericTransactionParser):
    """Specialized parser for ChezBob database dumps."""

    date_fmt = "%Y-%m-%d"
    date_column = 0
    desc_column = 2
    amt_column = 1
    user_column = None
    amt2_column = None

    def preprocess_date(self, datestr):
        return datestr.split()[0]

# Keep this synchronized with any changes to the account list in the database.
acct_deposits = Account.objects.get(id=2)
acct_cash = Account.objects.get(id=7)
acct_purchases = Account.objects.get(id=4)
acct_donations = Account.objects.get(id=12)
acct_writeoff = Account.objects.get(id=13)
acct_bank = Account.objects.get(id=1)
acct_social_restricted = Account.objects.get(id=21)
acct_social_donations = Account.objects.get(id=20)

def update_ledger(date, deposits, purchases, donations, writeoffs, social_hour):
    for t in list(Transaction.objects.filter(date=date, auto_generated=True)):
        t.split_set.all().delete()
        t.delete()

    if deposits:
        t = Transaction(date=date, description="Deposits", auto_generated=True)
        t.save()
        s = Split(transaction=t, account=acct_deposits, amount=-deposits)
        s.save()
        s = Split(transaction=t, account=acct_cash, amount=deposits)
        s.save()

    if purchases:
        t = Transaction(date=date, description="Purchases", auto_generated=True)
        t.save()
        s = Split(transaction=t, account=acct_purchases, amount=-purchases)
        s.save()
        s = Split(transaction=t, account=acct_deposits, amount=purchases)
        s.save()

    if donations:
        t = Transaction(date=date, description="Donations", auto_generated=True)
        t.save()
        s = Split(transaction=t, account=acct_donations, amount=-donations)
        s.save()
        s = Split(transaction=t, account=acct_deposits, amount=donations)
        s.save()

    if writeoffs:
        t = Transaction(date=date, description="Debt Written Off", auto_generated=True)
        t.save()
        s = Split(transaction=t, account=acct_writeoff, amount=writeoffs)
        s.save()
        s = Split(transaction=t, account=acct_deposits, amount=-writeoffs)
        s.save()

    if social_hour:
        t = Transaction(date=date, description="Social Hour Donations", auto_generated=True)
        t.save()
        s = Split(transaction=t, account=acct_social_donations,
                  amount=-social_hour)
        s.save()
        s = Split(transaction=t, account=acct_bank,
                  amount=-social_hour)
        s.save()
        s = Split(transaction=t, account=acct_deposits,
                  amount=social_hour)
        s.save()
        s = Split(transaction=t, account=acct_social_restricted,
                  amount=social_hour)
        s.save()

def process_log(fp):
    p = TransactionParser(fp)
    error_flag = False

    old_date = None
    while True:
        row = p.next_row()
        if row is not None:
            next_date = row[0]
        else:
            next_date = None

        if next_date != old_date:
            if old_date is not None:
                print(old_date, deposits, purchases,
                      donations, writeoffs, social_hour)
                update_ledger(old_date, deposits / 100.0, purchases / 100.0,
                              donations / 100.0, writeoffs / 100.0,
                              social_hour / 100.0)
            deposits = 0
            purchases = 0
            donations = 0
            writeoffs = 0
            social_hour = 0

        if next_date is None:
            break

        desc = row[1]
        amt = row[2]

        if desc in ("INIT", "TRANSFER") or amt == 0:
            pass
        elif amt < 0 and re.match(r"^(BUY|CANDY|JUICE|POPCORN|SNAPPLE)", desc):
            purchases -= amt
        elif desc == "ADD" and amt > 0:
            deposits += amt
        elif desc == "DONATION":
            donations -= amt
        elif desc == "WRITEOFF":
            writeoffs += amt
        elif desc == "SOCIAL HOUR":
            social_hour -= amt
        else:
            print("Unknown transaction entry:", row)
            error_flag = True

        old_date = next_date

    if error_flag:
        print("Unknown records encountered, results may be off!")
