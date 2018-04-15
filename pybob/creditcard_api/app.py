import sys

import stripe

from flask import Flask, jsonify, request
from flask.json import JSONEncoder

from private_api import db
from private_api.bob_api import BobApi
from secrets import get_secret

import decimal


class DecimalFriendlyJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        return super().default(obj)


app = Flask(__name__)
app.json_encoder = DecimalFriendlyJSONEncoder

conn = db.get_conn()
bobapi = BobApi(conn)
stripe.api_key = get_secret("stripe.live_key")


# TODO - make things log in a better way. This dumps to apache's error logs.
def log(*args):
    sys.stderr.write(" ".join([str(x) for x in args]))
    sys.stderr.write("\n")


@app.route('/api/v0.1/validate_user/<string:username>', methods=['GET'])
def validate_user(username):
    return jsonify({
        "success": bobapi.is_valid_username(username),
        "username": username})


@app.route('/api/v0.1/get_balance/<string:username>', methods=['GET'])
def get_balance(username):
    log(("INFO: Received balance request for {}").format(username))
    return jsonify({
        "balance": bobapi.get_balance(username),
        "username": username})


def approx_equals(a, b, margin):
    return a - margin <= b and b <= a + margin


@app.route('/api/v0.1/stripe_deposit', methods=['POST', 'GET'])
def deposit():
    error = ""
    success = False

    # Get the credit card details submitted by the form
    token = request.form['token']
    credit_amount = request.form['credit_amount']
    charged_amount = request.form['charged_amount']
    username = request.form['username']

    try:
        credit_amount = round(float(credit_amount))
        charged_amount = int(charged_amount)
    except Exception:
        log(("ERROR: Received request to charge {} {} cents for {} cents"
             " credit, but the amounts weren't convertible to ints.").format(
                 username, charged_amount, credit_amount))
        return jsonify({"success": False, "error": "invalid charge amounts"})

    if not token:
        log(("ERROR: Received request to charge {} {} cents "
             "for {} cents credit, but the token was invalid.").format(
                 username, charged_amount, credit_amount))
        return jsonify({"success": False, "error": "invalid token"})

    calculated_charge_amount = int(round((credit_amount + 30) / .971))
    if not approx_equals(charged_amount, calculated_charge_amount, 1):
        log(("ERROR: Received request to charge {} {} cents "
             "for {} cents credit, but the charge amount was invalid.").format(
                 username, charged_amount, credit_amount))
        return jsonify({"success": False, "error": "invalid charge amount"})

    if not bobapi.is_valid_username(username):
        log(("ERROR: Received request to charge {} {} cents "
             "for {} cents credit, but the username is invalid.").format(
                 username, charged_amount, credit_amount))
        return jsonify({"success": False, "error": "invalid username"})

    # Create the charge on Stripe's servers - this will charge the user's card
    try:
        stripe.Charge.create(
            amount=charged_amount,  # amount in cents, again
            currency="usd",
            source=token,
            description="Deposit for {}".format(username)
        )
    except stripe.error.CardError as e:
        # The card has been declined
        error = "card declined"
    else:
        try:
            bobapi.make_deposit(username, credit_amount / 100,
                                'BY CC', 'webpayment')
            success = True
        except bobapi.InvalidOperationException as e:
            error = (
                "Error: {} (but card charged). "
                "Please contact Chez Bob for assistance.".format(e))
        except Exception as e:
            error = (
                "Unknown error (but card charged). "
                "Please contact Chez Bob for assistance.".format(e))

    if not success:
        log(("ERROR: Received request to charge {} {} cents "
             "for {} cents credit, but received error {}.").format(
                 username, charged_amount, credit_amount, error))
    else:
        log(("SUCCESS: Charged {} {} cents for {} cents credit.").format(
            username, charged_amount, credit_amount))
    return jsonify({"success": success, "error": error})
