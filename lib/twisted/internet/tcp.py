# -*- test-case-name: twisted.test.test_tcp -*-
# Copyright (c) Twisted Matrix Laboratories.
# See LICENSE for details.

"""
Various asynchronous TCP/IP classes.

End users shouldn't use this module directly - use the reactor APIs instead.
"""


# System Imports
import types
import socket
import sys
import operator
import struct

from zope.interface import implements

from twisted.python.runtime import platformType
from twisted.python import versions, deprecate

try:
    # Try to get the memory BIO based startTLS implementation, available since
    # pyOpenSSL 0.10
    from twisted.internet._newtls import (
        ConnectionMixin as _TLSConnectionMixin,
        ClientMixin as _TLSClientMixin,
        ServerMixin as _TLSServerMixin)
except ImportError:
    try:
        # Try to get the socket BIO based startTLS implementation, available in
        # all pyOpenSSL versions
        from twisted.internet._oldtls import (
            ConnectionMixin as _TLSConnectionMixin,
            ClientMixin as _TLSClientMixin,
            ServerMixin as _TLSServerMixin)
    except ImportError:
        # There is no version of startTLS available
        class _TLSConnectionMixin(object):
            TLS = False
        class _TLSClientMixin(object):
            pass
        class _TLSServerMixin(object):
            pass

if platformType == 'win32':
    # no such thing as WSAEPERM or error code 10001 according to winsock.h or MSDN
    EPERM = object()
    from errno import WSAEINVAL as EINVAL
    from errno import WSAEWOULDBLOCK as EWOULDBLOCK
    from errno import WSAEINPROGRESS as EINPROGRESS
    from errno import WSAEALREADY as EALREADY
    from errno import WSAECONNRESET as ECONNRESET
    from errno import WSAEISCONN as EISCONN
    from errno import WSAENOTCONN as ENOTCONN
    from errno import WSAEINTR as EINTR
    from errno import WSAENOBUFS as ENOBUFS
    from errno import WSAEMFILE as EMFILE
    # No such thing as WSAENFILE, either.
    ENFILE = object()
    # Nor ENOMEM
    ENOMEM = object()
    EAGAIN = EWOULDBLOCK
    from errno import WSAECONNRESET as ECONNABORTED

    from twisted.python.win32 import formatError as strerror
else:
    from errno import EPERM
    from errno import EINVAL
    from errno import EWOULDBLOCK
    from errno import EINPROGRESS
    from errno import EALREADY
    from errno import ECONNRESET
    from errno import EISCONN
    from errno import ENOTCONN
    from errno import EINTR
    from errno import ENOBUFS
    from errno import EMFILE
    from errno import ENFILE
    from errno import ENOMEM
    from errno import EAGAIN
    from errno import ECONNABORTED

    from os import strerror

from errno import errorcode

# Twisted Imports
from twisted.internet import base, address, fdesc
from twisted.internet.task import deferLater
from twisted.python import log, failure, reflect
from twisted.python.util import unsignedID
from twisted.internet.error import CannotListenError
from twisted.internet import abstract, main, interfaces, error



class _SocketCloser(object):
    _socketShutdownMethod = 'shutdown'

    def _closeSocket(self, orderly):
        # The call to shutdown() before close() isn't really necessary, because
        # we set FD_CLOEXEC now, which will ensure this is the only process
        # holding the FD, thus ensuring close() really will shutdown the TCP
        # socket. However, do it anyways, just to be safe.
        skt = self.socket
        try:
            if orderly:
                getattr(skt, self._socketShutdownMethod)(2)
            else:
                # Set SO_LINGER to 1,0 which, by convention, causes a
                # connection reset to be sent when close is called,
                # instead of the standard FIN shutdown sequence.
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                       struct.pack("ii", 1, 0))

        except socket.error:
            pass
        try:
            skt.close()
        except socket.error:
            pass



class _AbortingMixin(object):
    """
    Common implementation of C{abortConnection}.

    @ivar _aborting: Set to C{True} when C{abortConnection} is called.
    @type _aborting: C{bool}
    """
    _aborting = False

    def abortConnection(self):
        """
        Aborts the connection immediately, dropping any buffered data.

        @since: 11.1
        """
        if self.disconnected or self._aborting:
            return
        self._aborting = True
        self.stopReading()
        self.stopWriting()
        self.doRead = lambda *args, **kwargs: None
        self.doWrite = lambda *args, **kwargs: None
        self.reactor.callLater(0, self.connectionLost,
                               failure.Failure(error.ConnectionAborted()))



class Connection(_TLSConnectionMixin, abstract.FileDescriptor, _SocketCloser,
                 _AbortingMixin):
    """
    Superclass of all socket-based FileDescriptors.

    This is an abstract superclass of all objects which represent a TCP/IP
    connection based socket.

    @ivar logstr: prefix used when logging events related to this connection.
    @type logstr: C{str}
    """
    implements(interfaces.ITCPTransport, interfaces.ISystemHandle)


    def __init__(self, skt, protocol, reactor=None):
        abstract.FileDescriptor.__init__(self, reactor=reactor)
        self.socket = skt
        self.socket.setblocking(0)
        self.fileno = skt.fileno
        self.protocol = protocol


    def getHandle(self):
        """Return the socket for this connection."""
        return self.socket


    def doRead(self):
        """Calls self.protocol.dataReceived with all available data.

        This reads up to self.bufferSize bytes of data from its socket, then
        calls self.dataReceived(data) to process it.  If the connection is not
        lost through an error in the physical recv(), this function will return
        the result of the dataReceived call.
        """
        try:
            data = self.socket.recv(self.bufferSize)
        except socket.error, se:
            if se.args[0] == EWOULDBLOCK:
                return
            else:
                return main.CONNECTION_LOST
        if not data:
            return main.CONNECTION_DONE
        rval = self.protocol.dataReceived(data)
        if rval is not None:
            offender = self.protocol.dataReceived
            warningFormat = (
                'Returning a value other than None from %(fqpn)s is '
                'deprecated since %(version)s.')
            warningString = deprecate.getDeprecationWarningString(
                offender, versions.Version('Twisted', 11, 0, 0),
                format=warningFormat)
            deprecate.warnAboutFunction(offender, warningString)
        return rval


    def writeSomeData(self, data):
        """
        Write as much as possible of the given data to this TCP connection.

        This sends up to C{self.SEND_LIMIT} bytes from C{data}.  If the
        connection is lost, an exception is returned.  Otherwise, the number
        of bytes successfully written is returned.
        """
        try:
            # Limit length of buffer to try to send, because some OSes are too
            # stupid to do so themselves (ahem windows)
            return self.socket.send(buffer(data, 0, self.SEND_LIMIT))
        except socket.error, se:
            if se.args[0] == EINTR:
                return self.writeSomeData(data)
            elif se.args[0] in (EWOULDBLOCK, ENOBUFS):
                return 0
            else:
                return main.CONNECTION_LOST


    def _closeWriteConnection(self):
        try:
            getattr(self.socket, self._socketShutdownMethod)(1)
        except socket.error:
            pass
        p = interfaces.IHalfCloseableProtocol(self.protocol, None)
        if p:
            try:
                p.writeConnectionLost()
            except:
                f = failure.Failure()
                log.err()
                self.connectionLost(f)


    def readConnectionLost(self, reason):
        p = interfaces.IHalfCloseableProtocol(self.protocol, None)
        if p:
            try:
                p.readConnectionLost()
            except:
                log.err()
                self.connectionLost(failure.Failure())
        else:
            self.connectionLost(reason)



    def connectionLost(self, reason):
        """See abstract.FileDescriptor.connectionLost().
        """
        # Make sure we're not called twice, which can happen e.g. if
        # abortConnection() is called from protocol's dataReceived and then
        # code immediately after throws an exception that reaches the
        # reactor. We can't rely on "disconnected" attribute for this check
        # since twisted.internet._oldtls does evil things to it:
        if not hasattr(self, "socket"):
            return
        abstract.FileDescriptor.connectionLost(self, reason)
        self._closeSocket(not reason.check(error.ConnectionAborted))
        protocol = self.protocol
        del self.protocol
        del self.socket
        del self.fileno
        protocol.connectionLost(reason)


    logstr = "Uninitialized"

    def logPrefix(self):
        """Return the prefix to log with when I own the logging thread.
        """
        return self.logstr

    def getTcpNoDelay(self):
        return operator.truth(self.socket.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY))

    def setTcpNoDelay(self, enabled):
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, enabled)

    def getTcpKeepAlive(self):
        return operator.truth(self.socket.getsockopt(socket.SOL_SOCKET,
                                                     socket.SO_KEEPALIVE))

    def setTcpKeepAlive(self, enabled):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, enabled)



class BaseClient(_TLSClientMixin, Connection):
    """
    A base class for client TCP (and similiar) sockets.
    """
    _base = Connection

    addressFamily = socket.AF_INET
    socketType = socket.SOCK_STREAM

    def _finishInit(self, whenDone, skt, error, reactor):
        """
        Called by base classes to continue to next stage of initialization.
        """
        if whenDone:
            Connection.__init__(self, skt, None, reactor)
            self.doWrite = self.doConnect
            self.doRead = self.doConnect
            reactor.callLater(0, whenDone)
        else:
            reactor.callLater(0, self.failIfNotConnected, error)

    def stopConnecting(self):
        """Stop attempt to connect."""
        self.failIfNotConnected(error.UserError())

    def failIfNotConnected(self, err):
        """
        Generic method called when the attemps to connect failed. It basically
        cleans everything it can: call connectionFailed, stop read and write,
        delete socket related members.
        """
        if (self.connected or self.disconnected or
            not hasattr(self, "connector")):
            return

        self.connector.connectionFailed(failure.Failure(err))
        if hasattr(self, "reactor"):
            # this doesn't happen if we failed in __init__
            self.stopReading()
            self.stopWriting()
            del self.connector

        try:
            self._closeSocket(True)
        except AttributeError:
            pass
        else:
            del self.socket, self.fileno

    def createInternetSocket(self):
        """(internal) Create a non-blocking socket using
        self.addressFamily, self.socketType.
        """
        s = socket.socket(self.addressFamily, self.socketType)
        s.setblocking(0)
        fdesc._setCloseOnExec(s.fileno())
        return s

    def resolveAddress(self):
        if abstract.isIPAddress(self.addr[0]):
            self._setRealAddress(self.addr[0])
        else:
            d = self.reactor.resolve(self.addr[0])
            d.addCallbacks(self._setRealAddress, self.failIfNotConnected)

    def _setRealAddress(self, address):
        self.realAddress = (address, self.addr[1])
        self.doConnect()

    def doConnect(self):
        """I connect the socket.

        Then, call the protocol's makeConnection, and start waiting for data.
        """
        if not hasattr(self, "connector"):
            # this happens when connection failed but doConnect
            # was scheduled via a callLater in self._finishInit
            return

        err = self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if err:
            self.failIfNotConnected(error.getConnectError((err, strerror(err))))
            return


        # doConnect gets called twice.  The first time we actually need to
        # start the connection attempt.  The second time we don't really
        # want to (SO_ERROR above will have taken care of any errors, and if
        # it reported none, the mere fact that doConnect was called again is
        # sufficient to indicate that the connection has succeeded), but it
        # is not /particularly/ detrimental to do so.  This should get
        # cleaned up some day, though.
        try:
            connectResult = self.socket.connect_ex(self.realAddress)
        except socket.error, se:
            connectResult = se.args[0]
        if connectResult:
            if connectResult == EISCONN:
                pass
            # on Windows EINVAL means sometimes that we should keep trying:
            # http://msdn.microsoft.com/library/default.asp?url=/library/en-us/winsock/winsock/connect_2.asp
            elif ((connectResult in (EWOULDBLOCK, EINPROGRESS, EALREADY)) or
                  (connectResult == EINVAL and platformType == "win32")):
                self.startReading()
                self.startWriting()
                return
            else:
                self.failIfNotConnected(error.getConnectError((connectResult, strerror(connectResult))))
                return

        # If I have reached this point without raising or returning, that means
        # that the socket is connected.
        del self.doWrite
        del self.doRead
        # we first stop and then start, to reset any references to the old doRead
        self.stopReading()
        self.stopWriting()
        self._connectDone()

    def _connectDone(self):
        self.protocol = self.connector.buildProtocol(self.getPeer())
        self.connected = 1
        logPrefix = self._getLogPrefix(self.protocol)
        self.logstr = "%s,client" % logPrefix
        self.startReading()
        self.protocol.makeConnection(self)

    def connectionLost(self, reason):
        if not self.connected:
            self.failIfNotConnected(error.ConnectError(string=reason))
        else:
            Connection.connectionLost(self, reason)
            self.connector.connectionLost(reason)


class Client(BaseClient):
    """A TCP client."""

    def __init__(self, host, port, bindAddress, connector, reactor=None):
        # BaseClient.__init__ is invoked later
        self.connector = connector
        self.addr = (host, port)

        whenDone = self.resolveAddress
        err = None
        skt = None

        try:
            skt = self.createInternetSocket()
        except socket.error, se:
            err = error.ConnectBindError(se.args[0], se.args[1])
            whenDone = None
        if whenDone and bindAddress is not None:
            try:
                skt.bind(bindAddress)
            except socket.error, se:
                err = error.ConnectBindError(se.args[0], se.args[1])
                whenDone = None
        self._finishInit(whenDone, skt, err, reactor)

    def getHost(self):
        """Returns an IPv4Address.

        This indicates the address from which I am connecting.
        """
        return address.IPv4Address('TCP', *self.socket.getsockname())

    def getPeer(self):
        """Returns an IPv4Address.

        This indicates the address that I am connected to.
        """
        return address.IPv4Address('TCP', *self.realAddress)

    def __repr__(self):
        s = '<%s to %s at %x>' % (self.__class__, self.addr, unsignedID(self))
        return s


class Server(_TLSServerMixin, Connection):
    """
    Serverside socket-stream connection class.

    This is a serverside network connection transport; a socket which came from
    an accept() on a server.

    @ivar _base: L{Connection}, which is the base class of this class which has
        all of the useful file descriptor methods.  This is used by
        L{_TLSServerMixin} to call the right methods to directly manipulate the
        transport, as is necessary for writing TLS-encrypted bytes (whereas
        those methods on L{Server} will go through another layer of TLS if it
        has been enabled).
    """
    _base = Connection

    def __init__(self, sock, protocol, client, server, sessionno, reactor):
        """
        Server(sock, protocol, client, server, sessionno)

        Initialize it with a socket, a protocol, a descriptor for my peer (a
        tuple of host, port describing the other end of the connection), an
        instance of Port, and a session number.
        """
        Connection.__init__(self, sock, protocol, reactor)
        self.server = server
        self.client = client
        self.sessionno = sessionno
        self.hostname = client[0]

        logPrefix = self._getLogPrefix(self.protocol)
        self.logstr = "%s,%s,%s" % (logPrefix,
                                    sessionno,
                                    self.hostname)
        self.repstr = "<%s #%s on %s>" % (self.protocol.__class__.__name__,
                                          self.sessionno,
                                          self.server._realPortNumber)
        self.startReading()
        self.connected = 1

    def __repr__(self):
        """A string representation of this connection.
        """
        return self.repstr

    def getHost(self):
        """Returns an IPv4Address.

        This indicates the server's address.
        """
        return address.IPv4Address('TCP', *self.socket.getsockname())

    def getPeer(self):
        """Returns an IPv4Address.

        This indicates the client's address.
        """
        return address.IPv4Address('TCP', *self.client)



class Port(base.BasePort, _SocketCloser):
    """
    A TCP server port, listening for connections.

    When a connection is accepted, this will call a factory's buildProtocol
    with the incoming address as an argument, according to the specification
    described in L{twisted.internet.interfaces.IProtocolFactory}.

    If you wish to change the sort of transport that will be used, the
    C{transport} attribute will be called with the signature expected for
    C{Server.__init__}, so it can be replaced.

    @ivar deferred: a deferred created when L{stopListening} is called, and
        that will fire when connection is lost. This is not to be used it
        directly: prefer the deferred returned by L{stopListening} instead.
    @type deferred: L{defer.Deferred}

    @ivar disconnecting: flag indicating that the L{stopListening} method has
        been called and that no connections should be accepted anymore.
    @type disconnecting: C{bool}

    @ivar connected: flag set once the listen has successfully been called on
        the socket.
    @type connected: C{bool}

    @ivar _type: A string describing the connections which will be created by
        this port.  Normally this is C{"TCP"}, since this is a TCP port, but
        when the TLS implementation re-uses this class it overrides the value
        with C{"TLS"}.  Only used for logging.
    """

    implements(interfaces.IListeningPort)

    addressFamily = socket.AF_INET
    socketType = socket.SOCK_STREAM

    transport = Server
    sessionno = 0
    interface = ''
    backlog = 50

    _type = 'TCP'

    # Actual port number being listened on, only set to a non-None
    # value when we are actually listening.
    _realPortNumber = None

    def __init__(self, port, factory, backlog=50, interface='', reactor=None):
        """Initialize with a numeric port to listen on.
        """
        base.BasePort.__init__(self, reactor=reactor)
        self.port = port
        self.factory = factory
        self.backlog = backlog
        self.interface = interface

    def __repr__(self):
        if self._realPortNumber is not None:
            return "<%s of %s on %s>" % (self.__class__, self.factory.__class__,
                                         self._realPortNumber)
        else:
            return "<%s of %s (not listening)>" % (self.__class__, self.factory.__class__)

    def createInternetSocket(self):
        s = base.BasePort.createInternetSocket(self)
        if platformType == "posix" and sys.platform != "cygwin":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s


    def startListening(self):
        """Create and bind my socket, and begin listening on it.

        This is called on unserialization, and must be called after creating a
        server to begin listening on the specified port.
        """
        try:
            skt = self.createInternetSocket()
            skt.bind((self.interface, self.port))
        except socket.error, le:
            raise CannotListenError, (self.interface, self.port, le)

        # Make sure that if we listened on port 0, we update that to
        # reflect what the OS actually assigned us.
        self._realPortNumber = skt.getsockname()[1]

        log.msg("%s starting on %s" % (
                self._getLogPrefix(self.factory), self._realPortNumber))

        # The order of the next 6 lines is kind of bizarre.  If no one
        # can explain it, perhaps we should re-arrange them.
        self.factory.doStart()
        skt.listen(self.backlog)
        self.connected = True
        self.socket = skt
        self.fileno = self.socket.fileno
        self.numberAccepts = 100

        self.startReading()


    def _buildAddr(self, (host, port)):
        return address._ServerFactoryIPv4Address('TCP', host, port)


    def doRead(self):
        """Called when my socket is ready for reading.

        This accepts a connection and calls self.protocol() to handle the
        wire-level protocol.
        """
        try:
            if platformType == "posix":
                numAccepts = self.numberAccepts
            else:
                # win32 event loop breaks if we do more than one accept()
                # in an iteration of the event loop.
                numAccepts = 1
            for i in range(numAccepts):
                # we need this so we can deal with a factory's buildProtocol
                # calling our loseConnection
                if self.disconnecting:
                    return
                try:
                    skt, addr = self.socket.accept()
                except socket.error, e:
                    if e.args[0] in (EWOULDBLOCK, EAGAIN):
                        self.numberAccepts = i
                        break
                    elif e.args[0] == EPERM:
                        # Netfilter on Linux may have rejected the
                        # connection, but we get told to try to accept()
                        # anyway.
                        continue
                    elif e.args[0] in (EMFILE, ENOBUFS, ENFILE, ENOMEM, ECONNABORTED):

                        # Linux gives EMFILE when a process is not allowed
                        # to allocate any more file descriptors.  *BSD and
                        # Win32 give (WSA)ENOBUFS.  Linux can also give
                        # ENFILE if the system is out of inodes, or ENOMEM
                        # if there is insufficient memory to allocate a new
                        # dentry.  ECONNABORTED is documented as possible on
                        # both Linux and Windows, but it is not clear
                        # whether there are actually any circumstances under
                        # which it can happen (one might expect it to be
                        # possible if a client sends a FIN or RST after the
                        # server sends a SYN|ACK but before application code
                        # calls accept(2), however at least on Linux this
                        # _seems_ to be short-circuited by syncookies.

                        log.msg("Could not accept new connection (%s)" % (
                            errorcode[e.args[0]],))
                        break
                    raise

                fdesc._setCloseOnExec(skt.fileno())
                protocol = self.factory.buildProtocol(self._buildAddr(addr))
                if protocol is None:
                    skt.close()
                    continue
                s = self.sessionno
                self.sessionno = s+1
                transport = self.transport(skt, protocol, addr, self, s, self.reactor)
                protocol.makeConnection(transport)
            else:
                self.numberAccepts = self.numberAccepts+20
        except:
            # Note that in TLS mode, this will possibly catch SSL.Errors
            # raised by self.socket.accept()
            #
            # There is no "except SSL.Error:" above because SSL may be
            # None if there is no SSL support.  In any case, all the
            # "except SSL.Error:" suite would probably do is log.deferr()
            # and return, so handling it here works just as well.
            log.deferr()

    def loseConnection(self, connDone=failure.Failure(main.CONNECTION_DONE)):
        """
        Stop accepting connections on this port.

        This will shut down the socket and call self.connectionLost().  It
        returns a deferred which will fire successfully when the port is
        actually closed, or with a failure if an error occurs shutting down.
        """
        self.disconnecting = True
        self.stopReading()
        if self.connected:
            self.deferred = deferLater(
                self.reactor, 0, self.connectionLost, connDone)
            return self.deferred

    stopListening = loseConnection

    def _logConnectionLostMsg(self):
        """
        Log message for closing port
        """
        log.msg('(%s Port %s Closed)' % (self._type, self._realPortNumber))


    def connectionLost(self, reason):
        """
        Cleans up the socket.
        """
        self._logConnectionLostMsg()
        self._realPortNumber = None

        base.BasePort.connectionLost(self, reason)
        self.connected = False
        self._closeSocket(True)
        del self.socket
        del self.fileno

        try:
            self.factory.doStop()
        finally:
            self.disconnecting = False


    def logPrefix(self):
        """Returns the name of my class, to prefix log entries with.
        """
        return reflect.qual(self.factory.__class__)

    def getHost(self):
        """Returns an IPv4Address.

        This indicates the server's address.
        """
        return address.IPv4Address('TCP', *self.socket.getsockname())

class Connector(base.BaseConnector):
    def __init__(self, host, port, factory, timeout, bindAddress, reactor=None):
        self.host = host
        if isinstance(port, types.StringTypes):
            try:
                port = socket.getservbyname(port, 'tcp')
            except socket.error, e:
                raise error.ServiceNameUnknownError(string="%s (%r)" % (e, port))
        self.port = port
        self.bindAddress = bindAddress
        base.BaseConnector.__init__(self, factory, timeout, reactor)

    def _makeTransport(self):
        return Client(self.host, self.port, self.bindAddress, self, self.reactor)

    def getDestination(self):
        return address.IPv4Address('TCP', self.host, self.port)
