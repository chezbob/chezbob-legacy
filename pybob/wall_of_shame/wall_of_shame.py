#!/usr/bin/env python3
"""Generates the wall of shame."""
import datetime
import os
import os.path
import sys
import tempfile

import arrow
from jinja2 import Environment, FileSystemLoader

if __name__ == "__main__":
    BOB_PATH = os.environ.get('CHEZ_BOB_PATH', '/git')
    sys.path.insert(0, os.path.join(BOB_PATH, 'pybob'))

from private_api import db

OUTFILE = "/git/www/wall_of_shame.html"

TEMPLATE_DIR = os.environ.get("CHEZBOB_WALL_TEMPLATE_DIR", "/git/templates")

WALL_TEMPLATE = "wall_of_shame.html"

MIN_SHAME_BALANCE = -5  # What the threshold is to be 'on the wall'

# Balance and day thresholds for warning and error states.
WARNING_BALANCE = -10.0
WARNING_DAYS = 14
ERROR_BALANCE = -15.0
ERROR_DAYS = 28

UNIMPORTANT_DAYS = 7
UNIMPORTANT_BALANCE = -7.5

DEBTOR_QUERY = """
    SELECT
        username, nickname, balance, userid, entered_wall
    FROM users
    WHERE
        balance <= {threshold}
        AND (NOT disabled)
    ORDER BY balance ASC
"""

TOTAL_BALANCE_QUERY = """
    SELECT
        sum(balance)
    FROM users
    WHERE
        balance < 0
        AND (NOT disabled)
"""


def get_days_since(dt):
    if dt is None:
        return -1
    dt = arrow.get() - arrow.get(dt)
    return dt.days


def get_seconds_since(dt):
    if dt is None:
        return -1
    dt = arrow.get() - arrow.get(dt)
    return dt.total_seconds()


def get_time_on_wall(cur, userid, balance):
    cur.execute(
        "SELECT xacttime, xactvalue FROM transactions WHERE userid = %s"
        "ORDER BY xacttime DESC",
        [userid])

    new_balance = balance
    for xacttime, xactvalue in cur:
        new_balance = new_balance - xactvalue
        if new_balance > MIN_SHAME_BALANCE:
            return xacttime

    return None


def print_wall_of_shame(f, users, total_owed, now):
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template(WALL_TEMPLATE)

    wall_debt = float(sum([x['balance'] for x in users]))
    debt_percentage = wall_debt / total_owed * -100.00

    f.write(template.render(
        users=users,
        total_percentage=debt_percentage, total_debt=total_owed,
        wall_debt=wall_debt,
        last_updated=now.strftime("%c"),
        WARNING_DAYS=WARNING_DAYS,
        WARNING_BALANCE=WARNING_BALANCE,
        MIN_SHAME_BALANCE=MIN_SHAME_BALANCE).encode('utf-8'))


def set_days_since(cursor, user):
    # We don't need to calculate it if we already have an answer
    if user['days_on_wall'] != -1:
        return user

    print("Had to manually calculate wall time for", user['username'])
    enter_time = get_time_on_wall(cursor, user['userid'], user['balance'])
    user['days_on_wall'] = get_days_since(enter_time)

    return user


def set_warnings(user):
    if ((user['balance'] <= ERROR_BALANCE) or
            (user['days_on_wall'] >= ERROR_DAYS)):
        user['error'] = True
    elif ((user['balance'] <= WARNING_BALANCE) or
            (user['days_on_wall'] >= WARNING_DAYS)):
        user['warning'] = True
    elif ((user['balance'] > UNIMPORTANT_BALANCE) and
            (user['days_on_wall'] < UNIMPORTANT_DAYS)):
        user['unimportant'] = True
    return user


def set_weight_days(user):
    mult = 1
    if 'error' in user and user['error']:
        mult = 1000000
    elif 'warning' in user and user['warning']:
        mult = 1000
    elif 'unimportant' in user and user['unimportant']:
        mult = .001

    return (-1 * mult *
            ((user['days_on_wall'] + 1) / WARNING_DAYS) *
            (float(user['balance']) / WARNING_BALANCE))


def set_weight_seconds(user):
    mult = 1
    if 'error' in user and user['error']:
        mult = 10000
    elif 'warning' in user and user['warning']:
        mult = 100
    elif 'unimportant' in user and user['unimportant']:
        mult = .01

    return (mult *
            (1000 + get_seconds_since(user['entered_wall'])) *
            float(user['balance']))


def set_weight(user):
    return set_weight_seconds(user)


def regenerate_wall_of_shame(outfile=OUTFILE):
    now = datetime.datetime.now()

    conn = db.get_conn()
    cursor = conn.cursor()
    cursor.execute(DEBTOR_QUERY.format(threshold=MIN_SHAME_BALANCE))

    results = [
        {
            "username": row[0],
            "nickname": row[1],
            "balance": row[2],
            "userid": row[3],
            "days_on_wall": get_days_since(row[4]),
            "entered_wall": row[4],
        } for row in cursor]

    # This should no longer be necessary, since everyone *should* have
    # days_on_wall already set.
    results = map(lambda x: set_days_since(cursor, x), results)

    results = map(lambda x: set_warnings(x), results)
    results = list(results)  # Listify the generator
    results.sort(key=set_weight)

    cursor.execute(TOTAL_BALANCE_QUERY)
    total_owed = -1 * float(cursor.fetchone()[0])

    # Doing this layer of indirection means that the transition is faster.
    # It reduces the race condition wherein we try to load the page while it's
    # only partially created.
    with tempfile.NamedTemporaryFile('wb', delete=False) as f:
        print_wall_of_shame(f, results, total_owed, now)
        tfile = f.name
    os.chmod(tfile, 0o644)
    os.rename(tfile, outfile)


def main():
    return regenerate_wall_of_shame()


if __name__ == "__main__":
    sys.exit(main())
