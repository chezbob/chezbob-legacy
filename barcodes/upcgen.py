#!/usr/bin/python

"""Extremely simple program to generate UPC barcode images.

Expects a list of barcodes to be specified on the command-line, and creates an
image for each one.  Only encodes standard 12-digit UPC-A barcodes
(EAN.UCC-12), not any other variants.  Expects the checksum digit to be
included as part of the provided barcode, and does not perform any checks that
the checksum digit is correct.

Doesn't produce any fancy barcode formatting either, just a single solid block
of bars.

Based on the article at <http://en.wikipedia.org/wiki/Universal_Product_Code>.
"""

__author__ = "Michael Vrable <mvrable@cs.ucsd.edu>"

import re
import sys
from PIL import Image

# Binary encodings of digits in UPC barcodes.  These are the L encodings, used
# for the left half of the barcode; the R encodings used in the right half are
# the one's complement of these codes.
upc_codes = {
    '0': "0001101",
    '1': "0011001",
    '2': "0010011",
    '3': "0111101",
    '4': "0100011",
    '5': "0110001",
    '6': "0101111",
    '7': "0111011",
    '8': "0110111",
    '9': "0001011",
}
start_code = "101"
guard_code = "01010"

def upc_encode_digit(digit, form='L'):
    """Return the encoded form of a single UPC digit.

    'form' is optional and should be either "L" (default) or "R", depending
    upon whether the left- or right-handed side encoding is desired.
    """

    result = upc_codes[digit]
    if form == 'R':
        result = "".join([{'0': '1', '1': '0'}[c] for c in result])
    return result

def upc_to_bits(digits):
    """Convert a string of digits to the sequence of bits which represent it."""

    if len(digits) != 12:
        raise ValueError("Invalid barcode length (expected 12 digits)")

    digits_l = list(digits[0:6])
    digits_r = list(digits[6:12])

    barcode = start_code
    for d in digits_l:
        barcode += upc_encode_digit(d, 'L')
    barcode += guard_code
    for d in digits_r:
        barcode += upc_encode_digit(d, 'R')
    barcode += start_code

    return barcode

def bits_to_image(bits, height=50):
    rawbits = "".join([{'0': '\377', '1': '\0'}[c] for c in bits])
    im = Image.frombytes('L', (len(bits), 1), rawbits)
    return im.resize((len(bits), height)).convert('1')

def html_escape(text):
    """Replace HTML characters with escape characters as needed.

    This function only escapes the four characters <, >, &, and ".
    """

    names = {'<': "lt", '>': "gt", '&': "amp", '"': "quot"}
    return re.sub('([<>&"])', lambda m: "&" + names[m.group(1)] + ";", text)

def generate_template(barcode_list, template, output):
    """Generate an HTML page containing a collection of barcodes.

    barcode_list should be a list of descriptions of the barcodes to include.
    DOCUMENT FORMAT HERE.  template should be a string with the HTML template
    to use; it should contain the text "%BARCODES%" which will be replaced with
    the actual set of barcodes.  output should be an open file-like object to
    which the page will be written.
    """

    barcodes = []
    for (title, img, subtext) in barcode_list:
        barcodes.append('<div class="barcodeblock">\n'
                        '  <div class="barcodetitle">%s</div>\n'
                        '  <img src="%s" class="barcode" '
                           'alt="[Barcode: %s]" />\n'
                        '  <div class="digits">%s</div>\n'
                        '</div>' % (html_escape(title), img, subtext, subtext))

    output.write(re.sub("%BARCODES%", "\n\n".join(barcodes), template))

if __name__ == '__main__':
    barcode_list = []
    for l in open("barcodes.txt").readlines():
        l = l.strip()
        m = re.match(r"^(\d{12}):(.*)$", l)
        if m:
            (barcode, text) = (m.group(1), m.group(2))
            image = bits_to_image(upc_to_bits(barcode))
            filename = barcode + ".png"
            image.save(filename)
            barcode_list.append((text, filename, barcode))
        else:
            print >>sys.stderr, "Ignoring line: " + l

    if barcode_list:
        template = open("barcodes-template.html").read()
        output = open("barcodes.html", 'w')
        generate_template(barcode_list, template, output)
