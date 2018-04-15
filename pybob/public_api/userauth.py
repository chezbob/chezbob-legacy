"""TODO: Change me!"""
import time
import sys

from flask import Blueprint, jsonify, request
from flask_cors import cross_origin

from jose import jwt, JWTError

from secrets import get_secret
from private_api.bob_api import bobapi

VALID_FOR_TIME_S = 300
JWT_SECRET = get_secret('jwt.secret')
JWT_ALGO = get_secret('jwt.algo')

blueprint = Blueprint('userauth', __name__)

"""
>>> token = jwt.encode({'key': 'value'}, JWT_SECRET, algorithm=JWT_ALGO)
>>> data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
"""


def log(*args):
    sys.stderr.write(" ".join([str(x) for x in args]))
    sys.stderr.write("\n")


def _mktoken(userid):
    exp = int(time.time()) + VALID_FOR_TIME_S
    verified = {
        "uid": userid,
        "exp": exp,
    }
    return jwt.encode(verified, JWT_SECRET, algorithm=JWT_ALGO), exp


def decodetoken(token):
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError as e:
        log("Failed to validate token: {} because {}".format(token, e))
        return None


@blueprint.route('/authenticate_from_bc/<string:barcode>')
@cross_origin()
def _authenticate_from_bc(barcode):
    results = bobapi.get_user_from_barcode(barcode)
    if not results:
        return jsonify(None)

    results = dict(zip(
        ["userid", "username", "nickname", "balance"],
        results))
    results['balance'] = float(results['balance'])

    token, exp = _mktoken(results['userid'])
    results['token'] = token
    results['exp'] = exp

    return jsonify(results)


@blueprint.route('/renew_token', methods=['POST', 'GET'])
@cross_origin()
def _renew_token():
    token = request.form.get('token', None)
    if not token:
        return jsonify({"result": "error", "error": "Token required"})

    result = decodetoken(token)
    if result is None:
        return jsonify({"result": "error", "error": "Invalid token"})

    new_token, exp = _mktoken(result['uid'])

    return jsonify({"token": new_token, "exp": exp})


@blueprint.route('/validate_token', methods=['POST', 'GET'])
@cross_origin()
def _validate_token():
    token = request.form.get('token', None)
    if not token:
        return jsonify({"result": "error", "error": "Token required"})

    result = decodetoken(token)
    if result is None:
        return jsonify({"result": "error", "error": "Invalid token"})

    result['result'] = 'success'

    return jsonify(result)
