#!/usr/bin/env python3.4
"""serial_shell, - simple serial shell for talking to a serial device directly. Mostly does pretty printing and allows for easy encoding of non-ascii charaters using hex.

Usage:
  serial_shell.py [--device=<dev>]
  serial_shell.py (-h | --help)
  serial_shell.py --version

Options:
  -h --help                 Show this screen.
  --version                 Show version.
  --device=<dev>            Path to /dev node corresponding to P115M. [default: /dev/mdb] 
"""

import sys
import os
import cmd2
from docopt import docopt
from serial import readline, writeln, _setupPair
from threading import Thread
from select import select
import string

args = docopt(__doc__, version="WTF")

# Devices
serial_fd = None
printable = set(map(ord, set(string.printable) - set(string.whitespace)))

def ppb(b):
    if b in printable:
        return "%02c " % chr(b)
    else:
        return "%02x " % b

def hexbs(s):
    return ''.join(["%02x " % x for x in s])

def ppbs(s):
    return ''.join(map(ppb, s))

class SerialShell(cmd2.Cmd):
    def do_cmd(self, line):
        print ("SEND:[%d]: %s" % (len(line), line))
        writeln(serial_fd, line)

    def do_xcmd(self, line):
        """DOC?"""
        els = line.split(' ')
        line = ''
        for x in els:
            if (x.startswith('0x')):
                line += chr(int(x, 16))
            else:
                line += x

        print ("SEND:[%d]: %s" % (len(line), line))
        writeln(serial_fd, line)

done = False
def readerThr(fd):
    while (not done):
        s, dummy1, dummy2 = select([fd], [], [], 1)
        if (fd in s):
            l =readline(fd)
            print ("RECV[%03d]: %s" %(len(l), hexbs(l)))
            print ("           %s" %ppbs(l))

try:
    serial_fd = os.open(args['--device'], os.O_RDWR | os.O_NOCTTY)
    _setupPair(serial_fd, serial_fd)
except OSError as e:
    print ("Couldn't open %s: %s" % (args['--device'], str(e)))
    sys.exit(-1)

try:
    t = Thread(target=readerThr, args=[serial_fd])
    t.start()
    sys.argv=[sys.argv[0]]
    shell = SerialShell()
    shell.cmdloop()
finally:
    done = True
    os.close(serial_fd)
    t.join();