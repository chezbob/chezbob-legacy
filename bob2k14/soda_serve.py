#!/usr/bin/env python3.4

"""SodaServe, The ChezBob JSON-RPC Database Server.

Usage:
  soda_serve.py serve <dburl> [--config=<config-file>] [--mdb-server-ep=<ep>] [--vdb-server-ep=<ep>] [--address=<listen-address>] [--port=<port>] [--log_level=<level>]
  soda_serve.py (-h | --help)
  soda_serve.py --version

Options:
  -h --help                     Show this screen.
  --version                     Show version.
  --config=<config-file>        Use alternate config file. [default: config.json]
  --address=<listen-address>    Address to listen on. [default: 0.0.0.0]
  --port=<port>                 Port to listen on. [default: 8080]
  --mdb-server-ep=<ep>          Endpoint of MDB server. [default: http://127.0.0.1:8081/api]
  --vdb-server-ep=<ep>          Endpoint of VDB server. [default: http://127.0.0.1:8083/api]
  --log_level=<level>           Level of logging to do.  Notably SQLAlchemy is only allowed to
                                dump messages at level=DEBUG.  Can be DEBUG, INFO, WARNING,
                                ERROR, or CRITICAL.

"""
from docopt import docopt

from flask import Flask, Response, jsonify
from flask_jsonrpc import JSONRPC
from flask_cors import cross_origin
from flask.ext.sqlalchemy import SQLAlchemy

from soda_session import SessionLocation, SessionManager, Session, User
import subprocess
import json
import soda_app
import os
import time
import requests
import sys
from models import app, db, aggregate_purchases, products, transactions, users, userbarcodes, roles, soda_inventory
from decimal import *
from enum import Enum
import logging
import traceback

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

##########
#from sqlalchemy import func

class vmcstates(Enum):
    reset = 0
    enabled = 1
    vsession = 2
    vsessionidle = 3
    configured = 4
    vapproved = 5
    vdeny = 6
    vsessionend = 7
    disabled = 8
    cancel = 9

class sodastates(Enum):
    unknown = 0
    available = 1
    empty = 2

def get_git_revision_hash():
    return str(subprocess.check_output(['git', 'rev-parse', 'HEAD', '--work-tree=/git' ,'--git-dir=/git']))

def to_jsonify_ready(model):
    """ Returns a JSON representation of an SQLAlchemy-backed object.
    """
    json = {}
    if model != None:
        for col in model._sa_class_manager.mapper.mapped_table.columns:
            json[col.name] = str(getattr(model, col.name))

    return json

# Flask-JSONRPC
jsonrpc = JSONRPC(app, '/api', enable_web_browsable_api=True)

@app.after_request
def add_header(response):
    """
    Add headers to disable caching
    """
    response.headers['Cache-Control'] = 'no-cache, no-store'
    response.headers['Pragma'] = 'no-cache'
    return response

@jsonrpc.method('Soda.index')
@cross_origin()
def json_index():
    return 'SodaServe ' + get_git_revision_hash()

@jsonrpc.method('Soda.products')
@cross_origin()
def product(barcode):
    return to_jsonify_ready(products.query.filter(products.barcode==barcode).first())

def make_purchase(user, product, location, privacy=False):
    app.logger.info("%s purchasing %s from %s" % (user.username, product.name, location))
    # Get the purchase price of the item
    value = product.price
    # Deduct the balance from the user's account
    user.balance -= value

    today = time.strftime("%Y-%m-%d")
    aggregates = aggregate_purchases.query.filter(\
      aggregate_purchases.date == today,\
      aggregate_purchases.barcode == product.barcode,\
      aggregate_purchases.price == value,\
      aggregate_purchases.bulkid == product.bulkid).all()

    if (len(aggregates) == 0):
      aggregate = aggregate_purchases(product.barcode, value, product.bulkid)
      db.session.add(aggregate)
    else:
      aggregate = aggregates[0]
      aggregate.quantity = aggregate.quantity + 1
      db.session.add(aggregate)

    # Insert into the transaction table, respecting the user's privacy settings
    barcode = product.barcode
    description = "BUY " + product.name.upper()
    if privacy:
        description = "BUY"
        barcode = ""
    transact = transactions(userid=user.userid, xactvalue=-value, xacttype=description, barcode=barcode, source=location)
    # Commit our changes
    db.session.add(transact)
    db.session.merge(user)
    db.session.commit()
    return True

def make_purchase_other(user, value, location):
    app.logger.info("%s making other purchase for %s from %s" % (user.username, value, location))
    # fail if the price doesn't make sense
    if (value < 0):
        return False
    # update the balance
    user.balance -= value
    app.logger.debug("deducted value")
    # now create a matching record in transactions
    transact = transactions(userid=user.userid, xactvalue=-value, xacttype="BUY OTHER", barcode=None, source="chezbob2k14")
    app.logger.debug("made transaction")
    # commit our changes
    db.session.add(transact)
    db.session.merge(user)
    db.session.commit()
    app.logger.debug("merged")
    return True

def make_deposit(user, amount, location):
    app.logger.info("%s is depositing %s from %s" % (user.username, amount, location))
    # update the user's balance
    user.balance += Decimal(amount)
    # make a matching record in transactions
    transact = transactions(userid=user.userid, xactvalue=amount, xacttype="ADD", barcode=None, source=location)
    # commit our changes
    db.session.add(transact)
    db.session.merge(user)
    db.session.commit()
    return True

def adduserbarcode(user, barcode):
    # Technically, this only makes sense if the user is logged in.
    # No other function seems to be checking, though, so...

    #if not sessionmanager.checkSession(SessionLocation.computer):
    #    return False
    # -- OR --
    #if userid is None:
    #    return False

    barcode = barcode.strip(' "')
    app.logger.info("Attempting to add barcode %s to user %s" % (barcode, user.username))
    ubc = userbarcodes.query.filter(userbarcodes.barcode==barcode).first()
    app.logger.debug("Queried for barcode %s" % (barcode,))

    if ubc is None:
        # We didn't find a barcode like that one, so we can create a new one.
        app.logger.debug("...barcode is available")

        ubc = userbarcodes(userid=user.userid, barcode=barcode)
        app.logger.debug("...attempting to commit")

        db.session.merge(ubc)
        db.session.commit()
        return True
    elif ubc.userid != user.userid:
        # We found this barcode in use by another user
        app.logger.debug("...barcode in use")

        sys.stdout.flush()
        raise Exception("Barcode in use")
    app.logger.debug("...barcode trivially satisfied")

    # Implicitly, we may have already found that barcode in use.
    # In which case, we succeed by default.

    return True

@jsonrpc.method('Soda.remotebarcode')
def remotebarcode(type, barcode):
    #several things to check here. first, if there is anyone logged in, we're probably buying something, so check that.
    if sessionmanager.checkSession(SessionLocation.soda):
         app.logger.info("found barcode %s, probably buying something" % (barcode,))
         # Get the user, product, location, and privacy settings
         user = sessionmanager.sessions[SessionLocation.soda].user.user
         product = products.query.filter(products.barcode==barcode).first()
         location = "soda"
         privacy = sessionmanager.sessions[SessionLocation.soda].user.privacy
         # make a purchase, which also updates the db
         if (product):
              make_purchase(user, product, location, privacy)
         soda_app.add_event("sbc" + barcode)
    else:
         app.logger.info("found barcode %s, probably trying to log in" % (barcode,))
         #do a login
         user = User()
         user.login_barcode(barcode)
         #logout any existing session
         sessionmanager.deregisterSession(SessionLocation.soda)
         sessionmanager.registerSession(SessionLocation.soda, user)
    return ""

def sendvdbfailemail(hopper):
    msg = MIMEMultipart('alternative')
    #ok useful to fetch the soda name here
    msg['Subject'] = "Soda is out"
    msg['From'] = "chezbob@cs.ucsd.edu"
    msg['To'] = "chezbob@cs.ucsd.edu"
    htmlout = """
    """.format()
    plainout = """
    """.format()
    msg.attach(htmlout, 'html')
    msg.attach(plainout, 'plain')
    s = smtplib.SMTP('localhost')
    s.sendmail(msg['From'], msg['To'], msg.as_string())
    s.quit()

#simplified authorization logic.
#TODO: extend a users session until the request finishes... (in UI)
@jsonrpc.method('Soda.vdbauth')
def vdbauth(vending_soda):
    if sessionmanager.checkSession(SessionLocation.soda):
        #ui should show dispensing...
        soda_app.add_event("vdr" + configdata["sodamapping"][vending_soda])
        return True
    else:
        soda_app.add_event("vdd")
        return False

@jsonrpc.method('Soda.vdbvend')
def vdbvend(result, vending_soda):
    if result:
        soda_updateinventory(vending_soda, soda_getinventory()[vending_soda] - 1)
        remotebarcode("R", configdata["sodamapping"][vending_soda])
    else:
        soda_updateinventory(vending_soda, 0)
        soda_app.add_event("vdf")

### ALERT TODO: This API is now depercated! DO NOT USE IT ANYMORE!
#this should be safe since only one can can be vended at once...
# TODO: we need better debug messages here but I'm not sold on what it's doing.
lastsoda = ""
@jsonrpc.method('Soda.remotevdb')
def remotevdb(event):
    global lastsoda
    if "CLINK: REQUEST AUTH" in event:
        #someone is trying to buy a soda. if no one is logged in, tell them guest mode isn't ready.
         if sessionmanager.checkSession(SessionLocation.soda):
              app.logger.debug("purchase: " + event[20:22])
              soda_app.add_event("vdr" + configdata["sodamapping"][event[20:22]])
              result = soda_app.make_jsonrpc_call(soda_app.arguments["--vdb-server-ep"], "Vdb.command", ["A"])
              lastsoda = event[20:22]
         else:
              soda_app.add_event("vdd")
              result = soda_app.make_jsonrpc_call(soda_app.arguments["--vdb-server-ep"], "Vdb.command", ["D"])
    elif "CLINK: VEND FAIL" in event:
        #vend failed, don't charge
        #also record and let people known that it failed...
        #TODO: Log an error if the lastsoda count is not 0!
        soda_updateinventory(lastsoda, 0)
        #send the e-mail
        soda_app.add_event("vdf")
    elif "CLINK: VEND OK" in event:
        #vend success
        soda_updateinventory(lastsoda, soda_getinventory()[lastsoda] - 1)
        app.logger.debug("vend success: " + lastsoda)
        remotebarcode("R", configdata["sodamapping"][lastsoda])

# TODO: need better logging here as well
@jsonrpc.method('Soda.remotemdb')
def remotemdb(event):
    #let's make sure theres a user logged in. if not, just tell them that guest mode isn't ready yet.
    if event[0:2] == "Q1":
         if sessionmanager.checkSession(SessionLocation.soda):
              result = soda_app.make_jsonrpc_call(soda_app.arguments["--mdb-server-ep"], "Mdb.command", ["K1"])
         else:
              result = soda_app.make_jsonrpc_call(soda_app.arguments["--mdb-server-ep"], "Mdb.command", ["K2"])
    elif event [0:2] == "Q2":
         #well, someone better be logged in. the bill was stacked.
         billtype = event[3:5]
         amount = 0
         if billtype == "00":
              amount = 1
         elif billtype == "01":
              amount = 5
         elif billtype == "02":
              amount = 10
         elif billtype == "03":
              amount = 20
         elif billtype == "04":
              amount = 50
         elif billtype == "05":
              amount = 100
         #now credit to the user.
         user = sessionmanager.sessions[SessionLocation.soda].user.user
         make_deposit(user, amount, "soda")
         soda_app.add_event("deb" + str(amount))
    elif event [0:2] == "P1":
         if not sessionmanager.checkSession(SessionLocation.soda):
              #refund it since we're not logged in.
              result = soda_app.make_jsonrpc_call(soda_app.arguments["--mdb-server-ep"], "Mdb.command", ["G " + event[3:5] + " 01"])
         else:
              #coins!
              cointype = event[3:5]
              amount = 0
              if cointype == "00":
                   amount = 0.5
              elif cointype == "01":
                   amount = 0.10
              elif cointype == "02":
                   amount = 0.25
              #now credit to the user
              user = sessionmanager.sessions[SessionLocation.soda].user.user
              make_deposit(user, amount, "soda")
         soda_app.add_event("dec" + str(amount))
    elif event [0:1] == "W":
         #logout
         #get rid of bills in escrow (guessing this is what people expect)
         #TODO: THIS NEEDS TO HAPPEN WHENEVER A LOGOUT OCCURS AND THE BILL IS NT STACKED
         #result = soda_app.make_jsonrpc_call(soda_app.arguments["--mdb-server-ep"], "Mdb.command", ["K2"])
         sessionmanager.deregisterSession(SessionLocation.soda)
    return ""

@jsonrpc.method('Soda.getusername')
def soda_getusername():
    if sessionmanager.sessions[SessionLocation.soda].user.user.nickname == None:
         return sessionmanager.sessions[SessionLocation.soda].user.user.username
    else:
         return sessionmanager.sessions[SessionLocation.soda].user.user.nickname

@jsonrpc.method('Soda.getbalance')
def soda_getbalance():
    #force the balance to update
    userid = sessionmanager.sessions[SessionLocation.soda].user.user.userid
    user = users.query.filter(users.userid == userid).first()
    return str(user.balance)

@jsonrpc.method('Soda.getroles')
def soda_getroles():
    #get user roles
    userid = sessionmanager.sessions[SessionLocation.soda].user.user.userid
    row = roles.query.filter(roles.userid == userid).first()
    if (not row):
      roles_lst = []
    else:
      roles_lst = row.roles.split(",")

    return { "userid" : userid, "roles": roles_lst }

@jsonrpc.method('Soda.passwordlogin')
def soda_passwordlogin(username, password):
    user = User()
    user.login_password(username,password)
    #logout any existing session
    sessionmanager.deregisterSession(SessionLocation.soda)
    sessionmanager.registerSession(SessionLocation.soda, user)
    return to_jsonify_ready(sessionmanager.sessions[SessionLocation.soda].user.user)

@jsonrpc.method('Soda.logout')
def bob_logout():
    sessionmanager.deregisterSession(SessionLocation.soda)
    return ""

@jsonrpc.method('Soda.getinventory')
def soda_getinventory():
    inv = {}
    for row in soda_inventory.query.all():
      inv[row.slot] = row.count
    return inv

@jsonrpc.method('Soda.updateinventory')
def soda_updateinventory(slot, count):
    app.logger.info("Updating soda slot %s to %s" % (str(slot), str(count)))
    row = soda_inventory.query.filter(soda_inventory.slot == slot).first();

    if (row == None):
      raise InvalidParamError("Unknown slot " + slot)

    icount = int(count)

    if (icount < 0):
      icount = 0;

    row.count = icount
    db.session.add(row);
    db.session.commit()
    return ""

def strTB():
    return "".join(traceback.format_stack()[:-1])

def log(level, msg):
    if (level == "INFO"):
      app.logger.info(msg)
    elif (level == "WARN"):
      app.logger.warn(msg)
    elif (level == "DEBUG"):
      app.logger.debug(msg)
    elif (level == "ERROR"):
      app.logger.error(msg)
    elif (level == "FATAL"):
      app.logger.fatal(msg)
    elif (level == "CRITICAL"):
      app.logger.critical(msg)
    else:
      app.logger.critical("Bad level %s at:\n %s" % (level, strTB()))
      app.logger.critical(msg)

@jsonrpc.method('Soda.log')
def soda_log(level, msg):
    log(level, "SODA UI SAYS: " + msg)
    return ""

@jsonrpc.method('Bob.adduserbarcode')
def bob_adduserbarcode(barcode):
    userid = sessionmanager.sessions[SessionLocation.computer].user.user
    return adduserbarcode(userid, barcode)

@jsonrpc.method('Bob.getuserbarcode')
def bob_getuserbarcode(barcode):
    userid = sessionmanager.sessions[SessionLocation.computer].user.user.userid

    ubc = userbarcodes.query.filter(userbarcodes.userid==userid).first()
    if ubc is None:
        return ""
    return ubc.barcode

#bob tasks
@jsonrpc.method('Bob.index')
def bob_json_index():
    return 'SodaServe (Bob) ' + get_git_revision_hash()

@jsonrpc.method('Bob.passwordlogin')
def bob_passwordlogin(username, password):
    user = User()
    user.login_password(username,password)
    #logout any existing session
    sessionmanager.deregisterSession(SessionLocation.computer)
    sessionmanager.registerSession(SessionLocation.computer, user)
    return to_jsonify_ready(sessionmanager.sessions[SessionLocation.computer].user.user)

@jsonrpc.method('Bob.barcodelogin')
def bob_barcodelogin(barcode):
    user = User()
    user.login_barcode(barcode)
    #logout any existing session
    sessionmanager.deregisterSession(SessionLocation.computer)
    sessionmanager.registerSession(SessionLocation.computer, user)
    return to_jsonify_ready(sessionmanager.sessions[SessionLocation.computer].user.user)

@jsonrpc.method('Bob.getusername')
def bob_getusername():
    if sessionmanager.sessions[SessionLocation.computer].user.user.nickname == None:
         return sessionmanager.sessions[SessionLocation.computer].user.user.username
    else:
         return sessionmanager.sessions[SessionLocation.computer].user.user.nickname

@jsonrpc.method('Bob.getbalance')
def bob_getbalance():
    return str(sessionmanager.sessions[SessionLocation.computer].user.user.balance)

@jsonrpc.method('Bob.sodalogin')
def bob_sodalogin():
    sessionmanager.registerSession(SessionLocation.soda, sessionmanager.sessions[SessionLocation.computer].user)
    sessionmanager.deregisterSession(SessionLocation.computer)
    return to_jsonify_ready(sessionmanager.sessions[SessionLocation.soda].user.user)

@jsonrpc.method('Bob.getcrypt')
def bob_getcrypt(username):
    return users.query.filter(users.username==username).first().pwd

@jsonrpc.method('Bob.getextras')
def bob_getextras():
    extras = []
    for extra in configdata["extraitems"]:
         extras.append(to_jsonify_ready(products.query.filter(products.barcode==extra["barcode"]).first()))
    return extras

@jsonrpc.method('Bob.setpassword')
def bob_setpassword(new_password):
    user = sessionmanager.sessions[SessionLocation.computer].user.user
    app.logger.info("setpassword called for user %s" % (user.username,))
    if new_password == None or new_password == "":
        app.logger.debug("removing password for user %s" % (user.username,))
    else:
        app.logger.debug("setting new password for user %s" % (user.username,))
    user.pwd = new_password
    db.session.merge(user)
    db.session.commit()
    return True

@jsonrpc.method('Bob.setnickname')
def bob_setnickname(new_nickname):
    user = sessionmanager.sessions[SessionLocation.computer].user.user
    app.logger.info("setnickname called for user %s" % (user.username,))
    if new_nickname == None or new_nickname == "":
        app.logger.debug("removing nickname for user %s" % (user.username,))
    else:
        app.logger.debug("setting new nickname for user %s" % (user.username,))
    user.nickname = new_nickname
    db.session.merge(user)
    db.session.commit()
    return True

@jsonrpc.method('Bob.sendmessage')
def bob_sendmessage(message, anonymous):
    username = sessionmanager.sessions[SessionLocation.computer].user.user.username
    email = sessionmanager.sessions[SessionLocation.computer].user.user.email
    display_name = "%s (email: %s)" % (username, email)
    msg = MIMEMultipart('alternative')
    if (anonymous == "1"):
        username = "anonymous"
        display_name = username
    else:
        msg['Cc'] = email
    app.logger.info("%s is trying to send a message" % (display_name,))
    msg['Subject'] = "New ChezBob E-Mail from User"
    msg['From'] = "chezbob@cs.ucsd.edu"
    msg['To'] = "chezbob@cs.ucsd.edu"
    htmlout = """
        <html>
            <head></head>
            <body>
                Hello,<br/>
                      <br/>
                      The user {0} sent a message to ChezBob via the ChezBob interface. The message reads:<br/>
                    <br/>
                    {1}
                    <br/>
                    -eom-
            </body>
        </html>
    """.format(display_name, message)
    plainout = """
Hello,

The user {0} sent a message to ChezBob via the ChezBob interface. The message reads:

{1}

-eom-
    """.format(display_name, message)
    msg.attach(MIMEText(htmlout, 'html'))
    msg.attach(MIMEText(plainout, 'plain'))
    s = smtplib.SMTP('localhost')
    if (anonymous == "1"):
        s.sendmail(msg['From'], msg['To'], msg.as_string())
    else:
        s.sendmail(msg['From'], msg['To'] + "," + msg['Cc'], msg.as_string())
    s.quit()
    app.logger.debug("message properly sent")

@jsonrpc.method('Bob.getbarcodeinfo')
def bob_getbarcodeinfo(barcode):
    return to_jsonify_ready(products.query.filter(products.barcode==barcode).first())

@jsonrpc.method('Bob.purchasebarcode')
def bob_purchasebarcode(barcode):
    #ok, we're supposed to subtract the balance from the user first,
    user = sessionmanager.sessions[SessionLocation.computer].user.user
    product = products.query.filter(products.barcode==barcode).first()
    location = "chezbob2k14"
    privacy = sessionmanager.sessions[SessionLocation.computer].user.privacy
    return make_purchase(user, product, location, privacy)

@jsonrpc.method('Bob.purchaseother')
def bob_purchaseother(amount):
    #ok, we're supposed to subtract the balance from the user first,
    user = sessionmanager.sessions[SessionLocation.computer].user.user
    value = Decimal(amount.strip(' "'))
    return make_purchase_other(user, value, "chezbob2k14")

@jsonrpc.method('Bob.deposit')
def bob_deposit(amount):
    value = Decimal(amount.strip(' "'))
    user = sessionmanager.sessions[SessionLocation.computer].user.user
    return make_deposit(user, value, "chezbob2k14")

@jsonrpc.method('Bob.transactions')
def bob_transactions():
    userid = sessionmanager.sessions[SessionLocation.computer].user.user.userid
    query = transactions.query.filter(transactions.userid==userid).order_by(transactions.xacttime.desc()).limit(10)
    results = []
    for q in query:
         results.append(to_jsonify_ready(q))
    return results

@jsonrpc.method('Bob.logout')
def bob_logout():
    sessionmanager.deregisterSession(SessionLocation.computer)
    return ""

@jsonrpc.method('Util.force_refresh')
def util_force_refresh():
    soda_app.add_event("refresh")
    return ""

@app.route("/")
def index():
     return jsonify(to_jsonify_ready(products.query.first()))

def event_stream():
    subscription = soda_app.add_subscription()
    try:
         while True:
              result = subscription.queue.get()
              yield 'data: %s\n\n' % str(result)
    except GeneratorExit as ge:
         soda_app.remove_subscription(subscription)

@app.route('/stream')
def stream():
    return Response(event_stream(), mimetype="text/event-stream")

sessionmanager = SessionManager()
configdata = []

def setup_logging(app, log_level):
    app.debug = True
    new_handler = logging.StreamHandler(sys.stdout)
    loglevel = logging.DEBUG
    try:
        loglevel = getattr(logging, log_level.upper())
    except:
        pass
    new_handler.setLevel(loglevel)
    log_format = "%(levelname)s|%(filename)s:%(lineno)d|%(asctime)s|%(message)s"
    new_handler.setFormatter(logging.Formatter(log_format))
    print(app.logger.handlers)
    for handler in app.logger.handlers:
        app.logger.removeHandler(handler)
    app.logger.addHandler(new_handler)

if __name__ == '__main__':
    arguments = docopt(__doc__, version='SodaServe 1.0')
    log_level = "INFO"
    if 'log_level' in arguments:
        log_level = arguments['log_level']
    setup_logging(app, log_level)
    print(arguments)
    soda_app.arguments = arguments
    with open(os.path.dirname(os.path.realpath(__file__)) + "/" +  arguments["--config"]) as json_data:
        configdata = json.load(json_data)
    if log_level == "DEBUG":
        app.config["SQLALCHEMY_RECORD_QUERIES"] = True
        app.config["SQLALCHEMY_ECHO"] = True
    if arguments['serve']:
        app.config["SQLALCHEMY_DATABASE_URI"] = arguments["<dburl>"]
        app.run(host=arguments['--address'], port=int(arguments['--port']), threaded=True)
