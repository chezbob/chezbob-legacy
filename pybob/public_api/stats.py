"""The stats needed for the shiny dashboard.

"""

import hashlib
import random
import string

from flask import Blueprint, jsonify
from flask_cors import cross_origin

from private_api.bob_api import bobapi


blueprint = Blueprint('dashboard', __name__)


def fix_decimals(x):
    return x


def anonymize(inp):
    h = hashlib.md5()
    h.update(inp.encode('ascii', 'ignore'))
    return h.hexdigest()


@blueprint.route('/v0.1/get_day_stats', methods=['GET'])
@cross_origin()
def get_day_stats():
    return generic_wrapper(bobapi.get_day_stats, nolist=True)


@blueprint.route('/v0.1/get_hourly_stats', methods=['GET'])
@cross_origin()
def get_hourly_stats():
    return generic_wrapper(bobapi.get_day_average_data)


@blueprint.route('/v0.1/bulkitem/getall', methods=['GET'])
@cross_origin()
def get_bulkitems():
    return generic_wrapper(bobapi.get_bulkitems)


@blueprint.route('/v0.1/bulkitem/get_details/<int:bulkid>',
                 methods=['GET'])
@cross_origin()
def get_bulkitem(bulkid):
    return generic_wrapper(bobapi.get_bulkitems, singleton=True, bulkid=bulkid)


@blueprint.route(
    '/v0.1/sales/get_inventory_steps/<int:bulkid>/<int:window>',
    methods=['GET'])
@cross_origin()
def get_inventory_steps(bulkid, window):
    def fix(x):
        # This stupid thing is because the json conversion of date types isn't
        # the same as the string conversion... which means the timezones get
        # fucked up.
        x['date'] = str(x['date'])
        return x

    if window < 0 or window > 90:
        return jsonify({"error": "Window is of invalid size."})
    return generic_wrapper(
        bobapi.get_inventory_steps, repair_func=fix,
        bulkids=[bulkid], window='{} days'.format(window))


@blueprint.route('/v0.1/sales/get_stats/<int:bulkid>/<int:window>',
                 methods=['GET'])
@cross_origin()
def get_sales_stats(bulkid, window):
    def fix(x):
        # This stupid thing is because the json conversion of date types isn't
        # the same as the string conversion... which means the timezones get
        # fucked up.
        x['step'] = str(x['step'])
        return x

    if window < 0 or window > 365:
        return jsonify({"error": "Window is of invalid size."})
    return generic_wrapper(
        bobapi.get_sales_stats, repair_func=fix,
        bulkid=bulkid, window=window, agg='day')


@blueprint.route('/v0.1/sales/get_aggregate_sales', methods=['GET'])
@cross_origin()
def get_aggregate_sales():
    def fix(x):
        x['date'] = str(x['date'])
        x['revenue'] = float(x['revenue'])
        return x

    return generic_wrapper(bobapi.get_daily_aggregate_stats, repair_func=fix)


@blueprint.route('/v0.1/sales/get_day_sales', methods=['GET'])
@cross_origin()
def get_day_sales():
    rand = "".join([random.choice(string.printable) for x in range(32)])

    def strip(x):
        # Strip out anything sensitive
        x = fix_decimals(x)
        result = {
            'xacttime': str(x['xacttime']),
            'xactvalue': x['xactvalue'],
            'userid': anonymize(str(x['userid']) + rand)[:5],
            'source': x['source'],
        }

        return result

    return generic_wrapper(bobapi.get_day_transactions, repair_func=strip)


@blueprint.route('/v0.1/sales/get_month_transactions', methods=['GET'])
@cross_origin()
def get_month_transactions():
    rand = "".join([random.choice(string.printable) for x in range(32)])

    def strip(x):
        # Strip out anything sensitive
        x = fix_decimals(x)
        result = {
            'barcode': x['barcode'],
            'bulkid': x['bulkid'],
            'xacttime_s': str(x['xacttime']),
            'xacttime_e': int(x['xacttime'].strftime('%s')),
            'xactvalue': x['xactvalue'],
            'userid': anonymize(str(x['userid']) + rand)[:5],
            #'source': x['source'],
        }

        return result

    return generic_wrapper(bobapi.get_month_transactions, repair_func=strip)


@blueprint.route('/v0.1/details/scan_barcode/<string:bc>',
                 methods=['GET'])
@cross_origin()
def get_barcode_details(bc):
    result = bobapi.get_product_from_barcode(bc)
    if result:
        if result['bulkid']:
            result = dict(result)
            result['bulkitem'] = dict(bobapi.get_bulkitem_from_bulkid(
                result['bulkid']))
            result['bulkitem'] = (dict(result['bulkitem'])
                                  if result['bulkitem'] else None)
    else:
        result = bobapi.get_bulkitem_from_barcode(bc)

    if not result:
        if bc.startswith("0") and len(bc) == 13:
            return get_barcode_details(bc[1:])
        if bc.startswith("0") and len(bc) == 8:
            return get_barcode_details(bc[1:-1])

        result = {"type": "unknown"}

    return jsonify(dict(result))


def generic_wrapper(func, repair_func=None,
                    singleton=False, nolist=False, **kwargs):
    if not repair_func:
        repair_func = fix_decimals

    try:
        raw_result = func(**kwargs)

        if nolist:
            result = repair_func(dict(raw_result))
        else:
            result = [dict(x) for x in raw_result]
            result = list(map(repair_func, result))

        if singleton:
            result = result[0]

        return jsonify(result)

    except:
        import traceback
        traceback.print_exc()
