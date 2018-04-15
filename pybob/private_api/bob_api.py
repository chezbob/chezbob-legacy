"""

This file contains various operations on the Chez Bob database.

It's awful, and bloated.

There's a bunch of stuff that shouldn't be in here.

You would be doing us a favor to migrate some of the more niche stuff OUT of
this file...

"""

import psycopg2
import psycopg2.extras

from private_api.db import get_conn


class InvalidOperationException(Exception):
    pass


class BobApi(object):
    def __init__(self, creds, connected=False):
        if type(creds) == psycopg2.extensions.connection:
            self.db = creds
        else:
            self.db = psycopg2.connect(**creds)
        self.db.set_client_encoding('utf8')

    def _get_cursor(self):
        return self.db.cursor(cursor_factory=psycopg2.extras.DictCursor)

    def is_valid_username(self, username):
        """Given a username, return whether or not it's valid. """
        return self.get_userid(username) is not None

    def get_balance(self, username):
        """Given a username, returns their balance, or None. """
        query = ("SELECT balance FROM users WHERE username = %s")
        cursor = self._get_cursor()
        cursor.execute(query, [username])

        if cursor.rowcount > 0:
            return cursor.fetchone()[0]
        return None

    def get_userid(self, username):
        """Given a username, return userid or None if invalid. """
        query = ("SELECT userid FROM users WHERE username = %s")
        cursor = self._get_cursor()
        cursor.execute(query, [username])

        if cursor.rowcount > 0:
            return cursor.fetchone()[0]
        return None

    def get_user_from_barcode(self, barcode):
        """Returns info about any user associated with that barcode."""

        query = (" SELECT"
                 "  u.userid, username, nickname, balance"
                 " from users u inner join userbarcodes b"
                 "  on b.userid = u.userid"
                 " where"
                 "  barcode = %s")

        return self._fetchone(query, [barcode])

    def make_deposit(self, username, amount, description, source=None):
        """Deposits the given amount into the username provided."""
        if amount < 0:
            raise InvalidOperationException("invalid amount for deposit")

        userid = self.get_userid(username)
        if not userid:
            raise InvalidOperationException("invalid username")

        if not source:
            source = 'webpayment'

        description = "ADD " + description

        query1 = ("UPDATE users SET balance = balance + %s WHERE userid = %s")
        query2 = ("INSERT INTO transactions"
                  " (xacttime, userid, xactvalue, xacttype, source)"
                  " VALUES"
                  " (now(), %s, %s, %s, %s)")
        cursor = self._get_cursor()
        cursor.execute(query1, [amount, userid])
        cursor.execute(query2, [userid, amount, description, source])
        self.db.commit()

    def get_day_stats(self):
        """Returns stats from the past day."""

        query = (" SELECT"
                 "  count(*) as n_transactions,"
                 "  sum(case when xactvalue < 0 then 1 else 0 end) as n_purchases,"
                 "  sum(case when xactvalue < 0 then xactvalue else 0 end) as purchased,"
                 "  sum(case when xactvalue > 0 then 1 else 0 end) as n_deposits,"
                 "  sum(case when xactvalue > 0 then xactvalue else 0 end) as deposits,"
                 "  sum(xactvalue) as net"
                 " from transactions"
                 " where"
                 "  xacttime >= now() - interval '24 hours'"
                 )

        cursor = self._get_cursor()
        cursor.execute(query)
        stats = cursor.fetchone()
        return stats

    def get_deposited_cash(self):
        """Returns the expected makeup of cash sitting in soda machine."""

        since = self._get_last_soda_empty()
        query = (" SELECT"
                 "  xactvalue::integer::text as value,"
                 "  count(*) as n,"
                 "  (count(*) * xactvalue) as total"
                 " from transactions"
                 " where"
                 "  xactvalue >= 1"
                 "  and xacttime > %s"
                 "  and source = 'bob2k14.2'"
                 "  and xacttype like 'ADD %% (cash)'"
                 " group by xactvalue"
                 " order by xactvalue")

        cursor = self._get_cursor()
        try:
            cursor.execute(query, [since])
        except:
            import traceback
            traceback.print_exc()

        rows = cursor.fetchall()
        return rows

    def _get_last_soda_empty(self):
        query = (
            " SELECT"
            "     max(xacttime) as last_emptied"
            " FROM transactions WHERE barcode = '482665976515'")
        return self._fetchone(query)['last_emptied']

    def get_sales_stats(
            self, bulkid=None, barcodes=None, window=14, agg='day'):
        """Returns daily sales numbers from past given days."""

        assert(bulkid or barcodes)

        assert(agg in {'day'})
        #{'hour', 'minute', 'month', 'day'})

        cursor = self._get_cursor()
        args = {}
        conditions = ["true"]

        query = (
            " SELECT"
            "      t_ago,"
            "      date_trunc('{group_type}',"
            "                  now()) - t_ago * interval '1 {group_type}'"
            "          as step,"
            "      count(distinct id) AS n_sold,"
            "      count(distinct userid) AS n_users"
            " FROM "
            " (select generate_series(0, %(window_size)s) as t_ago) s"
            " LEFT OUTER JOIN "
            " ("
            "      SELECT t.*, p.bulkid FROM "
            "          transactions t"
            "          INNER JOIN products p"
            "              ON t.barcode = p.barcode"
            "      WHERE"
            #"          xacttime > date_trunc("
            #"               '{group_type}',"
            #"               now()) - interval '%(window_size)s'"
            #"                   || ' {group_type}"
            " true"
            "          AND {transaction_join_condition}"
            "          AND {product_join_condition}"
            " ) x"
            " ON"
            "        date_part('{group_type}', "
            "                  date_trunc('{group_type}',"
            "                             now()) - date_trunc("
            "                                   '{group_type}',"
            "                                   xacttime))::integer = t_ago"
            " AND {conditions}"
            " GROUP BY t_ago"
            " ORDER BY t_ago ASC"
        )

        args['window_size'] = window

        product_join_condition = 'true'
        transaction_join_condition = 'true'
        if bulkid:
            #conditions.append("bulkid = %(bulkid)s")
            product_join_condition = "bulkid = %(bulkid)s"
            args['bulkid'] = bulkid
        elif barcodes:
            transaction_join_condition = "t.barcode in %(barcodes)s"
            args['barcodes'] = tuple(barcodes)

        query = query.format(
            conditions=" AND ".join(conditions),
            product_join_condition=product_join_condition,
            transaction_join_condition=transaction_join_condition,
            group_type=agg,
        )

        cursor.execute(query, args)
        self.db.commit()
        return cursor

    def get_daily_aggregate_stats(self):
        """Returns daily sales numbers from past given days."""
        cursor = self._get_cursor()
        query = """
        select
            xacttime::date as date,
            -1*sum(xactvalue) as revenue,
            count(distinct userid) as n_users,
            count(*) as n_transactions
        from transactions
        where
            xactvalue < 0
            and xacttime > current_date - interval '1 month'
        group by xacttime::date
        order by xacttime::date
        """

        cursor.execute(query)
        self.db.commit()
        return cursor

    def get_month_transactions(self):
        query = """
        SELECT t.barcode, t.userid, t.xacttime, t.xactvalue, p.bulkid
        FROM transactions t LEFT OUTER JOIN products p ON p.barcode = t.barcode
        WHERE xacttime > now() - interval '31 days'
        ORDER BY xacttime ASC
        """

        return self._fetchall(query)

    def get_day_average_data(self):
        query = """
select
    s.hour,
    case
        when a.avg_sales is not null
            then a.avg_sales
        else 0
            end as avg_sales,
    case
        when t.sales is not null then t.sales
        when s.hour > extract(hour from now()) then null
        else 0
            end as today_sales,
    case
        when a.avg_deposits is not null
            then a.avg_deposits
        else 0
            end as avg_deposits,
    case
        when t.deposits is not null then t.deposits
        when s.hour > extract(hour from now()) then null
        else 0
            end as today_deposits

from (
        select generate_series(0, 23) as hour) s
    left outer join (
        select
            extract(hour from xacttime) as hour,
            -1 * sum(case when xactvalue < 0 then xactvalue else 0 end) /
                count(distinct date_trunc('day', xacttime))
                as avg_sales,
            sum(case when xactvalue > 0 then xactvalue else 0 end) /
                count(distinct date_trunc('day', xacttime))
                as avg_deposits
        from transactions
        where
            xacttime > current_date - interval '365 days'
            and extract(dow from current_date) = extract(dow from xacttime)
            and xacttime < current_date
        group by hour
        ) a
    on s.hour = a.hour
    left outer join (
        select
            extract(hour from xacttime) as hour,
            -1 * sum(case when xactvalue < 0 then xactvalue else 0 end)
                as sales,
            sum(case when xactvalue > 0 then xactvalue else 0 end) as deposits
        from transactions
        where
            xacttime > current_date
        group by hour
        ) t
    on t.hour = s.hour
order by hour
"""

        return self._fetchall(query)

    def get_day_transactions(self):
        query = """
        SELECT *
        FROM transactions
        WHERE xacttime > current_date - interval '3 days'
        ORDER BY xacttime ASC
        """

        return self._fetchall(query)

    def get_bulkitem_from_barcode(self, bc):
        query = """
        SELECT *, 'bulkitem' as \"type\" FROM bulk_items WHERE bulkbarcode = %s
        """
        return self._fetchone(query, [bc])

    def get_bulkitem_from_bulkid(self, bid):
        query = """
        SELECT *, 'bulkitem' as \"type\" FROM bulk_items WHERE bulkid = %s
        """
        return self._fetchone(query, [bid])

    def get_product_from_barcode(self, bc):
        query = """
        SELECT *, 'product' as \"type\" FROM products WHERE barcode = %s
        """
        return self._fetchone(query, [bc])

    def get_bulkitems(self, active=None, bulkid=None):
        """Returns details of all bulk items."""

        query = (" SELECT"
                 "  *"
                 " FROM bulk_items"
                 " WHERE {conditions}")

        cursor = self._get_cursor()
        conditions = ["true"]
        args = {}
        if active is not None:
            conditions.append("active = %(active)s")
            args['active'] = active
        if bulkid:
            conditions.append("bulkid = %(bulkid)s")
            args['bulkid'] = bulkid

        query = query.format(conditions=" AND ".join(conditions))

        cursor.execute(query, args)
        self.db.commit()
        return cursor

    def get_inventory_steps(self, bulkids, window):
        """Returns an array of actions on a product to graph inventory over
        time."""

        query = """
SELECT * FROM (
    SELECT xacttime AS date,
           bulkid,
           'sale' AS type,
           -1 AS n
    FROM transactions t INNER JOIN products p
        ON p.barcode = t.barcode
    WHERE xacttime > current_date - interval %s and bulkid is not null

    UNION ALL

    SELECT  date,
            bulk_type_id AS bulkid,
            'order' AS type,
            quantity*number AS n
    FROM order_items oi INNER JOIN orders o
        ON o.id = oi.order_id
    WHERE date > current_date - interval %s and bulk_type_id is not null

    UNION ALL

    SELECT  date,
            bulkid,
            'inventory' AS type,
            units AS n
    FROM inventory i
    WHERE
        date > current_date - interval %s
        and bulkid is not null
        and units is not null
) s
WHERE bulkid IN %s
ORDER BY date ASC
"""
        cursor = self._get_cursor()
        cursor.execute(query, [window, window, window, tuple(bulkids)])
        stats = cursor.fetchall()
        self.db.commit()
        return stats

    def get_wall_of_shame(self):
        QUERY = """
SELECT
    username,
    nickname,
    balance,
    extract('days' from (now() - entered_wall)) as days_on_wall
FROM users
WHERE
    (NOT disabled)
    AND (last_purchase_time > now() - INTERVAL '6 months')
    AND ((balance <= -5) OR (entered_wall < now() - interval '28 days'))
ORDER BY balance ASC
"""
        cursor = self._get_cursor()
        cursor.execute(QUERY, [])
        wall = cursor.fetchall()
        self.db.commit()
        return wall

    def cold_brew_sold_since_last_refresh(self):
        """Returns number of coldbrew cups sold since last restock."""

        query = ("select count(*) from transactions"
                 " where barcode = '488348702402'"
                 " and xacttime >"
                 "  (select xacttime from transactions t"
                 "   where barcode in (select barcode from coldbrew_varieties)"
                 "   order by xacttime desc limit 1)")

        cursor = self._get_cursor()
        cursor.execute(query)
        self.db.commit()
        return cursor

    def _fetchall(self, query, *args, **kwargs):
        cursor = self._get_cursor()
        try:
            cursor.execute(query, *args, **kwargs)
        except:
            import traceback
            traceback.print_exc()

        if cursor.rowcount:
            rows = cursor.fetchall()
        else:
            rows = []
        self.db.commit()
        return rows

    def _fetchone(self, query, *args, **kwargs):
        cursor = self._get_cursor()
        try:
            cursor.execute(query, *args, **kwargs)
        except:
            import traceback
            traceback.print_exc()

        if cursor.rowcount:
            row = cursor.fetchone()
        else:
            row = None
        self.db.commit()
        return row


bobapi = BobApi(get_conn())
