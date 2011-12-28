import random
from twisted.python import log
from twisted.internet import defer, reactor


def sleep(seconds):
    """Asynchronous sleep."""
    d = defer.Deferred()
    reactor.callLater(seconds, d.callback, None)
    return d


chars = [chr(i) for i in xrange(ord("a"), ord("z") + 1)] +\
        [str(i) for i in xrange(0, 10)]

def generate_username():
    """Simple random. Maybe be more complex in future."""
    username = ""
    for i in xrange(20):
        username += random.choice(chars)
    return username

def generate_password():
    password = ""
    for i in xrange(20):
        password += random.choice(chars)
    return password


def log_data_in(buf):
    log.msg("RECV: %r" % buf)

def log_data_out(buf):
    log.msg("SEND: %r" % buf)
