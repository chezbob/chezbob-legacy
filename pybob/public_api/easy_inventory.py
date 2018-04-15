"""TODO: Change me!"""
import sys

from flask import Blueprint, jsonify
from flask_cors import cross_origin

from private_api.bob_api import bobapi

from jinja2 import Environment, FileSystemLoader

from sh import zint
import base64

TEMPLATE_DIR = "/git/pybob/public_api/templates"
EASY_INVENTORY_TEMPLATE = "easy_inventory.html"


blueprint = Blueprint('easy_inventory', __name__)

api = bobapi.db

# What was the MOST RECENT inventory for each item?
LAST_INVENTORY_VIEW = """
create or replace temporary view last_inventory as
select date, bulkid, units from (
        SELECT
            date,
            bulkid,
            units,
            rank() over (partition by bulkid order by date desc) as r
        from inventory
        where bulkid in (select bulkid from bulk_items where active)
        ) s1
where r = 1
"""

# Represents how many of an item we've purchased since the last inventory of it
RECENT_ORDERS_VIEW = """
create or replace temporary view recent_orders as
select min(order_date) as since, bulkid, sum(units) as units
from (
    select
        o.date as order_date,
        li.date AS last_inventoried,
        quantity*number as units,
        bulk_type_id as bulkid
    from orders o
        inner join order_items oi
            on oi.order_id = o.id
        left outer join last_inventory li
        on bulk_type_id = bulkid
    ) s1
where (case
        when last_inventoried is null then true
        else order_date > last_inventoried end)
group by bulkid
"""

# Represents how many of an item we've sold since the most recent inventory
RECENT_SALES_VIEW = """
create or replace temporary view recent_sales as
select min(date) as since, max(date) as most_recent, bulkid, count(*) as units
from (
    select
        xacttime as date,
        li.date AS last_inventoried,
        p.bulkid
    from transactions t
        inner join products p
            on p.barcode = t.barcode
        left outer join last_inventory li
        on li.bulkid = p.bulkid
    ) s1
where ( case
    when last_inventoried is null then true
    else date > last_inventoried end)
group by bulkid
"""

CURRENT_INVENTORY_VIEW = """
create or replace temporary view current_inventory as
select
    i.date,
    (case when i.bulkid is null then s.bulkid else i.bulkid end) as bulkid,
    (case when i.units is null then 0 else i.units end)
        + (case when o.units is null then 0 else o.units end)
        - (case when s.units is null then 0 else s.units end)
        AS remaining,
    s.most_recent as most_recent_sale
    from last_inventory i
        full outer join recent_sales s on s.bulkid = i.bulkid
        left outer join recent_orders o on o.bulkid =
            (case when i.bulkid is null then s.bulkid else i.bulkid end)
    order by remaining asc
"""

LOW_QUERY = """
select ci.bulkid,
       remaining,
       round(remaining::numeric / quantity, 2) as cases_rem,
       date::date as inventoried,
       bulkbarcode,
       description
from current_inventory ci
    inner join bulk_items bi on bi.bulkid = ci.bulkid
where
    source != 4
    and active
    and (remaining < 10 or most_recent_sale < now() - interval '3 weeks')
    --and remaining <= quantity
    and (date is null or date <= now() - interval '3 weeks')
    and most_recent_sale is not null
order by floor_location, inventoried asc, remaining asc
limit 90
;
"""

QUERY = """
select ci.bulkid,
       remaining,
       round(remaining::numeric / quantity, 2) as cases_rem,
       date::date as inventoried,
       bulkbarcode,
       description
from current_inventory ci
    inner join bulk_items bi on bi.bulkid = ci.bulkid
where
    source != 4
    and active
    and remaining < 6
    and remaining <= quantity
    and (date is null or date <= now() - interval '2 weeks')
    and most_recent_sale > now() - interval '90 days'
order by remaining
limit 90
;
"""

PRODUCT_BCS = """
select barcode from products where bulkid = %s
"""


def log(*args):
    sys.stderr.write(" ".join([str(x) for x in args]))
    sys.stderr.write("\n")


def get_product_bc(bulkid):
    cursor = bobapi._get_cursor()
    cursor.execute(PRODUCT_BCS, [bulkid])

    if cursor.rowcount:
        return cursor.fetchone()['barcode']
    else:
        return None


def _get_barcode_img(barcode):
    subbar = (
        barcode[:-1] if (len(barcode) == 12 or len(barcode) == 13)
        else barcode)
    typ = 34 if len(barcode) == 12 else 37 if len(barcode) == 6 else 20
    try:
        img = (
            base64.b64encode(zint(
                "--directpng", "--height=25",
                "-b", typ, "-d", subbar).stdout).decode('utf-8'))
    except:
        img = ""
    return img


@blueprint.route('/all_low', methods=['GET'])
@cross_origin()
def _get_all_low_sheet():
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template(EASY_INVENTORY_TEMPLATE)

    cursor = bobapi._get_cursor()
    cursor.execute(LAST_INVENTORY_VIEW)
    cursor.execute(RECENT_ORDERS_VIEW)
    cursor.execute(RECENT_SALES_VIEW)
    cursor.execute(CURRENT_INVENTORY_VIEW)
    cursor.execute(LOW_QUERY)

    to_inventory = [dict(x) for x in cursor.fetchall()]
    for row in to_inventory:
        barcode = (
            row['bulkbarcode'] if row['bulkbarcode']
            else get_product_bc(row['bulkid']))
        if not barcode:
            log("Error in:", row)
            continue

        barcode_img = _get_barcode_img(barcode)

        row['barcode_img'] = barcode_img
        if row['inventoried']:
            row['inventoried'] = row['inventoried'].strftime("%y-%m-%d")

        row['description'] = row['description'][:row['description'].find(" (")]

    return template.render(to_inventory=to_inventory, title="Low Inventory")


@blueprint.route('/', methods=['GET'])
@cross_origin()
def _get_cheat_sheet():
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template(EASY_INVENTORY_TEMPLATE)

    cursor = bobapi._get_cursor()
    cursor.execute(LAST_INVENTORY_VIEW)
    cursor.execute(RECENT_ORDERS_VIEW)
    cursor.execute(RECENT_SALES_VIEW)
    cursor.execute(CURRENT_INVENTORY_VIEW)
    cursor.execute(QUERY)

    to_inventory = [dict(x) for x in cursor.fetchall()]
    for row in to_inventory:
        barcode = (
            row['bulkbarcode'] if row['bulkbarcode']
            else get_product_bc(row['bulkid']))
        if not barcode:
            log("Error in:", row)
            continue

        barcode_img = _get_barcode_img(barcode)

        row['barcode_img'] = barcode_img
        if row['inventoried']:
            row['inventoried'] = row['inventoried'].strftime("%y-%m-%d")

        row['description'] = row['description'][:row['description'].find(" (")]

    return template.render(to_inventory=to_inventory, title="Easy Inventory")


@blueprint.route('/json', methods=['GET'])
@cross_origin()
def _get_json():
    cursor = bobapi._get_cursor()
    cursor.execute(LAST_INVENTORY_VIEW)
    cursor.execute(RECENT_ORDERS_VIEW)
    cursor.execute(RECENT_SALES_VIEW)
    cursor.execute(CURRENT_INVENTORY_VIEW)
    cursor.execute(QUERY)

    to_inventory = [dict(x) for x in cursor.fetchall()]

    return jsonify({"to_inventory": to_inventory})

