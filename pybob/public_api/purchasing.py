"""TODO: Change me!"""
import sys

from flask import Blueprint, jsonify, request
from flask_cors import cross_origin

from private_api.bob_api import bobapi, InvalidOperationException
from .userauth import decodetoken


blueprint = Blueprint('purchasing', __name__)


ACCEPTABLE_SOURCES = ['elektra', 'mobile', 'web']

"""
>>> token = jwt.encode({'key': 'value'}, JWT_SECRET, algorithm=JWT_ALGO)
>>> data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
"""


def log(*args):
    sys.stderr.write(" ".join([str(x) for x in args]))
    sys.stderr.write("\n")


@blueprint.route('/by_barcode', methods=['POST'])
@cross_origin()
def _purchase_by_barcode():
    token = request.form.get('token', None)
    barcode = request.form.get('barcode', None)
    source = request.form.get('source', "elektra")
    if not token or not barcode:
        return jsonify({"result": "error",
                        "error": "Token and barcode required"})

    if source not in ACCEPTABLE_SOURCES:
        return jsonify({"result": "error",
                        "error": "Invalid source"})

    decoded = decodetoken(token)
    if decoded is None:
        return jsonify({"result": "error", "error": "Invalid token"})

    return _purchase_by_barcode_unwrapped(barcode, decoded['uid'], source)


def _purchase_by_barcode_unwrapped(barcode, userid, source):
    try:
        new_row = bobapi.buy_barcode(userid, barcode, source=source)

    except InvalidOperationException as e:
        if barcode.startswith("0") and len(barcode) == 13:
            log("Retrying barcode check with EAN->UPCA: {}".format(barcode))
            return _purchase_by_barcode_unwrapped(barcode[1:], userid, source)

        if barcode.startswith("0") and len(barcode) == 8:
            log("Retrying barcode check with shorter UPC-E: {}".format(
                barcode))
            return _purchase_by_barcode_unwrapped(
                barcode[1:-1], userid, source)

        return jsonify({"result": "error", "error": str(e)})

    return jsonify({"result": "success", "transaction": new_row})
