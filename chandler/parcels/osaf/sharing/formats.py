#   Copyright (c) 2003-2006 Open Source Applications Foundation
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

__all__ = [
    'ImportExportFormat',
    'STYLE_SINGLE',
    'STYLE_DIRECTORY',
    'CloudXMLFormat',
]

import shares, errors
from utility import *
from notifications import *
import datetime, base64
from elementtree.ElementTree import ElementTree, XML
from xml.parsers import expat
from application import schema
from osaf import pim
from i18n import ChandlerMessageFactory as _
import osaf.mail.utils as utils
from chandlerdb.util.c import UUID, Nil
from cStringIO import StringIO
from repository.item.Item import Item
from repository.schema.Types import Type
import logging

logger = logging.getLogger(__name__)


STYLE_SINGLE = 'single' # Share represented by monolithic file
STYLE_DIRECTORY = 'directory' # Share is a directory where each item has
                              # its own file

CLOUD_XML_VERSION = '3'

class ImportExportFormat(pim.ContentItem):

    share = schema.One(shares.Share, inverse=shares.Share.format)


    def fileStyle(self):
        """
        Should return 'single' or 'directory'
        """
        pass

    def shareItemPath(self):
        """
        Return the path for the file representing the Share item
        """
        return None # None indicates there is no file representing the Share
                    # item

    def contentType(self, item):
        return "text/plain"

    def acceptsItem(self, item):
        return True


# These DOM API classes make it possible for subclasses CloudXMLFormat to
# share code that works with different XML DOM implementations.

class AbstractDOM(object):

    def addElement(self, parent, tag, content=None, **attrs):
        raise NotImplementedError, "%s.addElement" %(type(self))

    def addContent(self, element, content):
        raise NotImplementedError, "%s.addContent" %(type(self))
        
    def setAttribute(self, element, name, value):
        raise NotImplementedError, "%s.setAttribute" %(type(self))

    def setAttributes(self, element, *pairs, **kwds):
        raise NotImplementedError, "%s.setAttributes" %(type(self))
        
    def getTag(self, element):
        raise NotImplementedError, "%s.getTag" %(type(self))

    def getAttribute(self, element, name):
        raise NotImplementedError, "%s.getAttribute" %(type(self))

    def getAttributes(self, element):
        raise NotImplementedError, "%s.getAttributes" %(type(self))
        
    def iterElements(self, element):
        raise NotImplementedError, "%s.iterElements" %(type(self))

    def getFirstChildElement(self, element):
        raise NotImplementedError, "%s.getFirstChildElement" %(type(self))
        

class ElementTreeDOM(AbstractDOM):

    def getTag(self, element):
        return element.tag

    def getAttribute(self, element, name):
        return element.get(name)

    def iterElements(self, element):
        return element.getchildren()

    def getFirstChildElement(self, element):
        return element.getchildren()[0]


class CloudXMLFormat(ImportExportFormat):

    cloudAlias = schema.One(schema.Text, initialValue='sharing')
    
    # The following attributes are used to make sure that Cloud XML
    # is backwards compatible with the pre-annotation-as-stamping
    # world.

    # STAMP_MAP tells us what "old"-world class to use in place
    # of a given Stamp subclass when writing out Cloud XML
    STAMP_MAP = {
        pim.EventStamp: 'osaf.pim.calendar.Calendar.CalendarEvent',
        pim.TaskStamp: 'osaf.pim.tasks.Task',
        pim.mail.MailStamp: 'osaf.pim.mail.MailMessage',
    }
    
    # CLASS_NAME_TO_STAMP tells us how to map a share's filterClasses
    # attribute between the "old" and "new" world..
    CLASS_NAME_TO_STAMP  = dict(
        (clsName + "Mixin", "%s.%s" % (cls.__module__, cls.__name__))
            for cls, clsName in STAMP_MAP.iteritems()
    )

    
    # ELEMENT_ENTRIES is a list of three element tuples:
    #
    #  - An XML element name (tag, in elementtree parlance)
    #  - A tuple of stamp classes
    #  - Optionally, the "old-world" class name
    #
    # This allows us to use the correct element name when writing
    # out cloud XML, as well as pick the correct python class
    # name(s). When reading cloud XML, it lets us pick the
    # correct combination of stamps for an input element.
    ELEMENT_ENTRIES = [
        ('CalendarEvent', (pim.EventStamp,), None),
        ('Task', (pim.TaskStamp,), None),
        ('MailMessage', (pim.mail.MailStamp,), None),
        # The following are entries for pre-fab combinations
        # of Mixin classes in the old world.
        ('EventTask', (pim.EventStamp, pim.TaskStamp), 'osaf.pim.EventTask'),
        ('MailedEvent', (pim.EventStamp, pim.mail.MailStamp), 'osaf.pim.mail.MailedEvent'),
        ('MailedTask', (pim.TaskStamp, pim.mail.MailStamp), 'osaf.pim.mail.MailedTask'),
        ('MailedEventTask', (pim.TaskStamp, pim.mail.MailStamp, pim.EventStamp),
         'osaf.pim.MailedEventTask'),
    ]
    
    # In the old world, pim.mail defined all these classes as subclasses
    # of ContentItem, and then made MailMessageMixin a subclass of
    # MIMEContainer. In the new world, MailStamp (the equivalent of
    # MailMessageMixin) can't inherit from ContentItem (since it's an
    # Annotation), and so these classes all inherit from Annotation.
    # This makes it hard to figure out what to write out for a given
    # MIME object.
    MIME_CLASSES = (
        pim.mail.MIMEBase,
        pim.mail.MIMENote,
        pim.mail.MIMEContainer,
        pim.mail.MIMEBinary,
        pim.mail.MIMESecurity,
        pim.mail.MIMEText,
    )


    def fileStyle(self):
        return STYLE_DIRECTORY

    def extension(self, item):
        return "xml"

    def shareItemPath(self):
        return "share.xml"

    def importProcess(self, contentView, text, extension=None, item=None,
        updateCallback=None, stats=None):

        try:
            root = ElementTree(file=StringIO(text)).getroot()
        except expat.ExpatError, e:
            logger.exception("CloudXML parsing error")
            raise errors.MalformedData(str(e))
        except:
            logger.exception("CloudXML parsing error")
            raise

        try:
            item = self._importElement(ElementTreeDOM(), contentView, root,
                                       item, updateCallback, stats)
        except:
            logger.exception("Error during import")
            raise

        return item

    def _getElementName(self, kind, stampClasses):

        if stampClasses:
            # Figure out the element name
            for eltName, eltStampClasses, eltClassName in self.ELEMENT_ENTRIES:
                if set(eltStampClasses) == stampClasses:
                    elementName = eltName
                    if eltClassName is not None:
                        classes = eltClassName
                    else:
                        classes = ','.join(self.STAMP_MAP[cls]
                                           for cls in eltStampClasses)
                    break
            else:
                raise errors.VersionMismatch, ("Can't match stamp classes",
                                        stampClasses)
        else:
            elementName = kind.itsName
            if kind.isMixin():
                classNames = []
                for kind in kind.superKinds:
                    cls = kind.classes['python']
                    className = "%s.%s" % (cls.__module__, cls.__name__)
                    classNames.append(className)
                classes = ",".join(classNames)
            else:
                cls = kind.classes['python']
                classes = "%s.%s" % (cls.__module__, cls.__name__)

        return elementName, classes

    def exportProcess(self, item, depth=0, items=None):

        if items is None:
            items = {}

        if depth == 0:
            result = '<?xml version="1.0" encoding="UTF-8"?>\n\n'
            versionString = "version='%s' " % CLOUD_XML_VERSION
        else:
            result = ''
            versionString = ''

        indent = "   "

        if items.has_key(item.itsUUID):
            result += indent * depth
            result += "<%s uuid='%s' />\n" % (item.itsKind.itsName,
                                               item.itsUUID)
            return result

        items[item.itsUUID] = 1

        result += indent * depth
        
        stampClasses = None
        
        try:
            stampClasses = set(pim.Stamp(item).stamp_types)
        except TypeError:
            pass

        # Figure out the element name
        elementName, classes = self._getElementName(item.itsKind, stampClasses)

        # Collect the set of attributes that are used in this format
        def getNameAndAttributes():
            attributes = self.share.getSharedAttributes(item.itsKind)
            hasMailStamp = pim.has_stamp(item, pim.mail.MailStamp)
            attrs = []
            mailClass = None

            if hasMailStamp and not pim.mail.MailStamp.subject.name in attributes:
                attributes.add(pim.mail.MailStamp.subject.name)
            
            for attrName in attributes:
            
                # @@@ [grant] A hack; cloud xml seems to write out 'subject'
                # sometimes, and 'displayName' @ others. This might have
                # something to do with the order of redirected attributes?
                if hasMailStamp and attrName in ('displayName', 'title'):
                    continue
                
                    
                splitComponents = attrName.rsplit(".", 1)
                
                if len(splitComponents) == 2: # an "annotation" attribute
                    try:
                        annotationClass = schema.importString(splitComponents[0])
                    except ImportError:
                        # raise? how did this happen, eh?
                        continue

                    if annotationClass in self.MIME_CLASSES:
                        # Here, we decide that we should use annotationClass
                        # for writing out the element if it turns out
                        # that item has a value for the attribute, and
                        # that value isn't the same is the attribute's
                        # initialValue....
                        if not hasattr(item, attrName):
                            continue
                        
                        initial = item.getAttributeAspect(attrName,
                                                          'initialValue')
                        itemValue = getattr(item, attrName)
                        
                        if (item.getAttributeAspect(attrName, 'cardinality') ==
                            'list'):
                            itemValue = list(itemValue)
                        
                        # ... with the exception of
                        # mimeParts, which always seem to have been written
                        # in the "old" world.
                        if ( (not (hasMailStamp and splitComponents[-1] in
                                ('mimeParts'))) and
                                itemValue == initial ):
                            continue
                            
                        if mailClass is None:
                            mailClass = annotationClass
                        elif issubclass(annotationClass, mailClass):
                            mailClass = annotationClass

                    elif not annotationClass in (stampClasses or []):
                        continue

                if not hasattr(item, attrName):
                    continue
                    
                attrs.append((splitComponents[-1], attrName))
                
            if mailClass is not None and not hasMailStamp:
                # Here, we base the XML element name we write out
                # (e.g. MIMEBinary vs MIMEText) on the Content-Type
                # of the MIME part.
                if mailClass == pim.mail.MIMENote:
                    if getattr(item, mailClass.mimeType.name,
                               "text/plain").startswith("text/"):
                        mailClass = pim.mail.MIMEText
                    else:
                        mailClass = pim.mail.MIMEBinary
                        
                return mailClass.__name__, "%s.%s" % (mailClass.__module__, mailClass.__name__), attrs
            else:
                return elementName, classes, attrs
                
        elementName, classes, attributes = getNameAndAttributes()

        # Backwards compatibility hack
        if classes == "osaf.sharing.shares.Share":
            classes = "osaf.sharing.Sharing.Share"

        result += "<%s %sclass='%s' uuid='%s'>\n" % (elementName,
                                                    versionString,
                                                    classes,
                                                    item.itsUUID)

        depth += 1
        

        # Backwards compatibility hack
        if classes == "osaf.sharing.Sharing.Share":
            result += indent * depth
            result += "<filterClasses>\n"
            result += indent * depth
            result += "</filterClasses>\n"

        for attrXmlName, attrName in attributes:

            attrValue = item.getAttributeValue(attrName)
            if attrValue is None:
                continue

            otherName = item.itsKind.getOtherName(attrName, item, None)
            cardinality = item.getAttributeAspect(attrName, 'cardinality')
            attrType = item.getAttributeAspect(attrName, 'type')

            result += indent * depth

            if otherName: # it's a bidiref
                result += "<%s>\n" % attrXmlName

                if cardinality == 'single':
                    if attrValue is not None:
                        result += self.exportProcess(attrValue, depth+1, items)

                elif cardinality == 'list':
                    for value in attrValue:
                        result += self.exportProcess(value, depth+1, items)

                elif cardinality == 'dict':
                    # @@@MOR
                    pass

                result += indent * depth

            else: # it's a literal (@@@MOR could be SingleRef though)

                # Since 'displayName' is being renamed 'title', let's keep
                # existing shares backwards-compatible and continue to read/
                # write 'displayName':
                if attrName == 'title':
                    result += "<%s" % 'displayName'
                else:
                    result += "<%s" % attrXmlName

                if cardinality == 'single':

                    if isinstance(attrValue, Item):
                        result += ">\n"
                        result += self.exportProcess(attrValue, depth+1, items)
                    else:
                        (mimeType, encoding, attrValue) = \
                            serializeLiteral(attrValue, attrType)

                        # @@@MOR 0.6 sharing compatibility
                        # Pretend body is a Lob for the benefit of 0.6 clients
                        if attrName == 'body':
                            mimeType = "text/plain"
                            encoding = "utf-8"
                            attrValue = base64.b64encode(attrValue)
                        else:
                            attrValue = attrValue.replace('&', '&amp;')
                            attrValue = attrValue.replace('<', '&lt;')
                            attrValue = attrValue.replace('>', '&gt;')

                        if mimeType:
                            result += " mimetype='%s'" % mimeType

                        if encoding:
                            result += " encoding='%s'" % encoding

                        result += ">"
                        result += attrValue


                elif cardinality == 'list':
                    result += ">"
                    depth += 1
                    result += "\n"
                    
                    if isinstance(item, shares.Share):
                    
                        if attrXmlName == "filterAttributes":
                            # In the stamping-as-annotation world, all the
                            # attribute names in Share.filterAttributes are
                            # annotation attributes; i.e. they are prefixed
                            # by the 'fully-qualified' annotation class name.
                            # The following makes sure that we share only the
                            # part of the name after the last '.'; note that
                            # it still works if rfind fails (i.e. returns -1)
                            # 
                            attrValue = list(x[x.rfind(".")+1:]
                                             for x in attrValue)
                        elif (attrXmlName == "filterClasses") and attrValue:
                            # Similarly, since the class names have changed
                            # (from xxxMixin to xxxStamp) some translation
                            # is needed for Share.filterClasses
                            newValues = []
                            for value in attrValue:
                                try:
                                    cls = schema.importString(value)
                                except ImportError:
                                    pass
                                else:
                                    value = self.STAMP_MAP.get(cls, value)
                                    if not value.endswith('Mixin'):
                                        value += 'Mixin'
                                newValues.append(value)
                            attrValue = newValues
                                

                    for value in attrValue:
                        result += indent * depth
                        result += "<value"

                        (mimeType, encoding, value) = \
                            serializeLiteral(value, attrType)
                        value = value.replace('&', '&amp;')
                        value = value.replace('<', '&lt;')
                        value = value.replace('>', '&gt;')

                        if mimeType:
                            result += " mimetype='%s'" % mimeType

                        if encoding:
                            result += " encoding='%s'" % encoding

                        result += ">"
                        result += value
                        result += "</value>\n"

                    depth -= 1

                    result += indent * depth

                elif cardinality == 'dict':
                    result += ">"
                    # @@@MOR
                    pass


            # Since 'displayName' is being renamed 'title', let's keep
            # existing shares backwards-compatible and continue to read/
            # write 'displayName':
            if attrName == 'title':
                result += "</%s>\n" % 'displayName'
            else:
                result += "</%s>\n" % attrXmlName

        depth -= 1
        result += indent * depth
        result += "</%s>\n" % elementName
        return result


    def _getElement(self, dom, element, attribute):

        # @@@MOR This method only supports traversal of single-cardinality
        # attributes

        # attribute can be a dot-separated chain of attribute names
        chain = attribute.split(".")
        attribute = chain[0]
        remaining = chain[1:]

        for child in dom.iterElements(element):
            if dom.getTag(child) == attribute:
                if not remaining:
                    # we're at the end of the chain
                    return child
                else:
                    # we need to recurse. @@@MOR for now, not supporting
                    # list
                    return self._getElement(dom, dom.getFirstChildElement(child), ".".join(remaining))

        return None

    def _importItem(self, dom, view, element, item, updateCallback, stats):

        kind = None
        kinds = []
        
        for eltName, eltStampClasses, eltClassName in self.ELEMENT_ENTRIES:
            if dom.getTag(element) == eltName:
                stampClasses = eltStampClasses
                for cls in stampClasses:
                    kind = cls.targetType().getKind(view)
                    if not kind in kinds:
                        kinds.append(kind)
                break
        else:
            stampClasses = []
            
        if item is None:
            uuidString = dom.getAttribute(element, 'uuid')
            if uuidString:
                try:
                    uuid = UUID(uuidString)
                    item = view.findUUID(uuid)
                except Exception, e:
                    logger.exception("Problem processing uuid %s", uuidString)
                    return item, None, True
            else:
                uuid = None

        classNameList = dom.getAttribute(element, 'class')
        if classNameList:
            classNameList = classNameList.split(",")
            for classPath in classNameList:
                # Backwards compatibility hack
                if classPath == 'osaf.sharing.Sharing.Share':
                    classPath = 'osaf.sharing.shares.Share'
                if stampClasses:
                    for cls, clsPath in self.STAMP_MAP.iteritems():
                        if clsPath == classPath:
                            if not cls in stampClasses:
                                stampClasses.append(cls)
                            break
                else:
                    try:
                        klass = schema.importString(classPath)
                    except ImportError:
                        pass
                    else:
                        if klass in self.MIME_CLASSES:
                            kind = schema.itemFor(klass.targetType(), view)
                        else:
                            kind = klass.getKind(view)

                        if kind is not None:
                            kinds.append(kind)
        else:
            # No kind means we're simply looking up an item by uuid and
            # returning it
            return item, None, True

        if len(kinds) == 0:
            # we don't have any of the kinds provided
            logger.error("No kinds found locally for %s", classNameList)
            return None, None, True
        elif len(kinds) == 1:
            kind = kinds[0]
        else: # time to mixin
            kind = kinds[0].mixin(kinds[1:])


        if item is None:
            # item search turned up empty, so create an item...
            if uuid:

                # Bug 7354: Before we proceed to create this item, let's see
                # if an icalUID is specified in the XML -- if there is, then
                # see if there is a master event already with this icalUID.
                # If so, skip this item.
                icalElement = self._getElement(dom, element, 'icalUID')
                if icalElement is not None:
                    icalUID = icalElement.text
                    existingEvent = pim.calendar.Calendar.findUID(view, icalUID)
                    if existingEvent is not None:
                        eventItem = existingEvent.itsItem
                        logger.error("A master event with this icalUID (%s) "
                                     "already exists (%s)",
                                     icalUID, eventItem.itsUUID)
                        raise errors.SharingError("Item with duplicate icalUID (%s)" %
                                           icalUID)

                parent = schema.Item.getDefaultParent(view)
                item = kind.instantiateItem(None, parent, uuid,
                                            withInitialValues=True)
                if isinstance(item, pim.SmartCollection):
                    item._setup()

            else:
                item = kind.newItem(None, None)

            if stats and uuid not in stats['added']:
                stats['added'].append(uuid)

            if isinstance(item, pim.ContentItem):
                SharingNewItemNotification(itsView=item.itsView,
                    displayName="New item", items=[item])

        else:
            uuid = item.itsUUID
            if stats and uuid not in stats['modified']:
                stats['modified'].append(uuid)

        return item, stampClasses, False

    def _importValues(self, dom, view, element, item, stampClasses,
                      updateCallback, stats):

        attributes = self.share.getSharedAttributes(item.itsKind)
            
        if (pim.mail.MailStamp in stampClasses and 
            not pim.mail.MailStamp.subject.name in attributes):
                attributes.add(pim.mail.MailStamp.subject.name)
                # 'subject' is redirected to 'displayName'
                # Lack of 'displayName' in XML can cause 'subject' to get
                # lost during import
                if 'displayName' in attributes:
                    attributes.remove('displayName')

        for attrName in attributes:
            attrStampClass = None
                
            # Since 'displayName' is being renamed 'title', let's keep
            # existing shares backwards-compatible and continue to read/
            # write 'displayName':
            if attrName == 'title':
                elementName = 'displayName'
            else:
                lastDot = attrName.rfind(".")
                if lastDot != -1:
                    elementName = attrName[lastDot + 1:]
                        
                    for cls in self.STAMP_MAP:
                        if (hasattr(cls, elementName) and
                            getattr(cls, elementName).name == attrName):
                            attrStampClass = cls
                            break
                        
                else:
                    elementName = attrName

            # [Bug 7149]
            # Here, we make sure we don't change any attributes that
            # aren't in the item's (possibly changed) set of stamps.
            if (attrStampClass is not None and
                not attrStampClass in stampClasses):
                continue

            attrElement = self._getElement(dom, element, elementName)

            if attrElement is None:
                # [Bug 7314]
                # When we export, we don't output any XML for
                # attributes whose value is None. So, don't
                # remove missing attributes that are missing
                # the item's value for that attribute is None.
                if item.getAttributeValue(attrName, default=None) is not None:
                    item.removeAttributeValue(attrName)
                continue

            otherName = item.itsKind.getOtherName(attrName, item, None)
            cardinality = item.getAttributeAspect(attrName, 'cardinality')
            attrType = item.getAttributeAspect(attrName, 'type')

            # This code depends on attributes having their type set, which
            # might not always be the case. What should be done is to encode
            # the value type into the shared xml itself:

            if otherName or (isinstance(attrType, Item) and \
                not isinstance(attrType, Type)): # it's a ref

                if cardinality == 'single':
                    children = attrElement.getchildren()
                    if children:
                        valueItem = self._importElement(dom, view,
                            children[0], updateCallback=updateCallback)
                        if valueItem is not None:
                            setattr(item, attrName, valueItem)

                elif cardinality == 'list':
                    count = 0
                    for child in attrElement.getchildren():
                        valueItem = self._importElement(dom, view,
                            child, updateCallback=updateCallback)
                        if valueItem is not None:
                            count += 1
                            item.addValue(attrName, valueItem)
                    if not count:
                        # Only set to an empty ref collection is attrName
                        # is not already an empty ref collection
                        needToSet = True
                        if hasattr(item, attrName):
                            try:
                                if len(getattr(item, attrName)) == 0:
                                    needToSet = False
                            except:
                                pass
                        if needToSet:
                            setattr(item, attrName, [])

                elif cardinality == 'dict':
                    pass

            else: # it's a literal

                if cardinality == 'single':

                    mimeType = attrElement.get('mimetype')
                    encoding = attrElement.get('encoding')
                    content = unicode(attrElement.text or u"")

                    if mimeType: # Lob
                        indexed = mimeType == "text/plain"
                        value = base64.b64decode(content)

                        # @@@MOR Temporary hack for backwards compatbility:
                        # Because body changed from Lob to Text:
                        if attrName == "body": # Store as unicode
                            if type(value) is not unicode:
                                if encoding:
                                    value = unicode(value, encoding)
                                else:
                                    value = unicode(value)
                        else: # Store it as a Lob
                            value = utils.dataToBinary(item, attrName,
                                value, mimeType=mimeType, indexed=indexed)
                            if encoding:
                                value.encoding = encoding

                    else:
                        value = attrType.makeValue(content)


                    # For datetime attributes, even if we set them to
                    # the same value they have now it's considered a
                    # change to the repository, so we do an additional
                    # check ourselves before actually setting a datetime:
                    if type(value) is datetime.datetime and hasattr(item,
                        attrName):
                        oldValue = getattr(item, attrName)
                        if (oldValue != value or
                            oldValue.tzinfo != value.tzinfo):
                            setattr(item, attrName, value)
                    else:
                        setattr(item, attrName, value)

                elif cardinality == 'list':
                    isFilterAttributes = (attrName == 'filterAttributes' and
                                          isinstance(item, shares.Share))
                    isFilterClasses = (attrName == 'filterClasses' and
                                          isinstance(item, shares.Share))

                    values = []
                    for child in attrElement.getchildren():

                        mimeType = child.get('mimetype')

                        if mimeType: # Lob
                            indexed = mimeType == "text/plain"
                            value = base64.b64decode(unicode(child.text
                                or u""))
                            value = utils.dataToBinary(item, attrName,
                                value, mimeType=mimeType,
                                indexed=indexed)

                            encoding = child.get('encoding')
                            if encoding:
                                value.encoding = encoding

                        else:
                            content = unicode(child.text or u"")
                            value = attrType.makeValue(content)

                        # For Share.filterAttributes, we need to map
                        # 'unqualified' attribute names to annotation-
                        # style ones. To do this, we look through all
                        # the Stamp classes we know, as well as
                        # pim.Remindable, to find a matching attribute.
                        # There is an inverse hack to this in exportProcess.
                        if isFilterAttributes:
                            for cls in self.STAMP_MAP.iterkeys():
                                schemaAttr = getattr(cls, value, None)
                                if schemaAttr is not None:
                                    break
                            else:
                                schemaAttr = getattr(pim.Remindable, value, None)

                            if schemaAttr is not None:
                                value = schemaAttr.name
                                    
                        if isFilterClasses:
                            value = self.CLASS_NAME_TO_STAMP.get(value, value)

                        values.append(value)

                    logger.debug("for %s setting %s to %s" % \
                        (item.getItemDisplayName().encode('utf8',
                        'replace'), attrName, values))
                    setattr(item, attrName, values)

                elif cardinality == 'dict':
                    pass

    def _importStamps(self, item, stampClasses):

        # Install stamps as needed
        for cls in stampClasses:
            if not pim.has_stamp(item, cls):
                cls(item).add()

        # Handle unstamping
        stamps = pim.Stamp(item).stamp_types or []
        for stamp in stamps:
            if stamp not in stampClasses:
                stamp(item).remove()

    def _importElement(self, dom, contentView, element, item=None,
                       updateCallback=None, stats=None):

        versionString = element.get('version')
        if versionString and versionString != CLOUD_XML_VERSION:
            raise errors.VersionMismatch(_(u"Incompatible share"))

        # Find or create the item being imported
        item, stamps, done = self._importItem(dom, contentView, element,
                                              item, updateCallback, stats)
        if done:
            return item

        # Set a temporary attribute that items can check to see if they're in
        # the middle of being imported:

        item._share_importing = True

        try:
            # We have an item, now set attributes
            self._importValues(dom, contentView, element, item,
                               stamps, updateCallback, stats)
        finally:
            del item._share_importing

        # Lastly, import stamps
        if isinstance(item, pim.ContentItem):
            self._importStamps(item, stamps)

        return item