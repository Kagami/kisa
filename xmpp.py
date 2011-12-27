from twisted.python import log
from twisted.internet import reactor, task
from twisted.words.xish import domish
from twisted.words.protocols.jabber import xmlstream, client, jid


def log_data_in(buf):
    log.msg("RECV: %r" % buf)

def log_data_out(buf):
    log.msg("SEND: %r" % buf)


class ChatModeBot(object):

    def __init__(self, bot_jid, password, jid_to, text, interval,
                 db, verbose=False):
        self._jid = bot_jid
        self._jid_to = jid_to
        self._msg = domish.Element((None, "message"))
        self._msg["to"] = jid_to
        self._msg["type"] = "chat"
        self._msg.addElement("body", content=text)
        self._interval = interval
        self._db = db
        self._verbose = verbose
        jid_obj = jid.JID(bot_jid + "/nyaknyak")
        self._factory = client.XMPPClientFactory(jid_obj, password)
        self._factory.continueTrying = 0
        self._factory.clientConnectionFailed = self._connection_failed
        self._factory.addBootstrap(xmlstream.STREAM_AUTHD_EVENT, self._authd)
        self._factory.addBootstrap(xmlstream.INIT_FAILED_EVENT, self._failed)
        reactor.connectTCP(jid_obj.host, 5222, self._factory, timeout=5)

    def _authd(self, xmlstream):
        if self._verbose:
            xmlstream.rawDataInFn = log_data_in
            xmlstream.rawDataOutFn = log_data_out
        # Init presence.
        xmlstream.send(domish.Element((None, "presence")))
        # Subscribe request.
        prs = domish.Element((None, "presence"))
        prs["to"] = self._jid_to
        prs["type"] = "subscribe"
        xmlstream.send(prs)
        # Message send loop.
        task.LoopingCall(xmlstream.send, self._msg).start(self._interval)

    def _connection_failed(self, connector, failure):
        self._failed(failure)

    def _failed(self, failure):
        self._db.del_account(self._jid)
