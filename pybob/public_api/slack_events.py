"""A blueprint for handling slack 'events' and 'interactive components'.

At present, no events are handled-- the infrastructure is residual from when
this code was also responsible for various slack-maintenance stuff, and it
seemed valuable enough to keep.

"""

import json
import sys

from flask import Blueprint, jsonify, request
from flask_cors import cross_origin

from slackclient import SlackClient

from . import slack_commands

from secrets import get_secret


blueprint = Blueprint('slack_events', __name__)


SLACK_VERIFICATION_TOKEN = get_secret('slack.ucsdcse_verification_token')
sc = SlackClient(get_secret('slack.ucsdcse_token'))


# Slack event handlers -- populated via decorator
EVENT_HANDLERS = {}
REQUEST_HANDLERS = {}


def handles_event(*handled_events):
    """Decorator for slack event routing."""
    def decorator(func):
        for event in handled_events:
            EVENT_HANDLERS[event] = func
        return func
    return decorator


def handles_request(*handled_requests):
    """Decorator for slack request routing."""
    def decorator(func):
        for req in handled_requests:
            REQUEST_HANDLERS[req] = func
        return func
    return decorator


def handle_url_verification(event_data):
    sys.stderr.write("Received url_verification request.\n")

    challenge = event_data.get("challenge", None)
    if not challenge:
        return jsonify({"ok": False, "error": "Missing challenge"})
    return jsonify({"challenge": challenge})



@blueprint.route('/incoming_event', methods=['POST'])
@cross_origin()
def incoming_event():
    event_data = json.loads(request.data.decode('utf-8'))

    token = event_data.get("token", None)
    if not token:
        sys.stderr.write("Ignored slack event with no token.\n")
        return jsonify({"ok": False, "error": "Missing token"})

    if token != SLACK_VERIFICATION_TOKEN:
        sys.stderr.write("Ignored slack event with invalid token.\n")
        return jsonify({"ok": False, "error": "Invalid token"})

    typ = event_data.get("type", None)
    if not typ:
        sys.stderr.write("Ignored slack event with no type.\n")
        return jsonify({"ok": False, "error": "Request type not found"})

    if typ == "url_verification":
        return handle_url_verification(event_data)

    event = event_data['event']['type']

    response_gen = EVENT_HANDLERS.get(event, None)
    if not response_gen:
        sys.stderr.write(
            "Ignored slack event with unknown event: {}\n".format(event))
        return jsonify(
            {"ok": False,
             "error": "Unhandled request event: {}".format(event)})

    response_gen(event_data)

    if 'X-Slack-Retry-Num' in request.headers:
        sys.stderr.write(
            "Received note from slack informing us of an error:\n"
            "  Retry-num: {}\n  Retry reason: {}\n".format(
                request.headers['X-Slack-Retry-Num'],
                request.headers['X-Slack-Retry-Reason']))

    return ('', 204)


@handles_request('wallofshame_refresh')
def request_wallofshame_refresh(request_data):
    sys.stderr.write("Received Wall of Shame refresh request\n")
    return slack_commands.wall_of_shame()


@blueprint.route('/request', methods=['POST', 'GET'])
@cross_origin()
def slack_request():
    request_data = json.loads(request.form.get('payload', {}))

    token = request_data.get("token", None)
    if not token:
        sys.stderr.write("Ignored slack request with no token.\n")
        return jsonify({"ok": False, "error": "Missing token"})

    if token != SLACK_VERIFICATION_TOKEN:
        sys.stderr.write("Ignored slack request with invalid token.\n")
        return jsonify({"ok": False, "error": "Invalid token"})

    callback = request_data.get("callback_id", None)
    if not callback:
        sys.stderr.write("Ignored slack request with no callback ID.\n")
        return jsonify({"ok": False, "error": "Callback id not found"})

    response_gen = REQUEST_HANDLERS.get(callback, None)
    if not response_gen:
        sys.stderr.write(
            "Ignored slack request with no handler: {}\n".format(callback))
        return jsonify(
            {"ok": False,
             "error": "Unhandled event type: {}".format(callback)})

    return response_gen(callback)
