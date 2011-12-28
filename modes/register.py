from twisted.words.xish.xmlstream import STREAM_CONNECTED_EVENT
from twisted.words.protocols.jabber import xmlstream, client, jid
from twisted.internet import defer, reactor
import utils


class RegisterBot(object):

    def __init__(self, verbose=0):
        self._verbose = verbose
        self._deferred = defer.Deferred()

    def register_account(self, server):
        reactor.callLater(10, self._failed, "timeout")
        username = utils.generate_username()
        self._jid = "%s@%s" % (username, server)
        self._password = utils.generate_password()
        jid_obj = jid.JID(self._jid)
        if self._verbose:
            print "Connecting to", jid_obj.host
        a = RegisterAuthenticator(jid_obj, self._password)
        factory = xmlstream.XmlStreamFactory(a)
        factory.maxRetries = 0
        factory.clientConnectionFailed = self._failed
        factory.addBootstrap(STREAM_CONNECTED_EVENT, self._connected)
        factory.addBootstrap(xmlstream.INIT_FAILED_EVENT, self._failed)
        factory.addBootstrap(RegisterInitializer.REGISTER_SUCCEEDED_EVENT,
                             self._registered)
        factory.addBootstrap(RegisterInitializer.REGISTER_FAILED_EVENT,
                             self._failed)
        reactor.connectTCP(jid_obj.host, 5222, factory, timeout=4)
        return self._deferred

    def _connected(self, xs):
        if self._verbose > 1:
            xs.rawDataInFn = utils.log_data_in
            xs.rawDataOutFn = utils.log_data_out

    def _failed(self, arg1, arg2=None):
        if self._deferred.called:
            return
        failure = arg1 if arg2 is None else arg2
        if type(failure) is int:
            error = failure
            failure = "error code = " + str(error)
        else:
            error = 1
        if self._verbose:
            print "Failed to register %s: %s" % (self._jid, failure)
        self._deferred.errback(RegisterError(error))

    def _registered(self, _):
        if self._deferred.called:
            return
        print "%s:%s registered." % (self._jid, self._password)
        self._deferred.callback((self._jid, self._password))


class RegisterError(Exception): pass


class RegisterAuthenticator(xmlstream.ConnectAuthenticator):

    namespace = "jabber:client"

    def __init__(self, jid_obj, password):
        xmlstream.ConnectAuthenticator.__init__(self, jid_obj.host)
        self._jid_obj = jid_obj
        self._password = password

    def associateWithStream(self, xs):
        xmlstream.ConnectAuthenticator.associateWithStream(self, xs)
        xs.initializers = [
            xmlstream.TLSInitiatingInitializer(xs),
            RegisterInitializer(xs, self._jid_obj, self._password),
        ]


class RegisterInitializer(object):

    REGISTER_SUCCEEDED_EVENT = "//event/client/register/succeeded"
    REGISTER_FAILED_EVENT = "//event/client/register/failed"

    def __init__(self, xs, jid_obj, password):
        self._xs = xs
        self._jid_obj = jid_obj
        self._password = password

    def initialize(self):
        iq = client.IQ(self._xs, "set")
        iq.addElement(("jabber:iq:register", "query"))
        iq.query.addElement("username", content=self._jid_obj.user)
        iq.query.addElement("password", content=self._password)
        iq.addCallback(self._registerResultEvent)
        iq.send()

    def _registerResultEvent(self, iq):
        if iq["type"] == "result":
            self._xs.dispatch(None, self.REGISTER_SUCCEEDED_EVENT)
        else:
            try:
                error = int(iq.error.getAttribute("code", 2))
            except AttributeError:
                error = 2
            self._xs.dispatch(error, self.REGISTER_FAILED_EVENT)
        self._xs.transport.loseConnection()
