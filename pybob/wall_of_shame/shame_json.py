#!/usr/bin/env python3
"""Super-fast hacky way to support an updateable shaming dashboard."""

import json
import os
import os.path
import psycopg2
import psycopg2.extras
import sys
import time

if __name__ == "__main__":
    BOB_PATH = os.environ.get('CHEZ_BOB_PATH', '/git')
    sys.path.insert(0, os.path.join(BOB_PATH, 'pybob'))

from private_api import db


OUTFILE = "/git/www/json/shame.json"
ANNOUNCE_PATH = "/git/www/json/shame_screen.json"

URL_TO_KIOSK = "https://chezbob.ucsd.edu/shame_kiosk.html"
DURATION_MULTIPLIER = 8
HOLD_TAGS = ["bobwall", "chezbob"]

DEBT_THRESHOLD = 15.0
DAYS_THRESHOLD = 28

HIGH_DEBT_QUERY = """
    SELECT
        username,
        nickname,
        balance,
        extract('days' from (now() - entered_wall)) as days_on_wall
    FROM users
    WHERE
        balance <= -{debt_threshold}
        AND (NOT disabled)
        AND (last_purchase_time > now() - INTERVAL '6 months')
    ORDER BY balance ASC
    LIMIT 20
"""

DELINQUENT_QUERY = """
    SELECT
        username,
        nickname,
        balance,
        extract('days' from (now() - entered_wall)) as days_on_wall
    FROM users
    WHERE
        (NOT disabled)
        AND entered_wall < now() - interval '{day_threshold} days'
        AND (last_purchase_time > now() - INTERVAL '12 months')
    ORDER BY balance ASC
    LIMIT 20
"""


def prepare_debtor_set(cursor, query, type_name, **formatting):
    cursor.execute(query.format(**formatting))
    debtors = []
    for i, row in enumerate(cursor):
        debtor = dict(row)
        debtor['balance'] = float(debtor['balance'])
        debtor['debt'] = "{:.2f}".format(-1 * debtor['balance'])
        debtor['index'] = i
        debtor['type'] = type_name
        debtors.append(debtor)
    return debtors


def generate_shame_json():
    conn = db.get_conn()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

    high_debt = prepare_debtor_set(
        cursor, HIGH_DEBT_QUERY, "high_value", debt_threshold=DEBT_THRESHOLD)
    delinquent = prepare_debtor_set(
        cursor, DELINQUENT_QUERY, "delinquent", day_threshold=DAYS_THRESHOLD)

    debtors = high_debt + delinquent

    debt_data = {
        "debtors": debtors,
        "debt_threshold": DEBT_THRESHOLD,
        "days_threshold": DAYS_THRESHOLD,
        "as_of": time.time(),  # Cache busting
    }
    announce_data = {
        "url": URL_TO_KIOSK,
        "duration": DURATION_MULTIPLIER * len(debtors),
        "hold_tags": HOLD_TAGS,
        "as_of": time.time(),  # Cache busting
    }

    with open(OUTFILE, 'w') as f:
        json.dump(debt_data, f)

    with open(ANNOUNCE_PATH, 'w') as f:
        if delinquent or high_debt:
            json.dump(announce_data, f)
        else:
            f.write('{}\n')

    # sys.stdout.write(json.dumps(debt_data))


def main():
    return generate_shame_json()


if __name__ == "__main__":
    sys.exit(main())
