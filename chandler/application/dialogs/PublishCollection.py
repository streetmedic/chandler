import os
import wx
import wx.xrc
import application.Globals
import osaf.mail.message
import osaf.mail.sharing
import application.dialogs.Util
import osaf.framework.sharing.Sharing

class PublishCollectionDialog(wx.Dialog):
    def __init__(self, parent, resources, collection):
        pre = wx.PreDialog()
        self.resources = resources
        resources.LoadOnDialog(pre, parent, 'PublishCollectionDialog')
        self.this = pre.this
        self.parent = parent
        self.collection = collection

        self.urlLabel = wx.xrc.XRCCTRL(self, "ID_URL_LABEL")
        self.urlLabel.SetLabel("Publish collection '%s' to:" % \
         collection.displayName)

        self.urlText = wx.xrc.XRCCTRL(self, "ID_URL")
        if osaf.framework.sharing.Sharing.isShared(collection):
            self.urlText.SetValue("%s" % collection.sharedURL)
        else:
            path = osaf.framework.sharing.Sharing.getWebDavPath()
            if path:
                self.urlText.SetValue("%s/%s" % (path, collection.itsUUID))
            else:
                self.urlText.SetValue("http://server/path/%s" % \
                 collection.itsUUID)

        self.inviteesText = wx.xrc.XRCCTRL(self, "ID_INVITEES")

        self.waitLabel = wx.xrc.XRCCTRL(self, "ID_WAIT")
        self.OkButton = wx.xrc.XRCCTRL(self, "OK_BUTTON")
        self.CancelButton = wx.xrc.XRCCTRL(self, "CANCEL_BUTTON")

        # This is the new style of event binding used as of wxWidgets 2.5.1
        self.Bind(wx.EVT_BUTTON, self.OnOk,
         id=wx.xrc.XRCID("OK_BUTTON"))
        self.Bind(wx.EVT_BUTTON, self.OnCancel,
         id=wx.xrc.XRCID("CANCEL_BUTTON"))

        #wx.EVT_BUTTON( self, wx.xrc.XRCID( "OK_BUTTON" ), self.OnOk )
        #wx.EVT_BUTTON( self, wx.xrc.XRCID( "CANCEL_BUTTON" ), self.OnCancel )

    def OnOk(self, evt):
        self.waitLabel.SetLabel("")

        # validate email addresses
        invitees = self.inviteesText.GetValue()
        if invitees:
            invitees = invitees.split(",")
            badAddresses = []

            for invitee in invitees:
                if not osaf.mail.message.isValidEmailAddress(invitee):
                    badAddresses.append(invitee)

            size = len(badAddresses)

            if size > 0:
                a = size > 1 and "addresses" or "address"
                self.waitLabel.SetLabel("Invalid %s: %s" % \
                 (a, ', '.join(badAddresses)))
                return

        url = self.urlText.GetValue()
        self.waitLabel.SetLabel("Publishing, Please Wait...")

        osaf.framework.webdav.Dav.DAV(url).put(self.collection)

        if invitees:
            osaf.mail.sharing.sendInvitation(url, self.collection.displayName,
             invitees)

        self.EndModal(True)

    def OnCancel(self, evt):
        self.EndModal(False)

def ShowPublishCollectionsDialog(parent, collection):
        xrcFile = os.path.join(application.Globals.chandlerDirectory,
         'application', 'dialogs', 'PublishCollection_wdr.xrc')
        resources = wx.xrc.XmlResource(xrcFile)
        win = PublishCollectionDialog(parent, resources, collection)
        win.CenterOnScreen()
        val = win.ShowModal()
        win.Destroy()
