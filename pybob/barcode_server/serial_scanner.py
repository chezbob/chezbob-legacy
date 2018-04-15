"""A simple serial-reading scanner interface.

The beeps are available on many Honeywell/Handheld Products scanners, but
shouldn't hurt anything on other serial scanners.

"""

import sys

import serial

SERIAL_TIMEOUT = 1
ESC = b'\x1b'


def _mkcmd(scanner_id, parts):
    """Generate the command from its parts."""
    res = str(scanner_id).encode()
    return res + ESC + parts + b","


_BAD_COMMAND = b"b"
_OK_COMMAND = b"a"
_OK_READ = b"7"


class SerialBarcodeScanner(object):
    """A simple non-threaded serial barcode scanner interface."""
    def __init__(self, port, *args, **kwargs):
        super(SerialBarcodeScanner, self).__init__(*args, **kwargs)
        self.dev = serial.Serial(port, timeout=SERIAL_TIMEOUT)

    def get_barcode(self):
        """Retrieve a barcode."""
        barcode = self.dev.readline().strip().decode('utf-8')

        if not barcode:
            return None

        try:
            if len(barcode) >= 2 and barcode[1] == ';':
                return int(barcode[0]), barcode[2:]
        except ValueError:
            pass

        return 0, barcode

    def simple_beep(self, scanner_id=0):
        """Emit a simple beep."""
        self.dev.write(_mkcmd(scanner_id, _OK_READ))

    def good_beep(self, scanner_id=0):
        """Emit a happy beep."""
        self.dev.write(_mkcmd(scanner_id, _OK_COMMAND))

    def bad_beep(self, scanner_id=0):
        """Emit an unhappy beep."""
        self.dev.write(_mkcmd(scanner_id, _BAD_COMMAND))

    def supports_beep(self):  # pylint: disable=no-self-use
        """Whether or not we support beeping."""
        return True


if __name__ == "__main__":
    sys.exit(1)
