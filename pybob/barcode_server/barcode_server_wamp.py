#!/usr/bin/env python
"""A WAMP/crossbar-based barcode server."""

from __future__ import print_function

import argparse
import logging
import threading
import six

from autobahn.twisted.wamp import ApplicationSession
from autobahn.twisted.wamp import ApplicationRunner

import txaio

try:
    from queue import Queue, Empty
except ImportError:
    from Queue import Queue, Empty
import sys

from threaded_barcode_scanner import ThreadedBarcodeScanner
from hid_scanner import HIDBarcodeScanner
from serial_scanner import SerialBarcodeScanner

# Bullshit nfcpy only handles python 2 - :-P
if (sys.version_info < (3, 0)):
    from nfc_scanner import NFCScanner

# DEFAULT_CONFIG_FILE = "/etc/chezbob.json"


LOG_FORMAT = '%(asctime)-15s %(module)s %(levelname)s %(message)s'


scanners = []


def get_enqueuer(q):
    def enqueue_barcode(_, barcode):
        q.put(barcode)
    return enqueue_barcode


def get_running_scanner(scanner, cb):
    tscanner = ThreadedBarcodeScanner(scanner)
    tscanner.start()
    tscanner.get_barcode(callback=cb)
    return tscanner


def scanners_have_died():
    for scanner in scanners:
        if not scanner.is_alive():
            return True
    return False


class BarcodeSender(ApplicationSession):
    """
    Sends barcodes to wamp.
    """

    def _send_thread(self):
        # signal we are done with initializing our component
        self.publish(u'{}.connected'.format(self._prefix))
        self.log.info("Thread alive")

        while not self._thread_should_exit.is_set():
            try:
                barcode = self._q.get(timeout=1)
            except Empty:
                if scanners_have_died():
                    break
                continue

            self.log.info(barcode)
            self.publish(u'{}.barcode'.format(self._prefix), barcode)

    def onJoin(self, details):
        print("OnJoin called")

        args = self.config.extra['args']
        self._q = self.config.extra['queue']

        self._prefix = u'chezbob.scanner.{}'.format(args.NAME)

        self._thread_should_exit = threading.Event()
        self._thread = threading.Thread(target=self._send_thread)
        self._thread.daemon = True
        self._thread.start()

    def onLeave(self, details):
        self.log.info("Session closed: {details}", details=details)
        self._thread_should_exit.set()
        self._thread.join()
        self.disconnect()

    def onDisconnect(self):
        self.log.info("Connection closed")


def get_args():
    parser = argparse.ArgumentParser()
    #parser.add_argument('-c', '--config_file', type=argparse.FileType(),
    #                    default=file(DEFAULT_CONFIG_FILE),
    #                    help="Configuration file to use.")
    parser.add_argument("-v", "--debug", action='store_true',
                        help='Print debugging messages')
    parser.add_argument("-r", "--router", type=six.text_type,
                        default=u"wss://chezbob.ucsd.edu:8095/ws",
                        help='Router URL.')
    parser.add_argument("--realm", type=six.text_type, default=u"chezbob",
                        help='Router realm.')
    parser.add_argument('-i', '--hid_device', action='append',
                        help="HID device to open")
    parser.add_argument('-s', '--serial_device', action='append',
                        help="Serial device to open")

    if (sys.version_info < (3, 0)):
        parser.add_argument('-n', '--nfc_device', action='append',
                            help="NFC devices to open")

    parser.add_argument("NAME", type=str,
                        help='Name for this barcode reader')

    #parser.add_argument('-b', '--background', action="store_true",
    #                    help="Run in background (requires -o)")
    return parser.parse_args(), parser


def start_scanners(args):
        q = Queue()
        enqueuer = get_enqueuer(q)

        scanners = []
        if args.serial_device:
            for name in args.serial_device:
                sscanner = SerialBarcodeScanner(name)
                scanners.append(get_running_scanner(sscanner, enqueuer))

        if args.hid_device:
            for name in args.hid_device:
                iscanner = HIDBarcodeScanner(name)
                scanners.append(get_running_scanner(iscanner, enqueuer))

        if (sys.version_info < (3, 0)):
            if args.nfc_device:
                for name in args.nfc_device:
                    nscanner = NFCScanner(name)
                    scanners.append(get_running_scanner(nscanner, enqueuer))

        return scanners, q


def setup_logging(verbose, logfile=None):
    root_logger = logging.getLogger()
    formatter = logging.Formatter(LOG_FORMAT)
    streamhandler = logging.StreamHandler()
    streamhandler.setFormatter(formatter)
    root_logger.addHandler(streamhandler)

    if logfile:
        filehandler = logging.FileHandler(logfile)
        filehandler.setFormatter(formatter)
        root_logger.addHandler(filehandler)

    root_logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # They use txaio's logging. We use the logging module.
    # They should interplay just fine, but it's nice to be explicit.
    txaio.start_logging(level='debug' if verbose else 'info')


def main():
    # parse command line arguments
    global scanners
    args, _ = get_args()

    setup_logging(args.debug)

    scanners, q = start_scanners(args)

    # create and start app runner for our app component ..
    extra = {"args": args, "queue": q}
    runner = ApplicationRunner(url=args.router, realm=args.realm, extra=extra)
    runner.run(BarcodeSender, auto_reconnect=True)


if __name__ == "__main__":
    sys.exit(main())
