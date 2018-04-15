"""Simple interface for sending barcodes, etc. back to the server."""

from json_rpc_client import JsonRpcClient


class Bob2k14Api(object):
    def __init__(self, endpoint, client_type, client_id):
        """
        Arguments:
            endpoint:       url of api endpoint for sodad
            client_type:    0 or 1 for normal or soda machine, respectively
            client_id:      Usually 0, but to support multiple interfaces.
        """
        if client_id is None or client_type is None:
            raise Exception("client_id and client_type cannot be None")

        self.client = JsonRpcClient(endpoint)
        self.client_id = client_id
        self.client_type = client_type

    def send_barcode(self, barcode):
        args = [self.client_type, self.client_id, None, barcode]
        return self.client.call("Soda.remotebarcode", *args)
