/// <reference path="../typings/tsd.d.ts"/>
/// <reference path="models.ts"/>

var git = require('git-rev-2');
import async = require('async');
var pkginfo = require('pkginfo')(module);
var http = require('http');
var repl = require('repl');
var stream = require('stream');
var util = require('util');
var bunyan = require('bunyan');
var jayson = require('jayson');
var jsesc = require('jsesc');
import express = require('express')
var bodyparser = require('body-parser');
var bunyanredis = require('bunyan-redis');
var io = require('socket.io');
var promise = require('bluebird');
var rpc = require('socket.io-rpc');
var pgpass = require('pgpass');
var Models = require('./models');
var crypt = require('crypt3');
var redis = promise.promisifyAll(require('redis'));
var nodemailer = promise.promisifyAll(require('nodemailer'));
var ansihtml = require('ansi-to-html');
var child_process= require("child_process");
var S = require('string');
var stripansi = require('strip-ansi');
var PNG = require('pngjs').PNG;
var JSONB = require('json-buffer');

var log;
var dblog;
var ringbuffer;
var redistransport;
var sql;
var models;
var redisclient;
var mailtransport;

class InitData {
    version: String;
    longVersion: String;

    timeout: Number;

    dbname;
    dbuser;
    dbhost;
    config;

    mdbendpoint;
    fpendpoint;

    cbemail;
    sodamap;

    loadVersion (initdata: InitData, callback: () => void) : void
    {
        log.debug("Getting version information...");
        initdata.version = module.exports.version;
        initdata.longVersion = module.exports.version;
        //if we are in a git checkout, append the short SHA.
        git.short(__dirname, function (initdata: InitData) {
            return function (err, str)
            {
                if (err === null)
                {
                    log.debug("Git checkout detected.");
                    initdata.version += "+";
                    initdata.longVersion += "/" + str;
                }
                log.info("sodad_server version " + initdata.longVersion);
                callback();
            }
        }(initdata))
    }

    prepareLogs = (initdata: InitData, callback: () => void) : void =>
    {
        ringbuffer = new bunyan.RingBuffer({ limit: 1000 });
        redistransport = new bunyanredis({
            container: 'cb_log',
            host: '127.0.0.1',
            port: 6379,
            db: 0,
            length: 5000
        });
        log = bunyan.createLogger(
                {
                    name: 'sodad-server',
                    streams: [
                    {
                        stream: process.stdout,
                        level: "info"
                    },
                    {
                        stream: ringbuffer,
                        level: "trace"
                    },
                    {
                        stream: redistransport,
                        type: "raw",
                        level: "trace"
                    }
                    ]
                }
                );
        log.info("Logging system initialized");
        callback();
    }

    connectDB = (initdata : InitData, callback: () => void) : void  =>
    {
        dblog = log.child({module: 'db'});
        if (initdata.config.db.type == "postgres") {
            var sequelize = require('sequelize');
            pgpass({host: this.dbhost,
                    user: this.dbuser}, function (password)
                    {
                        sql = new sequelize(initdata.dbname, initdata.dbuser, password,  {
                            host: initdata.dbhost,
                            dialect: 'postgres',
                            logging: function(data) {
                                dblog.trace(data);
                            }
                        })
                        models = new Models.Models(sql, "postgres");
                        log.info("Sequelize database initialized.")
                        callback();

            });
        } else {
            var sequelize = require('sequelize');
            sql = new sequelize(null, null, null, {
                storage: initdata.config.db.path,
                dialect: 'sqlite',
                logging: function(data) {
                    dblog.trace(data);
                }
            })

            models = new Models.Models(sql, "sqlite");
            log.info("Sequelize database initialized.")
            callback();
        }
    }

    initSessions (initdata: InitData, callback: () => void) : void
    {
        redisclient = redis.createClient();
        callback();
    }

    initMailTransporter (initdata: InitData, callback: () => void) : void
    {
        mailtransport = promise.promisifyAll(
                nodemailer.createTransport(
                {
                    host: 'localhost',
                    port: 25,
                    ignoreTLS: true
                }
            ))
        log.info("Mail transport configured.");
        callback();
    }

    init = (initdata : InitData, callback: (err,res) => void) : void =>
    {
        async.series([
                    function (cb) {initdata.prepareLogs(initdata, cb)},
                    function (cb) {initdata.loadVersion(initdata, cb)},
                    function (cb) {initdata.connectDB(initdata, cb)},
                    function (cb) {initdata.initSessions(initdata, cb)},
                    function (cb) {initdata.initMailTransporter(initdata, cb)},
                    function (err, res)
                    {
                        callback(null, initdata);
                    }
                ]);
    }

    constructor(args: string[]) {
        if (args.length < 1)
            this.config = require('/etc/chezbob.json');
        else
            this.config = require(args[0]);

        this.timeout = 10000;
        this.dbname = this.config.db.name
        this.dbuser = this.config.db.user
        this.dbhost = this.config.db.host
        this.cbemail = "chezbob@cs.ucsd.edu";
        this.sodamap = this.config.sodamap;
        this.mdbendpoint = "http://localhost:8081";
        this.fpendpoint = "http://192.168.1.30:8089";
    }
}

enum log_level
{
    FATAL = 60,
    ERROR = 50,
    WARN = 40,
    INFO = 30,
    DEBUG = 20,
    TRACE = 10
}

//TODO: this needs to be sync'd with client code
enum ClientType {
    Terminal = 0,
    Soda = 1
}

class sodad_server {
    initdata : InitData; //initialization data
    app;
    server;
    clientloggers;
    clientchannels;
    clientmap;
    clientidmap;

    iochannel;

    // balance_transfer : transfer balances from one user to another
    balance_transfer (server: sodad_server, client: string, targetuser:string,
             amt: string)
    {
        redisclient.hget("sodads:" + client, "uid", function (err,uid)
        {
            if (err)
            {
                log.error("Error retrieving for balance transfer on client " + client);
            }
            else
            {
                log.trace("Session resolved to uid " + uid + " on client " + client);
                sql.transaction(function (t)
                {
                    return models.Users.find({ where: { userid: uid }},{ transaction: t })
                        .then(function (user)
                            {
                                if (user)
                                {
                                    log.trace("User found in transaction");
                                    if (parseFloat(user.balance) < parseFloat(amt))
                                    {
                                        throw "Insufficient balance for balance transfer!"
                                    }
                                    if (parseFloat(amt) < 0)
                                    {
                                        throw "Balance transfer must be positive!"
                                    }
                                    return user.updateAttributes(
                                        {
                                            balance: (parseFloat(user.balance) - parseFloat(amt))
                                        }, { transaction: t }
                                        );
                                }
                                throw "User " + uid + " not found!"
                            })
                        .then(function (user_updated)
                            {
                                //add the transaction
                                log.trace("User updated in transaction");
                                return models.Users.find({ where: { username: targetuser}}, { transaction: t })
                                    .then(function(target_found)
                                    {
                                        if (target_found)
                                        {
                                            log.trace("Target user found in transaction");
                                            if (target_found.disabled)
                                            {
                                                throw "Cannot transfer to disabled user!"
                                            }
                                            return target_found.updateAttributes(
                                                {
                                                    balance: (parseFloat(target_found.balance) + parseFloat(amt)),
                                                }, { transaction: t })
                                            .then(function(target_updated)
                                            {
                                                return models.Transactions.create(
                                                {
                                                    userid: uid,
                                                    xactvalue: - amt,
                                                    xacttype: "TRANSFER TO " + target_updated.username,
                                                    barcode: null,
                                                    source: 'bob2k14.2',
                                                    finance_trans_id: null
                                                }, { transaction: t } )
                                            })
                                            .then(function(user_xact)
                                            {
                                                return models.Transactions.create(
                                                {
                                                    userid: target_found.userid,
                                                    xactvalue: amt,
                                                    xacttype: "TRANSFER FROM " + user_updated.username,
                                                    barcode: null,
                                                    source: 'bob2k14.2',
                                                    finance_trans_id: null
                                                }, { transaction: t } )
                                            })
                                            .then(function (target_xact)
                                            {
                                                log.info("Balance transfer transactions successfully inserted for user " + uid + " to " + targetuser + ", client " + client);
                                                server.clientchannels[client].addpurchase({
                                                    name: "Transfer to " + targetuser,
                                                    amount: "-" + amt,
                                                    newbalance: user_updated.balance
                                                })
                                            });
                                        }
                                        throw "Target user " + targetuser + " not found!"
                                    })
                             });
                })
                .catch(function (err)
                {
                    log.error("Error committing transfer transaction for client " + client + ", rolling back: ", err);
                    server.clientchannels[client].displayerror("fa-warning", "Transfer Error", err);
                });
            }
        });
    }

    // balance_transaction : generate a new balance transaction for a user.
    balance_transaction (server: sodad_server, client: string, type: string,
            purchase_description: string, barcode: string, amt: string)
    {
        redisclient.hget("sodads:" + client, "uid", function (err,uid)
        {
            if (err)
            {
                log.error("Error retrieving for balance transaction on client " + client);
            }
            else
            {
                log.trace("Session resolved to uid " + uid + " on client " + client);
                sql.transaction(function (t)
                {
                    return models.Users.find({ where: { userid: uid }},{ transaction: t })
                        .then(function (user)
                            {
                                if (user)
                                {
                                    log.trace("User found in transaction");
                                    return user.updateAttributes(
                                        {
                                            balance: (parseFloat(user.balance) + parseFloat(amt))
                                        }, { transaction: t }
                                        );
                                }
                                throw "User " + uid + " not found!"
                            })
                        .then(function (user_updated)
                            {
                                //add the transaction
                                log.trace("User updated in transaction");
                                return models.Transactions.create(
                                {
                                    userid: uid,
                                    xactvalue: + amt,
                                    xacttype: type,
                                    barcode: barcode,
                                    source: 'bob2k14.2',
                                    finance_trans_id: null
                                }, { transaction: t } )
                                .then(function (new_xact)
                                {
                                    log.info("New balance transaction successfully inserted for user " + uid + ", client " + client);
                                    server.clientchannels[client].addpurchase({
                                        name: purchase_description,
                                        amount: amt,
                                        newbalance: user_updated.balance
                                    })
                                });
                             });
                })
                .catch(function (err)
                {
                    log.error("Error committing transaction for client " + client + ", rolling back: ", err);
                    server.clientchannels[client].displayerror("fa-warning", "Transaction Error", err);
                });
            }
        });
    }

    // transaction_history : get paginated transaction history for user.
    transaction_history (server: sodad_server, client: string, index: number,
            items: number)
    {
        return redisclient.hgetAsync("sodads:" + client, "uid")
                          .then(function (uid)
                                  {
                                    if (uid == null)
                                    { throw "User could not be found from session."; }
                                    return models.Transactions.findAndCountAll({
                                    where: { userid : uid },
                                    order: 'xacttime DESC',
                                    offset: index,
                                    limit: items
                                    })
                                  })
                          .catch(function (e)
                                  {
                                    log.error("Couldn't fetch transaction history " + e);
                                  })
    }

    handle_barcode (server: sodad_server, type: ClientType, num: number, bc_type: string, barcode: string)
    {
        var sessionid;
        if (server.clientmap[type][num] !== undefined )
        {
            sessionid = server.clientidmap[type][num];
            log.trace("Mapping session for " + ClientType[type] + "/" + num + " to " +  server.clientidmap[type][num]);
            redisclient.hgetallAsync("sodads:" + sessionid)
                .then(function (session)
                        {
                                //nobody is logged in
                               return models.Userbarcodes.find( { where: { barcode : barcode }})
                                .then(function(userbarcode)
                                    {
                                        if (userbarcode !== null)
                                        {
                                            return models.Users.find( { where: { userid : userbarcode.userid }})
                                                .then( function (user)
                                                    {
                                                        if (user !== null)
                                                        {
                                                            server.handle_login(server, sessionid, "barcode", user.dataValues);
                                                        }
                                                        else
                                                        {
                                                            throw "ERROR: userbarcode mapped to nonexistent user!";
                                                        }
                                                    })
                                        }
                                        else
                                        {
                                            //maybe it's a product? price check.
                                            var handler = function (products) {
                                                if (products !== null && session === null)
                                                {
                                                    log.trace("Display price for product " + products.name + " due to barcode scan.");
                                                    server.clientchannels[sessionid].displayerror("fa-barcode", "Price Check", products.name + " costs " + products.price);
                                                }
                                                else if (products !== null && session !== null)
                                                {
                                                    log.info("Purchase " + products.name + " using barcode scan.");
                                                    return models.Users.find( { where: { userid : session.uid }})
                                                        .then( function (user)
                                                        {
                                                            // Look up the products again with the dynamic products list
                                                            models.DynamicProducts.find( { where: { barcode: barcode, userid: session.uid }})
                                                                .then( function (products) {
                                                                    var purchase_desc;
                                                                    var purchase_barcode = user.pref_forget_which_product  === "true" ? null : products.barcode;
                                                                    var price = "-" + products.price;
                                                                    if (parseFloat(products.price) < 0) {
                                                                        // For dynamic pricing, we can have 'negative' priced products for, e.g., restocking credit.
                                                                        price = (-1 * parseFloat(products.price)) + "";
                                                                        log.info("Negative price:" + products.price);
                                                                        log.info("Adjusted price:" + price);
                                                                        purchase_desc = "ADD " + products.name;
                                                                    }
                                                                    else {
                                                                        purchase_desc = user.pref_forget_which_product === "true" ? "BUY" : "BUY " + products.name;
                                                                    }
                                                                    log.info("Inserting transaction using price: " + price);
                                                                    server.balance_transaction(server, sessionid, purchase_desc, products.name, purchase_barcode, price);
                                                                })
                                                        });

                                                }
                                                else if (session !== null && session.learn === "true")
                                                {
                                                    //we are trying to learn this barcode
                                                    log.trace("Learning mode on, add learned barcode.")
                                                    models.Userbarcodes.find(
                                                                {
                                                                    where : {
                                                                    barcode: barcode,
                                                                    userid: session.uid}
                                                                }
                                                            ).then(function (exist_barcode) {
                                                                if (exist_barcode !== null)
                                                                {
                                                                    throw "Barcode already learned!"
                                                                }
                                                                return models.Userbarcodes.create(
                                                                    {
                                                                        barcode: barcode,
                                                                        userid: session.uid
                                                                    }
                                                                ).then(function (a)
                                                                    {
                                                                        log.info("Barcode " + barcode + " learned for client " + sessionid);
                                                                        server.clientchannels[sessionid].displayerror("fa-barcode", "Barcode learned", "Barcode " + barcode + " learned");
                                                                        server.clientchannels[sessionid].updatebarcodes();
                                                                    })
                                                            })
                                                            .catch(function (e)
                                                                {
                                                                    log.info("Barcode " + barcode + " NOT learned for client " + sessionid + " due to error: " + e);
                                                                    server.clientchannels[sessionid].displayerror("fa-warning", "Learn failed", "Barcode " + barcode + " already learned by you or another user.");
                                                                })
                                                }
                                                else if (session !== null && session.detail)
                                                {
                                                    //trying to get detailed info about this barcode
                                                }
                                                //default to purchase
                                                else
                                                {
                                                    //no idea what this is.
                                                   log.error("Unknown barcode " + barcode + ", rejecting.")
                                                   server.clientchannels[sessionid].displayerror("fa-warning", "Unknown Barcode", "Unknown barcode " + barcode + ", please scan again.");
                                                }
                                            };
                                            if (session !== null)
                                                return models.DynamicProducts.find(
                                                    { where: { barcode: barcode , userid: session.uid } })
                                                        .then( handler );
                                            else
                                                return models.Products.find(
                                                    { where: { barcode: barcode } })
                                                        .then( handler );
                                        }
                                })
                        })
        }
    }

    //getbarcode: return a list of barcodes registered to the user.
    get_barcodes( server: sodad_server, client: string )
    {
        return redisclient.hgetAsync("sodads:" + client, "uid")
                          .then(function (uid)
                                  {
                                    return models.Userbarcodes.findAll( { where : { userid: uid }})
                                  })
    }

    //forget_barcode: forgets a barcode registered to the user.
    forget_barcode( server: sodad_server, client: string, barcode: string )
    {
        return redisclient.hgetAsync("sodads:" + client, "uid")
                          .then(function (uid)
                                  {
                                    return models.Userbarcodes.find( { where : { userid: uid, barcode: barcode }})
                                        .then(function(result){
                                            if (result === null) {throw "Barcode not registered to user!"}
                                            result.destroy().then(function (deleted)
                                                {
                                                    server.clientchannels[client].displayerror("fa-trash", "Barcode deleted", "Barcode " + barcode + " deleted");
                                                    server.clientchannels[client].updatebarcodes();
                                                })
                                        })
                                  })
    }

    learnmode_barcode( server: sodad_server, client: string, learnmode: boolean)
    {
        return redisclient.hsetAsync("sodads:" + client, "learn", learnmode);
    }

    change_personal_info(server: sodad_server, client: string, nickname: string)
    {
	return redisclient.hgetAsync("sodads:" + client, "uid")
	    .then(uid => {
		return models.Users.find({ where: { userid: uid } });
	    })
	    .then(user => {
		if (user == null) {
		    throw "Couldn't find user";
		}

		return user.updateAttributes({ nickname: nickname });
	    })
	    .then(updated_user => {
		log.info("Successfully updated nickname to " + nickname + " for user " + updated_user.username + " on client " + client);
		server.clientchannels[client].displayerror("fa-check", "Update success", "Personal info updated");
		server.updateuser(server, client);
	    })
	    .catch(error => {
		log.info("Failed to update nickname due to " + error);
		server.clientchannels[client].displayerror("fa-close", "Update failure", "Couldn't update personal info: " + error);
	    });
    }

    changepassword (server: sodad_server, client: string, enabled: boolean,
            newpassword: string, oldpassword: string)
    {
        return redisclient.hgetAsync("sodads:" + client, "uid")
                          .then(function (uid)
                                  {
                                    return models.Users.find( { where : { userid: uid }})
                                        .then(function(result){
                                            if (result === null) {throw "Couldn't find user to change password!"}
                                            else if (!(result.pwd === null || result.pwd === ""))
                                            {
                                                if (crypt(oldpassword, "cB") !== result.pwd)
                                                {
                                                    throw "Old password is incorrect!"
                                                }
                                            }
                                            var newpass = enabled ? crypt(newpassword, "cB") : null;
                                            return result.updateAttributes(
                                                    {
                                                        pwd : newpass
                                                    }).then(function (updated_user)
                                                        {
                                                            log.info("Successfully updated password for user " + updated_user.username + " on client "  + client);
                                                            server.clientchannels[client].displayerror("fa-check", "Update success", "Password settings updated");
                                                            server.updateuser(server, client);
                                                        })
                                            })
                                  })
                        .catch(function (e)
                                {
                                    log.info("Failed to update password due to " + e);
                                    server.clientchannels[client].displayerror("fa-close", "Update failure", "Couldn't update passwords: " + e);
                                })
    }

    cancel_transaction (server: sodad_server, client: string, trans_id : number)
    {
        return redisclient.hgetAsync("sodads:" + client, "uid")
        .then(function (uid){
            if (uid == null)
            { throw "User could not be found from session."; }
            return models.Transactions.find({
                where: { userid : uid, id : trans_id }
            });
        })
        .then(function (xact) {

            var transType = "BUY";
            if(xact.xacttype.substring(0, transType.length) !== transType){
                server.clientchannels[client].displayerror("fa-warning", "Failed to Cancel Transaction", "Can only cancel transactions where you bought something");
                return;
            }

            var amt = xact.xactvalue;
            if(parseFloat(amt) >= 0 || amt[0] != '-') {
                throw "Unexpected transaction amount";
                return;
            }

            //Convert the value of the expenditure to a positive amount
            var restoreAmount = amt.slice(1);
            return redisclient.hgetallAsync("sodads:" + client)
            .then(function(udata) {
                log.info("Cancel transaction from " + udata.username + " id: " + trans_id + " amt: " + restoreAmount);
                var mailOpts = {
                    from: server.initdata.cbemail,
                    to: server.initdata.cbemail,
                    cc: udata.email,
                    subject: '[cb_canceltrans] Transaction ' + trans_id + ' cancelled, user: ' + udata.username + ' amt: ' + restoreAmount,
                    html: 'User ' + udata.username + " cancelled transaction " + trans_id + " for amount :<br/><br/>" + restoreAmount,
                    text: 'User ' + udata.username + " cancelled transaction " + trans_id + " for amount :\n\n" + restoreAmount,
                };
                return mailtransport.sendMailAsync(mailOpts);
            })
            .then(function (response) {
                log.info("Cancelling transaction");
                server.balance_transaction(server, client, "ADD " + restoreAmount + " (cancelled transaction " + trans_id + ")",
                "Deposit " + restoreAmount + " (cancelled transaction " + trans_id + ")", null, restoreAmount);
                server.clientchannels[client].displayerror("fa-check", "Canceled Transaction", "Transaction " + trans_id + " has been canceled. Account has been credited with $" + restoreAmount);
                server.updateuser(server, client);
            });
        })
        .catch(function (e) {
            log.error("Failed to Cancel Transaction " + e);
            server.clientchannels[client].displayerror("fa-warning", "Failed to Cancel Transaction", "Failed to Cancel Transaction");
        });
    }

    //maybe make this a library function
    debunyanize (log: string[], callback: (Object, string) => void)
    {
        var bunyanproc = child_process.spawn('bunyan', ["--color"]);
        bunyanproc.stdout.setEncoding('utf8');
        var bunyanstr = '';
        bunyanproc.stdout.on('data', function(data) {
            bunyanstr += data;
        })
        bunyanproc.stdout.on('close', function(code){
            return callback(null, bunyanstr);
        });
        log.forEach(function (item)
                {
                    var unescaped = S(item).replaceAll('\n', '')
                    bunyanproc.stdin.write(unescaped + "\n");
                })

        //this should close bunyan
        bunyanproc.stdin.end("\x04");
    }
    //maybe this should create a github issue?
    bug_report (server: sodad_server, client: string, report: string)
    {
        return redisclient.hgetallAsync("sodads:" + client)
            .then(function(udata)
                {
                    log.info("User " + udata.username + " submitted a bug report, collecting log.");
                    //collect log.
                    return redisclient.lrangeAsync("cb_log", 0, -1).then(
                        function (lrange)
                        {
                            var debunyanizeAsync = promise.promisify(server.debunyanize, server);
                            return debunyanizeAsync(lrange.slice(0,200)).then(function(ansilog)
                            {
                                var converter = new ansihtml(
                                    {
                                        newline: true,
                                        escapeXML: true,
                                        bg: '#fff',
                                        fg: '#000'
                                    }
                                    );
                                //lrange is an array of log entries.
                                var mailOpts = {
                                    from: server.initdata.cbemail,
                                    to: server.initdata.cbemail,
                                    cc: udata.email,
                                    subject: '[cb_bugreport] Bug report from ' + udata.username,
                                    html: 'User ' + udata.username + " submitted a bug report:<br/><br/>" + report + '<br/><br/> The json log corresponding to this report is attached, and the first 200 log entries follow:<br/<br/>' + converter.toHtml(ansilog),
                                    text: 'User ' + udata.username + " submitted a bug report:\n\n" + report + '\n\n The json log corresponding to this report is attached, and the first 200 log entries follows:\n\n' + stripansi(ansilog),
                                    attachments: [
                                        {
                                            filename: 'log.json',
                                            content: lrange.join('\n')
                                        }
                                    ]
                                };
                                return mailtransport.sendMailAsync(mailOpts).then(function (response)
                                    {
                                        log.info("Bug report successfully e-mailed for user " + udata.username);
                                        server.clientchannels[client].displayerror("fa-check", "Report Submitted", "Thanks for your report! We'll get to squashing this bug soon.");
                                    })
                            })
                        }
                        )
                }
            )
            .catch(function(e)
                    {
                        log.error("Error sending bug report: " + e);
                        server.clientchannels[client].displayerror("fa-close", "Well this is embarassing...", "Could not submit your report - please e-mail chezbob@cs.ucsd.edu. Error: " + e);
                    })
    }

    issue_report (server: sodad_server, client: string, report: string)
    {
        return redisclient.hgetallAsync("sodads:" + client)
            .then(function(udata)
                {
                    log.info("User " + udata.username + " submitted an issue report");
                    var mailOpts = {
                        from: server.initdata.cbemail,
                        to: server.initdata.cbemail,
                        cc: udata.email,
                        subject: '[cb_issuereport] Account issue report from ' + udata.username,
                        html: 'User ' + udata.username + " submitted an issue report:<br/><br/>" + report,
                        text: 'User ' + udata.username + " submitted an issue report:\n\n" + report,
                    };
                    return mailtransport.sendMailAsync(mailOpts).then(function (response)
                        {
                            log.info("Issue report successfully e-mailed for user " + udata.username);
                            server.clientchannels[client].displayerror("fa-check", "Report Submitted", "Thanks for your report! We'll get back to you about your accounts soon.");
                        })
                })
            .catch(function(e)
                    {
                        log.error("Error sending issue report: " + e);
                        server.clientchannels[client].displayerror("fa-close", "Well this is embarassing...", "Could not submit your report - please e-mail chezbob@cs.ucsd.edu. Error: " + e);
                    })
    }

    oos_report (server: sodad_server, client: string, barcode: string)
    {
        return redisclient.hgetallAsync("sodads:" + client)
            .then(function(udata)
                {
                    log.info("User " + udata.username + " submitted an oos report");
                    return models.Products.find({where: {barcode : String(barcode)}}).then(function (product) {
                        var mailOpts = {
                            from: server.initdata.cbemail,
                            to: server.initdata.cbemail,
                            cc: udata.email,
                            subject: '[cb_oos] OOS of ' + product.name,
                            html: 'User ' + udata.username + " submitted an oos report for " + product.name + ", barcode " + product.barcode,
                            text: 'User ' + udata.username + " submitted an oos report for " + product.name + ", barcode " + product.barcode,
                        };
                        return mailtransport.sendMailAsync(mailOpts).then(function (response)
                            {
                                log.info("OOS report successfully e-mailed for user " + udata.username);
                                server.clientchannels[client].displayerror("fa-check", "Report Submitted", "Thanks for your report! Hopefully a restocker will get you more " + product.name + " soon.");
                            })
                    });
                })
            .catch(function(e)
                    {
                        log.error("Error sending oos report: " + e);
                        server.clientchannels[client].displayerror("fa-close", "Well this is embarassing...", "Could not submit your report - please e-mail chezbob@cs.ucsd.edu. Error: " + e);
                    })
    }

    //btw anonymous seems pretty silly since we can figure out who sent via logs???
    comment_report (server: sodad_server, client: string, report: string, anonymous: boolean)
    {
        return redisclient.hgetallAsync("sodads:" + client)
            .then(function(udata)
                {
                    if (!anonymous)
                    {
                        log.info("User " + udata.username + " submitted a comment report");
                    }
                    var cc = anonymous ? null : udata.email;
                    var subject = anonymous ? "[cb_comment] Comment from anonymous" : "[cb_comment] Comment from " + udata.username;
                    var mailOpts = {
                        from: server.initdata.cbemail,
                        to: server.initdata.cbemail,
                        cc: cc,
                        subject: subject,
                        html: 'User submitted an comment report:<br/><br/>' + report,
                        text: 'User submitted an comment report:\n\n' + report
                    };
                    return mailtransport.sendMailAsync(mailOpts).then(function (response)
                        {
                            if (!anonymous)
                            {
                                log.info("Comment report successfully e-mailed for user " + udata.username);
                            }
                            server.clientchannels[client].displayerror("fa-check", "Report Submitted", "Thanks for your comment! We'll look into this as resources permit.");
                        })
                })
            .catch(function(e)
                    {
                        log.error("Error sending comment report: " + e);
                        server.clientchannels[client].displayerror("fa-close", "Well this is embarassing...", "Could not submit your report - please e-mail chezbob@cs.ucsd.edu. Error: " + e);
                    })
    }

    handle_login (server: sodad_server, client: string, source: string, user)
    {
            var multi = redisclient.multi();
            models.Roles.find({ where : { userid: user.userid }})
                .then(function(roles)
                    {
                        multi.hset("sodads:" + client, "uid", user.userid); //TODO: deprecated key uid
                        multi.hmset("sodads:" + client, user)
                        multi.expire("sodads:" + client, 600);

                        user.roles = {};
                        if (roles != null)
                        {
                            S(roles.roles).parseCSV().forEach(function (role) {
                                user.roles[role] = true;
                            });
                            multi.hmset("sodads_roles:" + client, user.roles);
                            multi.expire("sodads_roles:" + client, 600);
                            log.info("User roles loaded: ", user.roles);
                        }

                        return multi.execAsync();
                    })
                .then(function(success)
                    {
                        log.info("Successfully authenticated " + user.username +
                            " (" + source + ") for client " + client);
                        if (user.pwd !== null && user.pwd !== '')
                        {
                            user.pwd = true;
                        }
                        else
                        {
                            user.pwd = false;
                        }
                        user.voice_settings = JSON.parse(user.voice_settings);
                        if (user.voice_settings === undefined || user.voice_settings === null)
                        {
                            user.voice_settings = {};
                        }

                        server.clientchannels[client].login(user, user.balance < 0 ? 'GetAttention' : 'Greeting');

                        // Enable bill acceptance if logged in to the soda machine.
                        // Is this really the best way to determine the client type?
                        if (server.clientidmap[ClientType.Soda][0] == client)
                        {
                            if (user.balance < 0) {
                                server.clientchannels[client].agentSpeak("It looks like you're trying to pay off your balance! Please insert some money!");
                            } else {
                                server.clientchannels[client].agentSpeak("It looks like you're trying to buy some soda! Just press the button for the soda you want!");
                            }

                            var mdb_client = jayson.client.http(server.initdata.mdbendpoint);

                            // Bill acceptor
                            mdb_client.request("Mdb.command", [ "E2" ], function (err,response){});

                            // Coin acceptor
                            mdb_client.request("Mdb.command", [ "E1" ], function (err,response){});

                            // Fingerprint reader
                            var fp_client = jayson.client.http(server.initdata.fpendpoint);
                            fp_client.request("fp.idle", [], function (err, response){});
                        }
                });

    }

    updateuser(server: sodad_server, client: string)
    {
        return redisclient.hgetAsync("sodads:" + client, "uid")
                          .then(function (uid)
                                  {
                                    return models.Users.find( { where : { userid: uid }})
                                        .then(function(result){
                                                var user = result;
                                                user.pwd = (user.pwd === null || user.pwd === '') ? false: true;
                                                user.voice_settings = JSON.parse(user.voice_settings);
                                                server.clientchannels[client].updateuser(user);
                                            })
                                  });
    }

    oos_search (server: sodad_server, client: string, searchstring: string)
    {
        return models.Products.findAll(
                {
                    where: [ "name ILIKE '" + searchstring +"%'" ],
                    limit: 5
                }
                ).then(function (products)
                    {
                        return products;
                    }
                    )
    }

    handle_logout (server: sodad_server, client: string)
    {
        return redisclient.hgetAsync("sodads:" + client, "activevend")
            .then(function(activevend)
                    {
                        if (activevend === "true")
                        {
                            log.warn("Logout cancelled due to active vending session");
                            throw "Active vending session prevents logout!";
                        }
                        else
                        {

                            // Disable bill acceptance if logged in to the soda machine.
                            // Is this really the best way to determine the client type?
                            if (server.clientidmap[ClientType.Soda][0] == client)
                            {
                                var mdb_client = jayson.client.http(server.initdata.mdbendpoint);

                                // Bill acceptor
                                mdb_client.request("Mdb.command", [ "D2" ], function (err,response){});

                                // Coin acceptor
                                mdb_client.request("Mdb.command", [ "D1" ], function (err,response){});

                                // Fingerprint reader
                                var fp_client = jayson.client.http(server.initdata.fpendpoint);
                                fp_client.request("fp.identify", [], function (err, response){});
                            }

                            return redisclient.delAsync("sodads:" + client)
                                            .then(function() {
                                                return redisclient.delAsync("sodads_roles:" + client)
                                            })
                                            .then(function()
                                                  {
                                                    log.info("Logging out session for client " + client);
                                                    server.clientchannels[client].logout();
                                                  })
                        }
                    })
    }

    handleRainRequest(server: sodad_server, client : string)
    {
        var rpc_client = jayson.client.http(server.initdata.mdbendpoint);
        rpc_client.request("Mdb.command", [ "G0204" ], function (err, response){});
        server.balance_transaction(server, client, "WITHDRAW 1.00", "Withdraw 1.00", null, "-1.00");
    }

    handleCoinDeposit(server: sodad_server, client : string, amt: string, tube: string, user)
    {
        if (user !== null)
        {
            log.info("Coin type " + amt + " accepted");
            server.balance_transaction(server, client, "ADD " + amt + " (coin)",
                "Deposit " + amt, null, amt);
        }
        else
        {
            log.warn("Coin type " + amt + " inserted, but no user is logged in, returning...")
            var rpc_client = jayson.client.http(server.initdata.mdbendpoint);
            rpc_client.request("Mdb.command", [ "G" + tube + "01"], function (err,response){});
        }
    }

    handleBillEscrow(server: sodad_server, client : string, amt: string, user)
    {
        if (user !== null)
        {
            log.info("Trying to accept bill type " + amt);
            var rpc_client = jayson.client.http(server.initdata.mdbendpoint);
            rpc_client.request("Mdb.command", [ "K1" ], function (err,response){});
            // After we've sent the request to stack, we need to poll for the
            // actual result.
            rpc_client.request("Mdb.command", [ "P2" ], function (err,response){});

        }
        else
        {
            log.warn("Bill type " + amt + " inserted, but no user is logged in, returning...")
            var rpc_client = jayson.client.http(server.initdata.mdbendpoint);
            rpc_client.request("Mdb.command", [ "K2" ], function (err,response){});
        }
    }

    handleBillStack(server: sodad_server, client : string, amt: string, user)
    {
        if (user !== null)
        {
            log.info("$" + amt + " bill accepted");
            server.balance_transaction(
                server, client, "ADD " + amt + " (cash)", "Deposit $" + amt, null, amt);
        }
        else
        {
            // Once a bill is stacked, it can't be unstacked.
            log.error("Bill type " + amt + " accepted, but no user is logged in.")
        }
    }

    updateVendStock(server: sodad_server, client: string, soda: string, success: boolean)
    {
        return redisclient.hgetAsync("sodad_vendstock", soda).then(function (curstock)
                {
                    // if curstock == null, the current status is unknown,
                    // but if the the vend failed, then we know that we are OOS
                    if (!success)
                    {
                        log.info("Vend FAILED, setting " + soda + " stock to OOS");
                        return redisclient.hsetAsync("sodad_vendstock", soda, 0);
                    }
                    else if (parseInt(curstock) === 0) //note curstock = null will get NaN
                    {
                        log.info("Vend SUCCESS but stock at 0,  setting " + soda + " stock to UNKNOWN");
                        return redisclient.hsetAsync("sodad_vendstock", soda, null);
                    }
                    else if (curstock !== null && curstock !== 'NaN')
                    {
                        var newstock = Math.max(parseInt(curstock) - 1,0);
                        log.info("Vend SUCCESS,  setting " + soda + " stock to " + newstock);
                        return redisclient.hsetAsync("sodad_vendstock", soda, newstock);
                    }
                    else
                    {
                        log.info("Vend status for " + soda + " UNKNOWN, not updating.")
                    }
                })
    }

    updateVendStockLevel(server: sodad_server, client:string, soda:string, newstock:number)
    {
        if (soda === undefined || newstock === undefined)
        {
            throw "Error: Incorrect param!";
        }
        return redisclient.hgetallAsync("sodads_roles:" + client)
            .then(function (user)
            {
                if (user.restocker !== 'true')
                {
                    throw "Error: You need the restocker permission to perform this action!";
                }
            }
            )
            .then(function() {
                redisclient.hsetAsync("sodad_vendstock", soda, newstock)
            })
            .then(function (update){
                server.updateClientVendStock(server, client);
            })
            .then(function(update)
            {
                server.clientchannels[client].displayerror("fa-check", "Update success", "Stock level for col " + soda + " updated!");
            })
            .catch(function (error)
            {
                log.error("Failed to update stock for reason: " + error);
                server.clientchannels[client].displayerror("fa-warn", "Update failure", "Update failed for reason: " + error);
            })

    }

    updateClientVendStock(server: sodad_server, client: string)
    {
        return redisclient.hgetallAsync("sodad_vendstock").then(function (stock)
                {
                    return server.clientchannels[client].updatevendstock(stock);
                });
    }

    handle_fp_identified(server: sodad_server, type: ClientType, num: number, userid: number)
    {
        var sessionid;
        if (server.clientmap[type][num] !== undefined )
        {
            sessionid = server.clientidmap[type][num];
            log.trace("Mapping session for " + ClientType[type] + "/" + num + " to " + server.clientidmap[type][num]);
            redisclient.hgetallAsync("sodads:" + sessionid)
                .then(function (session) {
                    return models.Users.find( { where: { userid : userid }})
                        .then(function (user) {
                            if (user !== null) {
                                server.handle_login(server, sessionid, "fingerprint", user.dataValues);
                            } else {
                                throw "ERROR: fingerprint mapped to nonexistent user!";
                            }
                        })
                });
        }
    }

    get_fingerprints( server: sodad_server, client: string )
    {
        return redisclient.hgetAsync("sodads:" + client, "uid")
            .then(function (uid) {
                     return models.Fingerprints.findAll( { where : { userid: uid }})
        })
    }

    forget_fingerprint( server: sodad_server, client: string, fpid: number )
    {
       return redisclient.hgetAsync("sodads:" + client, "uid")
           .then(function (uid) {
               return models.Fingerprints.find( { where : { userid: uid, fpid: fpid }})
                   .then(function (result) {
                       if (result === null) { throw "Invalid fpid" }
                       result.destroy().then(function (deleted) {
                           server.clientchannels[client].displayerror("fa-trash", "Fingerprint deleted", "Fingerprint data has been deleted");
                           var fp_client = jayson.client.http(server.initdata.fpendpoint);
                           fp_client.request("fp.reload", [], function (err, response){});
                       })
                   })
           })
    }

    check_fp_enroll_capability( server: sodad_server, client: string )
    {
        // For now, only the single soda machine has a fingerprint reader
        return (server.clientidmap[ClientType.Soda][0] == client);
    }

    begin_fp_enrollment( server: sodad_server, client: string )
    {
        if (!server.check_fp_enroll_capability(server, client))
            return false;

        return redisclient.hgetAsync("sodads:" + client, "uid")
            .then(function (uid) {
                var fp_client = jayson.client.http(server.initdata.fpendpoint);
                fp_client.request("fp.enroll", [uid], function (err, response){});
                return true;
        })
    }

    cancel_fp_enrollment( server: sodad_server, client: string )
    {
        if (!server.check_fp_enroll_capability(server, client))
            return false;

        var fp_client = jayson.client.http(server.initdata.fpendpoint);
        fp_client.request("fp.idle", [], function (err, response){});
    }

    savespeech(server: sodad_server, client: string, voice: string, welcome: string, farewell: string)
    {
        return redisclient.hgetAsync("sodads:" + client, "uid")
                    .then(function(uid)
                            {
                                models.Users.find({ where: { userid : uid }})
                                    .then(function (user)
                                        {
                                            if (voice === null)
                                            {
                                                return user.updateAttributes(
                                                    {
                                                        pref_speech : false
                                                    }
                                                    )
                                            }
                                            else
                                            {
                                                var voice_settings : any = {};
                                                voice_settings.voice = voice;
                                                voice_settings.welcome = welcome;
                                                voice_settings.farewell = farewell;
                                                var voice_settings_json = JSON.stringify(voice_settings);
                                                return user.updateAttributes(
                                                    {
                                                        pref_speech : true,
                                                        voice_settings: voice_settings_json
                                                    }
                                                    )
                                            }
                                        })
                                    .then(function(updated_user)
                                            {
                                                server.updateuser(server, client);
                                            })
                            })
    }
    start = () => {
        var server = this;
        var init = server.initdata
        log.info("sodad_server starting, listening on " + init.config.sodad.port);
        this.app = express();

        //configure routes
        this.app.use('/ui', express.static(__dirname + '/ui'));

        this.app.get('/', function (req,res) {
            log.trace("Handling request: ", req);
            res.send("hello world.");
        });

        var jsonserver = jayson.server({
            "Soda.remotebarcode" : function (ctype, id, type, barcode, cb)
            {
                log.trace("Got remote barcode "  + barcode);
                server.handle_barcode(server, ctype, id, type, barcode);
                cb(null);
            },
            "Soda.fp_enroll_progress" : function (ctype, id, result, cb)
            {
                log.trace("Got fingerprint enrollment status " + result + " for " + ClientType[ctype] + "/" + id);
                var sessionid = server.clientidmap[ctype][id];
                server.clientchannels[sessionid].fingerprintEnrollProgress(result);
                cb(null);
            },
            "Soda.fp_identify_result" : function (ctype, id, result, userid, cb)
            {
                log.trace("Got fingerprint identification result " + result + " for " + ClientType[ctype] + "/" + id);
                var sessionid = server.clientidmap[ctype][id];
                switch (result)
                {
                    case 0:
                        server.clientchannels[sessionid].displayerror("fa-warning", "Access Denied", "Sorry, we didn't recognize that fingerprint.");
                        break;
                    case 1:
                        server.handle_fp_identified(server, ctype, id, userid);
                        break;
                    default:
                        server.clientchannels[sessionid].displayerror("fa-warning", "Access Denied", "Please try again.");
                        break;
                }
                cb(null);
            },
            "Soda.vdbauth" : function (requested_soda, cb)
            {
                var sessionid;
                //for now, there is only one client attached to the soda machine.
                var type:ClientType = ClientType.Soda;
                var num: number = 0;
                if (server.clientmap[type][num] !== undefined )
                {
                    sessionid = server.clientidmap[type][num];
                    log.trace("Mapping session for " + ClientType[type] + "/" + num + " to " +  server.clientidmap[type][num]);
                    redisclient.hgetallAsync("sodads:" + sessionid)
                        .then (function (session)
                            {
                                //get requested soda name...
                                var lookup;
                                if (session !== null) {
                                    lookup = models.DynamicProducts.find(
                                        {where: {
                                            barcode: server.initdata.sodamap[requested_soda],
                                            userid: session.uid }})
                                }
                                else {
                                    lookup = models.Products.find(
                                        {where: {
                                            barcode: server.initdata.sodamap[requested_soda] }})
                                }
                                lookup.then(function (sodainfo)
                                    {
                                        if (session === null)
                                        {
                                            log.info ("Vend request for " + requested_soda + " DENIED due to no session");
                                            log.trace("Display price for product " + sodainfo.name + " due to soda button push.");
                                            server.clientchannels[sessionid].displayerror("fa-barcode", "Price Check", sodainfo.name + " costs " + sodainfo.price);
                                            cb(null, false);
                                        }
                                        else
                                        {
                                            log.info("Vend request for " + requested_soda + " AUTHORIZED for user " + session.username);
                                            server.clientchannels[sessionid].displaysoda(requested_soda, sodainfo.name);
                                            redisclient.hsetAsync("sodads:" + sessionid, "activevend", true).then(function ()
                                            {
                                                cb(null, true);
                                            });
                                        }
                                    });
                            }).catch(function (e)
                                {
                                    log.error("Vend request for " + requested_soda + " DENIED due to lookup error " + e);
                                    server.clientchannels[sessionid].displayerror("fa-warning", "Vend DENIED", "Lookup error " + e);
                                    cb(null, false);
                                })
                }
                else
                {
                    log.info("Vend request for " + requested_soda + " DENIED due to no session or socket");
                    cb(null, false); //DENY vend, no one is logged in (and the browser isn't even pointed at this page)
                }
            },
            "Soda.vdbvend" : function (success, requested_soda, cb)
            {
                log.info("Vend result is " + success);
                var sessionid;
                //for now, there is only one client attached to the soda machine.
                var type:ClientType = ClientType.Soda;
                var num: number = 0;
                if (server.clientmap[type][num] !== undefined )
                {
                    sessionid = server.clientidmap[type][num];
                    log.trace("Mapping session for " + ClientType[type] + "/" + num + " to " +  server.clientidmap[type][num]);
                    server.updateVendStock(server, sessionid, requested_soda, success)
                        .then(function() {
                            server.updateClientVendStock(server, sessionid);
                        });
                    redisclient.hgetallAsync("sodads:" + sessionid)
                        .then (function (session)
                            {
                                if (session === null)
                                {
                                    log.error("Vend result=" + success + " for " + requested_soda + " NOT RECORDED due to no session!");
                                    cb(null);
                                }
                                else
                                {
                                        log.info("Vend result=" + success + " for " + requested_soda + " recorded for " + session.username);
                                        redisclient.hsetAsync("sodads:" + sessionid, "activevend", false).then(function ()
                                                    {
                                                        if (success)
                                                        {
                                                        models.DynamicProducts.find({where : {barcode : server.initdata.sodamap[requested_soda], userid: session.uid }})
                                                            .then(function (sodainfo)
                                                            {
                                                                log.info("Purchase " + sodainfo.name + " due to soda vend");
                                                                var purchase_desc = session.pref_forget_which_product === "true" ? "BUY" : "BUY " + sodainfo.name;
                                                                var purchase_barcode = session.pref_forget_which_product === " true" ? null : sodainfo.barcode;
                                                                server.balance_transaction(server, sessionid, purchase_desc,
                                                                 sodainfo.name, purchase_barcode,  "-" + sodainfo.price);
                                                                cb(null);
                                                            })
                                                        }
                                                        else
                                                        {
                                                            log.info("Notifying client and recoding OOS for " + requested_soda);
                                                            server.clientchannels[sessionid].displayerror("fa-warning", "Sold Out", "Sorry, looks like we are sold out. Don't worry, you won't be charged.");
                                                            cb(null);
                                                        }
                                                    });
                                }
                            }).catch(function (e)
                                {
                                    log.error("Vend result=" + success + " for " + requested_soda + " NOT RECORDED due to " + e);
                                    server.clientchannels[sessionid].displayerror("fa-warn", "Vend ERROR", "Lookup error " + e);
                                    cb(null, false);
                                })
                }
                else
                {
                    log.error("Vend result=" + success + " for " + requested_soda + " NOT RECORDED due to no session!");
                    cb(null);
                }
            },
            "Soda.remotemdb": function(command,cb) {
                //TODO: this functionality (parsing commands) should be in MDB server
                log.info("Got MDB command " + command);
                var sessionid;
                //for now, there is only one client attached to the soda machine.
                var type:ClientType = ClientType.Soda;
                var num: number = 0;
                if (server.clientmap[type][num] !== undefined )
                {
                    sessionid = server.clientidmap[type][num];
                    log.trace("Mapping session for " + ClientType[type] + "/" + num + " to " +  server.clientidmap[type][num]);
                    redisclient.hgetallAsync("sodads:" + sessionid).then(function (user) {
                        switch (command)
                        {
                            case "W": //logout
                                if (user !== null)
                                {
                                    log.info("Requesting logout over MDB");
                                    server.handle_logout(server, sessionid);
                                }
                                else
                                {
                                    log.info("Requested logout but no one is logged in!");
                                    server.clientchannels[sessionid].displayerror("fa-warn", "Not logged in!", "No one is logged in!");
                                }
                                break;
                            case "P1 00":
                                server.handleCoinDeposit(server, sessionid, "0.05", "00", user);
                                break;
                            case "P1 01":
                                server.handleCoinDeposit(server, sessionid, "0.10", "01", user);
                                break;
                            case "P1 02":
                                server.handleCoinDeposit(server, sessionid, "0.25", "02", user);
                                break;
                            case "P1 03":
                                server.handleCoinDeposit(server, sessionid, "1.00", "03", user);
                                break;
                            case "Q1 00":
                                server.handleBillEscrow(server, sessionid, "1.00", user);
                                break;
                            case "Q1 01":
                                server.handleBillEscrow(server, sessionid, "5.00", user);
                                break;
                            case "Q1 02":
                                server.handleBillEscrow(server, sessionid, "10.00", user);
                                break;
                            case "Q1 03":
                                server.handleBillEscrow(server, sessionid, "20.00", user);
                                break;
                            case "Q1 04":
                                server.handleBillEscrow(server, sessionid, "50.00", user);
                                break;
                            case "Q1 05":
                                server.handleBillEscrow(server, sessionid, "100.00", user);
                                break;
                            case "Q2 00":
                                server.handleBillStack(
                                    server, sessionid, "1.00", user);
                                break;
                            case "Q2 01":
                                server.handleBillStack(
                                    server, sessionid, "5.00", user);
                                break;
                            case "Q2 02":
                                server.handleBillStack(
                                    server, sessionid, "10.00", user);
                                break;
                            case "Q2 03":
                                server.handleBillStack(
                                    server, sessionid, "20.00", user);
                                break;
                            case "Q2 04":
                                server.handleBillStack(
                                    server, sessionid, "50.00", user);
                                break;
                            case "Q2 05":
                                server.handleBillStack(
                                    server, sessionid, "100.00", user);
                                break;
                            default:
                                log.error("Unknown MDB command: " + command);
                        }
                    }).catch(
                            log.error("MDB command couldn't get session data!")
                        )
                }
                else
                {
                    log.error("MDB command " + command + " ignored due to NO SESSION!");
                }
                //command always succeeds.
                cb(null);
            }
        });

        this.app.use('/api', bodyparser.json());
        this.app.use('/api', jsonserver.middleware());
        this.server = this.app.listen(init.config.sodad.port, function() {

        });

        this.clientchannels = {};
        this.clientmap = {};
        this.clientmap[ClientType.Terminal] = {};
        this.clientmap[ClientType.Soda] = {};
        this.clientidmap = {};
        this.clientidmap[ClientType.Terminal] = {};
        this.clientidmap[ClientType.Soda] = {};

        this.iochannel = io.listen(this.server);
        rpc.createServer(this.iochannel, this.app);
        rpc.expose('serverChannel',{
            log: function(level: log_level, data)
            {
                var clog = log.child({module: 'client', id: this.id});
                switch(level)
                {
                    case log_level.TRACE:
                        clog.trace(data);
                        break;
                    case log_level.DEBUG:
                        clog.debug(data);
                        break;
                    case log_level.INFO:
                        clog.info(data);
                        break;
                    case log_level.WARN:
                        clog.warn(data);
                        break;
                    case log_level.ERROR:
                        clog.error(data);
                        break;
                    case log_level.FATAL:
                        clog.fatal(data);
                }
            },
            barcodestats: function(barcode)
            {
                return models.Transactions.count( { where:  { barcode : barcode } } );
            },
            barcode: function(barcode)
            {
                var deferred = promise.defer();
                models.Products.find(barcode)
                    .then(function(entry)
                            {
                                deferred.resolve(entry.dataValues);
                            })
                return deferred.promise;
            },
            logout: function()
            {
                var client = this.id;
                server.handle_logout(server, client);
            },
            manualpurchase: function(amt)
            {
                var client = this.id;
                log.info("Manual purchase of " + amt + " for client " + client);
                server.balance_transaction(server, client, "BUY OTHER",
                        "Manual Purchase", null, "-" + amt);
            },
            manualdeposit: function(amt)
            {
                var client = this.id;
                log.info("Manual deposit of " + amt + " for client " + client);
                server.balance_transaction(server, client, "ADD MANUAL",
                        "Manual Deposit", null,  amt);
            },
            rain: function()
            {
                var client = this.id;
                server.handleRainRequest(server, client);
            },
            transfer: function(amt, user)
            {
                var client = this.id;
                log.info("Balance transfer of " + amt + " to " + user + " for client " + client);
                server.balance_transfer(server, client, user, amt);
            },
            transactionhistory: function(index, count)
            {
                var client = this.id;
                log.info("Transaction history request for index " + index + ", count " + count + " for client " + client);
                return server.transaction_history(server, client, index, count);
            },
            get_barcodes: function()
            {
                var client = this.id;
                log.info("Getting barcodes registered for client " + client);
                return server.get_barcodes(server, client);
            },
            forget_barcode: function(barcode)
            {
                var client = this.id;
                log.info("Forget barcode requested for client "  + client);
                return server.forget_barcode(server, client, barcode);
            },
            learnmode_barcode: function(mode)
            {
                var client = this.id;
                log.info("Setting learn mode to " + mode  + " for client " + client);
                return server.learnmode_barcode(server, client, mode);
            },
            get_fingerprints: function()
            {
                var client = this.id;
                log.info("Getting fingerprints registered for client " + client);
                return server.get_fingerprints(server, client);
            },
            forget_fingerprint: function(fpid)
            {
                var client = this.id;
                log.info("Forgetting fingerprint " + fpid + " for client " + client);
                return server.forget_fingerprint(server, client, fpid)
            },
            check_fp_enroll_capability: function()
            {
                var client = this.id;
                log.info("Checking fingerprint enrollment capability for client " + client);
                return server.check_fp_enroll_capability(server, client);
            },
            begin_fp_enrollment: function()
            {
                var client = this.id;
                log.info("Beginning fingerprint enrollment for client " + client);
                return server.begin_fp_enrollment(server, client);
            },
            cancel_fp_enrollment: function()
            {
                var client = this.id;
                log.info("Cancelling fingerprint enrollment for client " + client);
                return server.cancel_fp_enrollment(server, client);
            },
            bug_report: function(report)
            {
                var client = this.id;
                log.info("Submitting a bug report for client " + client);
                return server.bug_report(server, client, report);
            },
            issue_report: function(report)
            {
                var client = this.id;
                log.info("Submitting an issue report for client " + client);
                return server.issue_report(server, client, report);
            },
            comment_report: function(anonymous, report)
            {
                var client = this.id;
                log.info("Submitting an comment report for client " + client);
                return server.comment_report(server, client, report, anonymous);
            },
	    change_personal_info: function(nickname)
	    {
	        var client = this.id;
		log.info("Changing nickname to " + nickname + " for client " + client);
		return server.change_personal_info(server, client, nickname);
	    },
            changepassword: function(enable, newpassword, oldpassword)
            {
                var client = this.id;
                log.info("Setting password (enabled=" + enable + ") for client " + client);
                return server.changepassword(server, client, enable, newpassword, oldpassword);
            },
            cancel_transaction:function(trans_id)
            {
                var client = this.id;
                log.info("Cancellng transaction for client " + client);
                return server.cancel_transaction(server, client, trans_id);
            },
            vendstock: function()
            {
                var client = this.id;
                log.info("Getting vend stock levels for client " + client);
                return server.updateClientVendStock(server, client);
            },
            updatevendstock: function(col, level)
            {
                var client = this.id;
                log.info("Updating vend stock levels for client " + client);
                return server.updateVendStockLevel(server, client, col, level);
            },
            oos_search: function(searchphrase)
            {
                var client = this.id;
                log.info("Executing OOS search for " + searchphrase + " for client " + client);
                return server.oos_search(server, client, searchphrase);
            },
            oos_report: function(barcode)
            {
                var client = this.id;
                log.info("Submitting an OOS report for barcode " + barcode + " for client " + client);
                return server.oos_report(server, client, barcode);
            },
            savespeech: function (voice, greeting, farewell)
            {
                var client = this.id;
                log.info("Saving speech settings, voice=" + voice + " for client " + client);
                return server.savespeech(server, client, voice, greeting, farewell);
            },
            authenticate: function(user, password)
            {
                var deferred = promise.defer();
                var client = this.id;
                models.Users.find(
                        {
                            where: {
                                username: user.toLowerCase()
                            }
                        })
                            .then(function (entry)
                            {
                                if (entry == null) {
                                    log.warn("Couldn't find user " + user + " for client " + client);
                                    server.clientchannels[client].displayerror("fa-warning", "User not found", "Login for account " + user + " not found.");
                                }
                                else
                                {
                                    var luser = entry.dataValues;
                                    if (luser.disabled)
                                    {
                                        log.warn("Disabled user " + user + " attempted login from client " + client);
                                        server.clientchannels[client].displayerror("fa-times-circle", "Login Disabled", "Login for account " + user + " is disabled. Please contact ChezBob staff for more details.");
                                    }
                                    else if ((luser.pwd == null && password == "") || (luser.pwd === "" && password == ""))
                                    {
                                        server.handle_login(server, client, "no pass", luser);
                                    }
                                    else
                                    {
                                        if(crypt(password, "cB") === luser.pwd)
                                        {
                                            server.handle_login(server, client, "password", luser);
                                        }
                                        else
                                        {
                                            log.error("PASSWORD =", luser.pwd);
                                            log.warn("Authentication failure (user= " + user + ")for client " + client);
                                            server.clientchannels[client].displayerror("fa-times-circle", "Login Denied", "Login for account " + user + " denied. Incorrect password was entered.");
                                        }
                                    }
                                }

                            deferred.resolve(true);
                            }
                            ).catch(function (err) {
                                if (err) { log.error(err); }
                            });
                return deferred.promise;
            }
        });

        this.iochannel.sockets.on('connection', function (server: sodad_server){
        return function(socket)
        {
            rpc.loadClientChannel(socket, 'clientChannel').then(function (fns)
                {
                    server.clientchannels[socket.id] = fns;
                    fns.gettype().then(function (typedata){
                        server.clientmap[typedata.type][typedata.id] = fns;
                        server.clientidmap[typedata.type][typedata.id] = socket.id;

                        log.info("Registered client channel type (" + ClientType[typedata.type] + "/"
                            + typedata.id + ") for client " + socket.id);
                        return fns.getversion().then(function(version)
                        {
                            if (version !== server.initdata.longVersion)
                            {
                                log.warn("Client version (" + version + ") different from server version + (" +server.initdata.longVersion + "), reloading");
                                fns.reload();
                            }
                            else
                            {
                                log.trace("Client version " + version);
                            }
                        }).catch(function (err)
                            {
                                log.warn("Error getting client version (probably really old), forcing reload");
                                fns.reload();
                            });
                    });
                }
                )
        }} (this));

        this.iochannel.sockets.on('disconnect', function (server: sodad_server){
            return function(socket)
            {
                delete server.clientchannels[socket.id];
                log.info("Deregistered client channel for client " + socket.id);
            }
        })
    }

    constructor(initdata : InitData) {
        this.initdata = initdata;
    }
}
export class App {
    private initdata : InitData;

    main(args: string[])
    {
        this.initdata = new InitData(args);
        this.initdata.init(this.initdata,
                function (err, res: InitData)
                {
                    var sodad = new sodad_server(res);
                    sodad.start();
                }
                );
    }

    constructor () {}
}
