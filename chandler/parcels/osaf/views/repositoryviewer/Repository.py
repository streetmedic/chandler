""" Classes used by the repository view
"""

__version__ = "$Revision$"
__date__ = "$Date$"
__copyright__ = "Copyright (c) 2004 Open Source Applications Foundation"
__license__ = "http://osafoundation.org/Chandler_0.1_license_terms.htm"

import wx
import osaf.framework.blocks.ControlBlocks as ControlBlocks

class RepositoryDelegate (ControlBlocks.ListDelegate):
    """ Used by the tree in the repository view
    """
    
    def GetElementParent(self, element):
        return element.itsParent

    def GetElementChildren(self, element):
        if element:
            return element.iterChildren()
        else:
            return wx.GetApp().UIRepositoryView

    def GetElementValues(self, element):
        cellValues = [element.itsName or '(anonymous)']
        try:
            name = element.blockName
        except AttributeError:
            try:
                name = element.getItemDisplayName()
            except AttributeError:
                name = u' '
        cellValues.append (name)
        try:
            cellValues.append (element.itsKind.itsName)
        except AttributeError:
            cellValues.append (' ')
        cellValues.append (unicode (element.itsUUID))
        cellValues.append (unicode (element.itsPath))
        return cellValues

    def ElementHasChildren(self, element):
        if element == wx.GetApp().UIRepositoryView:
            return True
        else:
            return element.hasChildren()

class RepositoryItemDetail(ControlBlocks.ItemDetail):

    def getHTMLText(self, item):
        def formatReference(reference):
            """
            Formats the a reference attribute to be clickable, etcetera
            """

            if reference == None:
                return "(None)"

            url = reference.itsPath
            kind = reference.itsKind
            if kind is not None:
                kind = kind.itsName
            else:
                kind = "(kindless)"

            dn = reference.getItemDisplayName()

            # Escape < and > for HTML display
            kind = kind.replace(u"<", u"&lt;").replace(u">", u"&gt;")
            dn = dn.replace(u"<", u"&lt;").replace(u">", u"&gt;")

            return u"<a href=\"%(url)s\">%(kind)s: %(dn)s</a>" % locals()

        try:
            displayName = item.getItemDisplayName()
            try:
                kind = item.itsKind.itsName
            except AttributeError:
                kind = "(kindless)"

            HTMLText = u"<html><body><h5>%s: %s</h5><ul>" % (kind, displayName)
            HTMLText = HTMLText + u"<li><b>Path:</b> %s" % item.itsPath
            HTMLText = HTMLText + u"<li><b>UUID:</b> %s" % item.itsUUID
            HTMLText = HTMLText + u"</ul><h5>Attributes</h5><ul>"

            # We build tuples (name, formatted) for all value-only, then
            # all reference-only. Then we concatenate the two lists and sort
            # the result, and append that to the HTMLText.
            valueAttr = []
            for k, v in item.iterAttributeValues(valuesOnly=True):
                if isinstance(v, dict):
                    tmpList = [u"<li><b>%s:</b></li><ul>" % k]
                    for attr in v:
                        attrString = unicode(attr)
                        attrString = attrString.replace(u"<", u"&lt;")
                        attrString = attrString.replace(u">", u"&gt;")
                        tmpList.append(u"<li>%s</li>" % attrString)
                    tmpList.append(u"</ul>")
                    valueAttr.append((k, "".join(tmpList)))
                else:
                    value = unicode(v)
                    value = value.replace(u"<", u"&lt;")
                    value = value.replace(u">", u"&gt;")
                    valueAttr.append((k,u"<li><b>%s: </b>%s</li>" % (k, value)))

            refAttrs = []
            for k, v in item.iterAttributeValues(referencesOnly=True):
                if isinstance(v, dict) or isinstance(v, list):
                    tmpList = [u"<li><b>%s:</b></li><ul>" % k]
                    for attr in v:
                        tmpList.append(u"<li>%s</li>" % formatReference(attr))
                    tmpList.append(u"</ul>")
                    refAttrs.append((k, "".join(tmpList)))
                else:
                    value = formatReference(v)
                    refAttrs.append((k, u"<li><b>%s: </b>%s</li>" % (k, value)))

            allAttrs = refAttrs + valueAttr
            allAttrs.sort()
            dyn_html = "".join([y for x, y in allAttrs])

            HTMLText = u"%s%s</ul></body></html>" % (HTMLText, dyn_html)
        except:
            HTMLText = u"<html><body><h5></h5></body></html>"

        return HTMLText


class CPIADelegate (ControlBlocks.ListDelegate):
    """ Used by the tree in the repository view
    """

    def GetElementParent(self, element):
        return element.parentBlock

    def GetElementChildren(self, element):
        if element:
            return element.childrenBlocks
        else:
            return self.blockItem.findPath('//userdata/MainViewRoot')

    def GetElementValues(self, element):
        try:
            blockName = element.blockName
        except AttributeError:
            blockName = 'None'
        cellValues = [blockName]

        try:
            name = element.blockName
        except AttributeError:
            try:
                name = element.getItemDisplayName()
            except AttributeError:
                name = u' '
        cellValues.append (name)

        try:
            cellValues.append (unicode (element.getItemDisplayName()))
        except AttributeError:
            cellValues.append (u' ')
        cellValues.append (unicode (element.itsUUID))
        cellValues.append (unicode (element.itsPath))
        return cellValues

    def ElementHasChildren(self, element):
        return len (element.childrenBlocks) > 0
