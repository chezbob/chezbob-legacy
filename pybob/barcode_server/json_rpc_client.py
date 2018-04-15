"""A simple json-rpc client."""

import json
import random
import sys

import requests


def _get_random_id():
    return random.randint(0, sys.maxsize)


class JsonRpcClient(object):
    endpoint = None

    def __init__(self, endpoint):
        self.headers = {'Content-Type': 'application/json'}
        self.endpoint = endpoint

    def call(self, fn_name, *params):
        request_id = _get_random_id()
        payload = {
            "method": fn_name,
            "params": params,
            "jsonrpc": "2.0",
            "id": request_id,
        }
        response = requests.post(
            self.endpoint,
            data=json.dumps(payload),
            headers=self.headers)

        return response


if __name__ == "__main__":
    sys.exit(1)
