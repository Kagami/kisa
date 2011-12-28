from twisted.words.xish import domish
from twisted.words.xish.xmlstream import STREAM_CONNECTED_EVENT
from twisted.words.protocols.jabber import xmlstream, client, jid
from twisted.internet import reactor, task
import utils


class ChatBot(object):

    def __init__(self, bot_jid, password, jid_to, text, interval,
                 db, verbose=0):
        self._jid = bot_jid
        self._jid_to = jid_to
        self._msg = domish.Element((None, "message"))
        self._msg["to"] = jid_to
        self._msg["type"] = "chat"
        self._msg.addElement("body", content=text)
        self._interval = interval
        self._db = db
        self._verbose = verbose
        jid_obj = jid.JID(bot_jid)
        # TODO: Remove CheckVersionInitializer?
        factory = client.XMPPClientFactory(jid_obj, password)
        factory.maxRetries = 0
        factory.clientConnectionFailed = self._failed
        factory.addBootstrap(STREAM_CONNECTED_EVENT, self._connected)
        factory.addBootstrap(xmlstream.STREAM_AUTHD_EVENT, self._authd)
        factory.addBootstrap(xmlstream.INIT_FAILED_EVENT, self._failed)
        reactor.connectTCP(jid_obj.host, 5222, factory, timeout=10)

    def _connected(self, xs):
        if self._verbose > 1:
            xs.rawDataInFn = utils.log_data_in
            xs.rawDataOutFn = utils.log_data_out

    def _authd(self, xs):
        # Init presence.
        xs.send(domish.Element((None, "presence")))
        # Subscribe request.
        prs = domish.Element((None, "presence"))
        prs["to"] = self._jid_to
        prs["type"] = "subscribe"
        xs.send(prs)
        # Message send loop.
        task.LoopingCall(xs.send, self._msg).start(self._interval)

    def _failed(self, arg1, arg2=None):
        failure = arg1 if arg2 is None else arg2
        print "Deleting bad account", self._jid,
        if self._verbose:
            print failure
        else:
            print
        self._db.del_account(self._jid)
