#   Copyright (c) 2005-2007 Open Source Applications Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

"""
SSL/TLS.

@var  trusted_until_shutdown_site_certs:         Certificates that should be
                                                 trusted until program exit.
                                                 The certificates are in PEM
                                                 format (str).
@type trusted_until_shutdown_site_certs:         list
@var  trusted_until_shutdown_invalid_site_certs: Ignore SSL errors with these
                                                 certificates until program
                                                 exit. The key is the
                                                 certificate in PEM format (str)
                                                 and the value is a list of the
                                                 errors to ignore.
@type trusted_until_shutdown_invalid_site_certs: dict
@var  unknown_issuer:                            Certificate verification error
                                                 codes in this list signal that
                                                 the certificate has been
                                                 issued by unknown authority
                                                 and that we should probably
                                                 ask the user if they would
                                                 like to trust this certificate.
@type unknown_issuer:                            list
"""

from __future__ import with_statement
import logging
import threading

import wx
import M2Crypto
import M2Crypto.m2 as m2
import M2Crypto.SSL as SSL
import M2Crypto.SSL.TwistedProtocolWrapper as wrapper
import M2Crypto.SSL.Checker as Checker
import M2Crypto.X509 as X509
import twisted
import twisted.protocols.policies as policies
from i18n import ChandlerMessageFactory as _

from application import schema, Utility
from osaf.framework.certstore import constants, utils
from osaf.framework.twisted import runInUIThread
from osaf import messages
from chandlerdb.persistence.RepositoryView import otherViewWins


__all__ = ['loadCertificatesToContext', 'SSLContextError', 'getContext',
           'connectSSL', 'connectTCP', 'unknown_issuer',
           'trusted_until_shutdown_site_certs',
           'trusted_until_shutdown_invalid_site_certs',
           'askTrustServerCertificate',
           'askIgnoreSSLError', 'certificateCache']

log = logging.getLogger(__name__)

certificateCache = []

_sslLock = threading.Lock()

def _getSSLView(repo):
    """
    Return the SSL view for this repository, creating one if necessary.
    This function is internal to this module. Also, it is advisable to take
    out _sslLock when accessing or changing the returned view, or any of
    its Items.
    
    @param repo: The repository whose SSL view we want to return
    @type repo: L{chandlerdb.persistence.DBRepository.DBRepository}
    
    @return: A repository view with name 'SSL'
    @rtype: L{chandlerdb.persistence.DBRepositoryView.DBRepositoryView}
    """
    with _sslLock:
        for view in repo.views:
            if view.name == 'SSL':
                return view
        
        return repo.createView('SSL', pruneSize=400, notify=False,
                               mergeFn=otherViewWins)


def loadCertificatesToContext(repView, ctx):
    """
    Add certificates to SSL Context.
    
    @param repView: repository view
    @param ctx:     M2Crypto.SSL.Context
    """
    sslView = _getSSLView(repView.repository)
    store = ctx.get_cert_store()
    
    with _sslLock:
        if certificateCache:
            for x509 in certificateCache:
                store.add_x509(x509)
        else:
            sslView.refresh()
            q = schema.ns('osaf.framework.certstore', sslView).sslCertificateQuery
            for cert in q:
                x509 = cert.asX509()
                store.add_x509(x509)
                certificateCache.append(x509)

class SSLContextError(utils.CertificateException):
    """
    Raised when an SSL Context could not be created. Currently happens
    only when cipher list cannot be set.
    """


def getContext(repositoryView, protocol='sslv23', verify=True,
               verifyCallback=None):
    """
    Get an SSL context. You should use this method to get a context
    in Chandler rather than creating them directly.

    @param repositoryView: Repository View from which to get certificates.
    @type repositoryView:  RepositoryView
    @param protocol:       An SSL protocol version string.
    @type protocol:        str
    @param verify:         Verify SSL/TLS connection. True by default.
    @type verify:          boolean
    @param verifyCallback: Function to call for certificate verification.
    @type verifyCallback:  Callback function
    """
    ctx = SSL.Context(protocol)

    # XXX Sometimes we might want to accept any cert, and only use
    #     sslPostConnectionCheck. Need an extra arg in calling func.

    # XXX We might want to accept any cert, and store it among with info
    #     who the other user is, and if at any time in the future these
    #     don't match, alert the user (vulnerable in first connection)
    #     Need to expand API.

    if verify:
        loadCertificatesToContext(repositoryView, ctx)
        
        # XXX TODO In some cases, for example when connecting directly
        #          to P2P partner, we want to authenticate mutually using
        #          certificates so we need to load the "me" certificate.
        #          Do not do this for all contexts, however, because it can
        #          leak our identity when connecting to random SSL servers
        #          out there.
        #ctx.load_cert_chain('client.pem')

        ctx.set_verify(SSL.verify_peer | SSL.verify_fail_if_no_peer_cert,
                       9, verifyCallback)

    # Do not allow SSLv2 because it has security issues
    ctx.set_options(SSL.op_all | SSL.op_no_sslv2)

    # Disable unsafe ciphers, and order the remaining so that strongest
    # comes first, which can help peers select the strongest common
    # cipher.
    if ctx.set_cipher_list('ALL:!ADH:!LOW:!EXP:!MD5:@STRENGTH') != 1:
        log.error('Could not set cipher list')
        raise SSLContextError(_(u'Could not set cipher list'))

    return ctx


class ContextFactory(object):
    """
    This is internal class to this module and should not be used outside.
    """
    def __init__(self, repositoryView, protocol='sslv23', verify=True,
                 verifyCallback=None):
        self.repositoryView = repositoryView
        self.protocol = protocol
        self.verify = verify
        self.verifyCallback = verifyCallback

    def getContext(self):
        return getContext(self.repositoryView, self.protocol, self.verify,
                          self.verifyCallback)

trusted_until_shutdown_site_certs = []
trusted_until_shutdown_invalid_site_certs = {}

# These errors will happen when
# the certificate can't be verified because we don't have
# the issuing certificate.
unknown_issuer = [m2.X509_V_ERR_DEPTH_ZERO_SELF_SIGNED_CERT,
                  m2.X509_V_ERR_SELF_SIGNED_CERT_IN_CHAIN,
                  m2.X509_V_ERR_UNABLE_TO_GET_ISSUER_CERT_LOCALLY,
                  m2.X509_V_ERR_CERT_UNTRUSTED,
                  m2.X509_V_ERR_UNABLE_TO_VERIFY_LEAF_SIGNATURE]


class TwistedProtocolWrapper(wrapper.TLSProtocolWrapper):
    """
    This is internal class to this module and should not be used outside.
    """
    def __init__(self, repositoryView, protocol, factory, wrappedProtocol, 
                 startPassThrough, client):

        if __debug__:
            log.debug('TwistedProtocolWrapper.__init__')

        repositoryView = _getSSLView(repositoryView.repository)
            
        self.contextFactory = ContextFactory(repositoryView, protocol, 
                                            verifyCallback=self.verifyCallback)
        wrapper.TLSProtocolWrapper.__init__(self, factory, wrappedProtocol, 
                                            startPassThrough, client,
                                            self.contextFactory,
                                            self.postConnectionVerify)
        self.repositoryView = repositoryView
        # List for now, even though only first might be needed:
        self.untrustedCertificates = []

    def verifyCallback(self, ok, store):
        # Returning 1 means any error is ignored and SSL checking continues
        if __debug__:
            log.debug('TwistedProtocolWrapper.verifyCallback')
        global trusted_until_shutdown_site_certs, \
               trusted_until_shutdown_invalid_site_certs, \
               unknown_issuer
                        
        if not ok:
            try:
                with _sslLock:
                    err = store.get_error()
        
                    # This would actually give us the certificate we are currently
                    # checking: 
                    #
                    #pem = store.get_current_cert().as_pem()
                    #
                    # However, we want to ask the user what to do about
                    # the actual server certificate, not the other certs in the
                    # chain. While this makes it a little annoying for experts
                    # (we say there was a problem in the chain, and show only the
                    # server cert which itself may have no problems), it makes it
                    # slightly safer because if the users decide to ignore the
                    # error, they ignore only the server certificate errors. If
                    # we showed the CA certificate, the user could accidentally
                    # ok any certificates issued by the bad CA. Now they will
                    # at least be faced with the warning dialog for each actual
                    # server certificate.
                    stack = store.get1_chain()
                    x509 = stack[0]
                    pem = x509.as_pem()
        
                    # Check temporarily trusted certificates
                    if err not in unknown_issuer:
                        # Check if we are temporarily ignoring errors with this
                        # certificate.
                        acceptedErrList = trusted_until_shutdown_invalid_site_certs.get(pem)
                        if acceptedErrList is not None and err in acceptedErrList:
                            if __debug__:
                                log.debug('Ignoring certificate error %d' %err)
                            return 1
                        self.untrustedCertificates.append(pem)
                        return ok
        
                    if pem in trusted_until_shutdown_site_certs:
                        if __debug__:
                            log.debug('Found temporarily trusted site cert')
                        return 1
        
                    # Check permanently trusted certificates
                    self.repositoryView.refresh()
                    q = schema.ns('osaf.framework.certstore', 
                                  self.repositoryView).sslTrustedServerCertificatesQuery
                    for cert in q:
                        if cert.pemAsString() == pem:
                            if __debug__:
                                log.debug('Found permanently trusted site cert')
                            return 1
        
                    self.untrustedCertificates.append(pem)
            except: # This is ok, we MUST return a value and not raise
                log.exception('SSL verifyCallback raised exception')
        if __debug__:
            log.debug('Returning %d' % ok)
        return ok

    def dataReceived(self, data):
        if __debug__:
            log.debug('TwistedProtocolWrapper.dataReceived')

        utils.entropyInitialized = True
        try:
            wrapper.TLSProtocolWrapper.dataReceived(self, data)
        except M2Crypto.BIO.BIOError, e:
            if self.isClient:
                host = self.transport.addr[0]
            else:
                host = self.transport.getPeer().host

            if e.args[1] == 'certificate verify failed':
                raise Utility.CertificateVerificationError(host,
                                                           e.args[0], e.args[1],
                                                           self.untrustedCertificates)
            raise


    def postConnectionVerify(self, peerX509, expectedHost):
        #Do a post connection check on an SSL connection. This is done just
        #after the SSL connection has been established, but before exchanging
        #any real application data like username and password.
        #
        #This implementation checks to make sure that the certificate that the
        #peer presented was issued for the host we tried to connect to, or in
        #other words, make sure that we are talking to the server we think we
        #should be talking to.
        #
        # TODO: We should report ALL errors from this post connection check
        #       so that users will only get one dialog, even if there are
        #       several errors. Obviously we need to record all errors in
        #       verifyCallback first.
        check = Checker.Checker()
        try:
            return check(peerX509, expectedHost)
        except Checker.WrongHost, e:
            e.pem = peerX509.as_pem()
    
            acceptedErrList = trusted_until_shutdown_invalid_site_certs.get(e.pem)
            err = messages.SSL_HOST_MISMATCH % {'actualHost': e.actualHost}
            if acceptedErrList is not None and err in acceptedErrList:
                if __debug__:
                    log.debug('Ignoring post connection error %s' % err)
                return 1
    
            raise e


def connectSSL(host, port, factory, repositoryView, 
               protocol='sslv23',
               timeout=30,
               bindAddress=None,
               reactor=twisted.internet.reactor):
    """
    A convenience function to start an SSL/TLS connection using Twisted.
    
    See IReactorSSL interface in Twisted. 
    """
    if __debug__:
        log.debug('connectSSL(host=%s, port=%d)' %(host, port))

    wrappingFactory = policies.WrappingFactory(factory)
    wrappingFactory.protocol = lambda factory, wrappedProtocol: \
        TwistedProtocolWrapper(repositoryView,
                               protocol,
                               factory,
                               wrappedProtocol,
                               startPassThrough=0,
                               client=1)
    return reactor.connectTCP(host, port, wrappingFactory, timeout,
                              bindAddress)
    

def connectTCP(host, port, factory, repositoryView, 
               protocol='tlsv1',
               timeout=30,
               bindAddress=None,
               reactor=twisted.internet.reactor):
    """
    A convenience function to start a TCP connection using Twisted.
    
    NOTE: You must call startTLS(ctx) to go into SSL/TLS mode.
    
    See IReactorSSL interface in Twisted. 
    """
    if __debug__:
        log.debug('connectTCP(host=%s, port=%d)' %(host, port))

    wrappingFactory = policies.WrappingFactory(factory)
    wrappingFactory.protocol = lambda factory, wrappedProtocol: \
        TwistedProtocolWrapper(repositoryView,
                               protocol,
                               factory,
                               wrappedProtocol,
                               startPassThrough=1,
                               client=1)
    return reactor.connectTCP(host, port, wrappingFactory, timeout,
                              bindAddress)    

@runInUIThread
def askTrustServerCertificate(host, pem, reconnect):
    """
    Ask user if they would like to trust the certificate that was returned by
    the server. This will only happen if the certificate is not already
    trusted, either by trust chain or explicitly.

    @note: If you want to reconnect on background thread, pass in a dummy
           reconnect and reconnect manually after receiving True.
    
    @param host:      The host we think we are connected with.
    @param pem:       The certificate in PEM format.
    @param reconnect: The reconnect callback that will be called if the
                      user chooses to trust the certificate.
    @return:          True if user chose to trust, False otherwise.
    """
    from osaf.framework.certstore import dialogs, certificate
    global trusted_until_shutdown_site_certs

    repositoryView = wx.GetApp().UIRepositoryView
    x509 = X509.load_cert_string(pem)
    untrustedCertificate = certificate.findCertificate(repositoryView, pem)
    dlg = dialogs.TrustServerCertificateDialog(wx.GetApp().mainFrame,
                                               x509,
                                               host,
                                               untrustedCertificate)
    try:
        if dlg.ShowModal() == wx.ID_OK:
            selection = dlg.GetSelection()

            if selection == 0:
                trusted_until_shutdown_site_certs += [pem]
            else:
                if untrustedCertificate is not None:
                    untrustedCertificate.trust |= constants.TRUST_AUTHENTICITY
                else:
                    fingerprint = utils.fingerprint(x509)
                    certificate.importCertificate(x509, fingerprint,
                                       constants.TRUST_AUTHENTICITY,
                                       repositoryView)
                # In either case here (a known, untrusted cert, or a
                # completely untrusted cert), we have made a change
                # and we need to commit so other views can see it.
                repositoryView.commit()
            
            reconnect()

            return True
    finally:
        dlg.Destroy()

    return False


@runInUIThread
def askIgnoreSSLError(host, pem, err, reconnect):
    """
    Ask user if they would like to ignore an error with the SSL connection,
    and if so, reconnect automatically.
    
    Strictly speaking we should not ask and just fail. In practice that
    wouldn't be very helpful because there are lots of misconfigured servers
    out there.
    
    @note: If you want to reconnect on background thread, pass in a dummy
           reconnect and reconnect manually after receiving True.
    
    @param host:      The host we think we are connected with.
    @param pem:       The certificate with which we noticed the error (the
                      error could be in the certificate itself, or it could be
                      a mismatch between the certificate and the server).
    @param err:       Error.
    @param reconnect: The reconnect callback that will be called if the used
                      chooses to ignore the error.
    @return:          True if user chose to ignore, False otherwise.
    """
    from osaf.framework.certstore import dialogs
    x509 = X509.load_cert_string(pem)
    dlg = dialogs.IgnoreSSLErrorDialog(wx.GetApp().mainFrame,
                                       x509,
                                       host,
                                       err)
    try:
        if dlg.ShowModal() == wx.ID_OK:
            acceptedErrList = trusted_until_shutdown_invalid_site_certs.setdefault(pem, [])
            acceptedErrList.append(err)
            reconnect()
            
            return True
    finally:
        dlg.Destroy()

    return False
