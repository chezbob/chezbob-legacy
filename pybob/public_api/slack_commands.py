"""TODO: Change me!"""

import json
import requests
import time


from flask import Blueprint, jsonify, request
from flask_cors import cross_origin

from private_api.bob_api import bobapi

WAMP_CALLPOINT = "https://chezbob.ucsd.edu:8095/call"

WARNING_BALANCE = -10.0
WARNING_DAYS = 14
ERROR_BALANCE = -15.0
ERROR_DAYS = 28

UNIMPORTANT_DAYS = 7
UNIMPORTANT_BALANCE = -7.5

blueprint = Blueprint('slack_commands', __name__)


def _get_keg_status():
    COLDBREW_FN = 'chezbob.coldbrew.get_keg_status'
    r = requests.post(WAMP_CALLPOINT, json={'procedure': COLDBREW_FN})
    try:
        result = json.loads(r.text)
        return result['args'][0]
    except:
        return None


@blueprint.route('/shame', methods=['POST', 'GET'])
@cross_origin()
def shame():
    form = request.form
    result = {
        "response_type": "in_channel",
        "text": "Shame {}! Shame shame shame!".format(form['text'])
    }

    return jsonify(result)


@blueprint.route('/coldbrew', methods=['POST', 'GET'])
@cross_origin()
def coldbrew_slack_slash():
    status = _get_keg_status()

    if status.get('out_of_order', False):
        result = {
            "response_type": "in_channel",
            "text": "Coldbrew is *OUT OF ORDER* right now!"
        }
    else:
        result = {
            "response_type": "in_channel",
            "text": "{} cups sold on current keg of:\n\n> *{}*\n> {}".format(
                status.get('n_sold', 'unknown number'),
                status.get('name', 'UNKNOWN'),
                status.get('description', 'UNKNOWN DESCRIPTION'),
            ),
            #"attachments": [
            #    {
            #        "title": status.get('name', 'UNKNOWN'),
            #        "text": status.get('description', 'UNKNOWN DESCRIPTION'),
            #        "mrkdwn_in": ["text"]
            #    }
            #]
        }

    return jsonify(result)


def _get_color_from_debtor(user):
    if ((user['balance'] <= ERROR_BALANCE) or
            (user['days_on_wall'] >= ERROR_DAYS)):
        return "#f65656"
    elif ((user['balance'] <= WARNING_BALANCE) or
            (user['days_on_wall'] >= WARNING_DAYS)):
        return "#e6e636"
    #elif ((user['balance'] > UNIMPORTANT_BALANCE) and
    #        (user['days_on_wall'] < UNIMPORTANT_DAYS)):
    #    return None
    return "#999"


def _debtor_order_key(user):
    error_bonus = 0
    warning_bonus = 0
    if ((user['balance'] <= ERROR_BALANCE) or
            (user['days_on_wall'] >= ERROR_DAYS)):
        error_bonus = 1000
    elif ((user['balance'] <= WARNING_BALANCE) or
            (user['days_on_wall'] >= WARNING_DAYS)):
        warning_bonus = 100
    return (
        (float(user['balance']) / WARNING_DAYS) * (
            user['days_on_wall'] / ERROR_DAYS) -
        error_bonus - warning_bonus)


@blueprint.route('/wallofshame', methods=['POST', 'GET'])
@cross_origin()
def wall_of_shame():
    response = {
        "response_type": "in_channel",
        "text":
            "Chez Bob <http://chezbob.ucsd.edu/wall_of_shame.html|Wall of Shame>",
        "attachments": [],
    }

    debtors = bobapi.get_wall_of_shame()
    for row in sorted(debtors, key=_debtor_order_key):
        if row['balance'] > -7.5 and row['days_on_wall'] < 7:
            continue

        line = "`{:30} owes ${:5.2f}  ({:2.0f} days on wall)`".format(
            row['nickname'], -1 * row['balance'], row['days_on_wall'])

        attachment = {"fallback": line, "text": line, "mrkdwn_in": ["text"]}

        color = _get_color_from_debtor(row)
        if color:
            attachment['color'] = color
            response["attachments"].append(attachment)

    response['attachments'].append({
        "fallback": "Refresh",
        "callback_id": "wallofshame_refresh",
        "color": "#88ccf7",
        "attachment_type": "default",
        "ts": time.time(),
        "actions": [
            {
                "name": "refresh",
                "text": "Refresh",
                "type": "button",
                "value": "refresh"
            },
        ]
    })

    return jsonify(response)
