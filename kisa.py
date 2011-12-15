#!/usr/bin/env python

__license__ = "Public Domain"
__version__ = "0.0.1"

import sys
import os.path
try:
    import twisted.words
except ImportError:
    path = os.path.join(os.path.dirname(__file__), "lib")
    sys.path.insert(0, path)
import signal
import random
import optparse
from twisted.python import log
try:
    from twisted.internet import epollreactor
    epollreactor.install()
except:
    pass
from twisted.internet import defer, reactor
from database import db
import xmpp


program_name = os.path.basename(__file__)
parser = optparse.OptionParser(version=__version__)
try:
    import config
except ImportError:
    pass
else:
    parser.set_defaults(
        verbose=config.verbose, mode=config.mode, bot_count=config.bot_count,
        jid=config.jid.encode("utf-8"), text=config.text.encode("utf-8"))
parser.add_option("-v", "--verbose", action="store_true",
                  help="print additional debug info")
parser.add_option("-q", "--quiet", dest="verbose", action="store_false",
                  help="be quiet")
parser.add_option("-m", "--mode", choices=("chat",),
                  help="set mode: chat")
group = optparse.OptionGroup(parser, "chat mode options")
group.add_option("-c", "--bot-count", type="int",
                 help="number of bots running in parallel")
group.add_option("-j", "--jid", help="destination jid")
group.add_option("-t", "--text")
parser.add_option_group(group)
(options, args) = parser.parse_args()
if args:
    parser.error("unknown options; see `%s --help' "
                 "for details" % program_name)
if options.verbose:
    log.startLogging(sys.stdout)


@defer.inlineCallbacks
def start_chat_mode():
    accounts = yield db.get_all_accounts()
    if not accounts:
        print "No accounts in the database, exiting."
        reactor.stop()
        return
    if len(accounts) > options.bot_count:
        accounts = random.sample(accounts, options.bot_count)
    print "Starting test using %d accounts." % len(accounts)
    for jid, password in accounts:
        xmpp.ChatModeBot(
            jid, password,
            options.jid.decode("utf-8"), options.text.decode("utf-8"),
            options.verbose)


if options.mode == "chat":
    reactor.callWhenRunning(start_chat_mode)
reactor.run()
