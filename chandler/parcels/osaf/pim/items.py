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


""" Classes used for pim parcel and kinds.
"""

__parcel__ = "osaf.pim"

import time
from datetime import datetime

from application import schema
from repository.schema.Kind import Kind
import repository.item.Item as Item
from chandlerdb.item.ItemError import NoLocalValueForAttributeError
from chandlerdb.util.c import Nil
from chandlerdb.item.c import isitemref
import logging
from i18n import ChandlerMessageFactory as _
from osaf import messages
from PyICU import ICUtzinfo

logger = logging.getLogger(__name__)

class ContentKind(Kind):
    """
    This kind is a metakind for creating other kinds.  Kinds which are
    an instance of ContentKind will have an attribute 'detailView' of type
    Block.  We could also make this attribute a bidiref.
    """

    __metaclass__ = schema.ItemClass

    detailView = schema.One()   # Block


class ImportanceEnum(schema.Enumeration):
    """
    Importance Enum
    """
    values = "important", "normal", "fyi"

class TriageEnum(schema.Enumeration):
    values = { "now": 0 , "later": 5000, "done": 10000 }

triageStatusNames = { TriageEnum.now: _(u"Now"),
                      TriageEnum.later: _(u"Later"),
                      TriageEnum.done: _(u"Done")
                    }
def getTriageStatusName(value):
    return triageStatusNames[value]

# Bug 6525: the clicking sequence isn't the sort order
triageStatusClickSequence = { TriageEnum.now: TriageEnum.done,
                              TriageEnum.done: TriageEnum.later,
                              TriageEnum.later: TriageEnum.now }
def getNextTriageStatus(value):
    return triageStatusClickSequence[value]
    
class Modification(schema.Enumeration):
    """
    Enumeration of the types of modification that are part of
    the edit/update workflows (a.k.a. "Stamping Storyboards")
    """
    values = { "edited":100, "queued":200, "sent":300, "updated":400 }

def isDead(item):
    """
    Return True if the item is None, an itemref, stale, or deferred.
    
    """
    return (item is None or isitemref(item) or item.isStale() or
            item.isDeferred())

# For use in indexing time-related attributes. We only use this for 
# reminderFireTime here, but CalendarEventMixin uses this a lot more...
def cmpTimeAttribute(item, other, attr, useTZ=True):
    """Compare item and self.attr, ignore timezones if useTZ is False."""
    otherTime = getattr(other, attr, None)
    itemTime = getattr(item, attr, None)

    if otherTime is None:
        if itemTime is None:
            # both attributes are None, so item and other compare as equal
            return 0
        else:
            return -1
    elif not useTZ:
        otherTime = otherTime.replace(tzinfo = None)

    if itemTime is None:
        return 1
    elif not useTZ:
        itemTime = itemTime.replace(tzinfo = None)

    return cmp(itemTime, otherTime)



class ContentItem(schema.Item):
    """
    Content Item

    Content Item is the abstract super-kind for things like Contacts, Calendar
    Events, Tasks, Mail Messages, and Notes.  Content Items are user-level
    items, which a user might file, categorize, share, and delete.

    Examples:
     - a Calendar Event -- 'Lunch with Tug'
     - a Contact -- 'Terry Smith'
     - a Task -- 'mail 1040 to IRS'
    """
    displayName = schema.One(schema.Text, indexed=True)
    body = schema.One(
        schema.Text,
        indexed = True,
        defaultValue = u"",
        doc="All Content Items may have a body to contain notes.  It's "
            "not decided yet whether this body would instead contain the "
            "payload for resource items such as presentations or "
            "spreadsheets -- resource items haven't been nailed down "
            "yet -- but the payload may be different from the notes because "
            "payload needs to know MIME type, etc."
    )

    creator = schema.One(
        # Contact
        doc="Link to the contact who created the item."
    )

    modifiedFlags = schema.Many(
        Modification,
        initialValue=set([]),
        description='Used to track the modification state of the item'
    )
    
    lastModified = schema.One(
        schema.DateTimeTZ,
        doc="DateTime (including timezone) this item was last modified",
        defaultValue=None,
    )

    lastModifiedBy = schema.One(
        # Contact
        doc="Link to the contact who last modified the item.",
        defaultValue=None,
    )
    
    lastModification = schema.One(
        Modification,
        doc="What the last modification was; None = freshly created item"
    )

    def getByline(self):
        lastModification = getattr(self, 'lastModification', None)
        
        if lastModification is None:
            fmt = _(u"Created by %(user)s on %(date)s")
        elif lastModification == Modification.edited:
            fmt = _(u"Edited by %(user)s on %(date)s")
        elif lastModification == Modification.updated:
            fmt = _(u"Updated by %(user)s on %(date)s")
        elif lastModification in (Modification.queued, Modification.sent):
            fmt = _(u"Sent by %(user)s on %(date)s")
        else:
            assert False, \
                "Unrecognized lastModification value %s" % (lastModification,)
                
        user = self.lastModifiedBy or messages.ME
        # fall back to createdOn
        lastModified = (self.lastModified or getattr(self, 'createdOn', None) or
                       datetime.now(ICUtzinfo.default))
        
        shortDateFormat = schema.importString("osaf.pim.shortDateFormat")
        date = shortDateFormat.format(lastModified)
        
        return fmt % dict(user=user, date=date)
        
    error = schema.One(
        schema.Text,
        doc="A user-visible string containing the last error that occurred. "
            "Typically, this should be set by the sharing or email layers when "
            "a conflict or delivery problem occurs.",
        defaultValue=None
    )

    byline = schema.Calculated(
        schema.Text,
        basedOn=(modifiedFlags, lastModified, lastModification, lastModifiedBy),
        fget=getByline
    )
    
    importance = schema.One(ImportanceEnum,
        doc="Most items are of normal importance (no value need be shown), "
            "however some things may be flagged either highly important or "
            "merely 'fyi'. This attribute is also used in the mail schema, so "
            "we shouldn't make any changes here that would break e-mail "
            "interoperability features.",
        initialValue="normal",
    )

    mine = schema.One(schema.Boolean, initialValue=True)

    private = schema.One(schema.Boolean, initialValue=False)

    read = schema.One(
        schema.Boolean,
        initialValue=False,
        doc="A flag indicating whether the this item has "
            "been 'viewed' by the user"
    )

    needsReply = schema.One(
        schema.Boolean,
        initialValue=False,
        doc="A flag indicating that the user wants to reply to this item"
    )


    createdOn = schema.One(
        schema.DateTimeTZ,
        doc="DateTime this item was created"
    )

    tags = schema.Sequence(
        #'Tag',
        description='All the Tags associated with this ContentItem',
        #inverse='items',
        initialValue=[]
    )

    notifications = schema.Sequence(
        #'UserNotification',
        description='All notifications for this ContentItem',
        initialValue=[]
    )

    # "Section" triage status is used for sorting
    triageStatus = schema.One(TriageEnum, defaultValue=TriageEnum.now,
                              indexed=True)
    
    # "unpurged" (aka "color") triage status is used to set (and changed 
    # by) the column cell, and is pushed to sectionTriageStatus by the 
    # 'Triage' button.
    _unpurgedTriageStatus = schema.One(TriageEnum)

    # For sorting by how recently the triageStatus values changed, 
    # we keep these attributes, which are the time (in seconds) of the last 
    # change to each, negated for proper order. They're updated automatically 
    # when the corresponding triage status value is changed by 
    # setTriageStatus and setUnpurgedTriageStatus, below.
    triageStatusChanged = schema.One(schema.Float)
    _unpurgedTriageStatusChanged = schema.One(schema.Float)
    
    def getUnpurgedTriageStatus(self):
        result = self.getAttributeValue('_unpurgedTriageStatus', default=None)
        if result is None:
            result = self.triageStatus
        return result

    def setUnpurgedTriageStatus(self, value):
        self._unpurgedTriageStatus = value

    unpurgedTriageStatus = schema.Calculated(
                            TriageEnum,
                            fset=setUnpurgedTriageStatus,
                            fget=getUnpurgedTriageStatus,
                            basedOn=(_unpurgedTriageStatus, triageStatus),
                            doc="Calculated for edited triageStatus, before"
                                "user has committed changes")

    # XXX These attributes should be moved to an Annotation defined in sharing
    #     to preserve the "modular APIs" tenet
    shares = schema.Sequence(initialValue=[], otherName='contents') # Share.contents
    sharedIn = schema.Sequence(initialValue=[], otherName='items')  # Share.items

    # ContentItem instances can be put into ListCollections and AppCollections
    collections = schema.Sequence(notify=True) # inverse=collections.inclusions

    # ContentItem instances can be excluded by AppCollections
    excludedBy = schema.Sequence()

    # ContentItem instances can be put into SmartCollections (which define
    # the other end of this biref)
    appearsIn = schema.Sequence()

    # The date used for sorting the Date column
    displayDate = schema.One(schema.DateTimeTZ, indexed=True)
    displayDateSource = schema.One(schema.Importable)

    # The value displayed (and sorted) for the Who column.
    displayWho = schema.One(schema.Text, indexed=True)
    displayWhoSource = schema.One(schema.Importable)

    schema.addClouds(
        sharing = schema.Cloud(
            literal = ["displayName", body, createdOn,
                       "description", triageStatus, triageStatusChanged],
            byValue = ['tags', lastModifiedBy]
        ),
        copying = schema.Cloud()
    )

    def __init__(self, *args, **kw):
        super(ContentItem, self).__init__(*args, **kw)
        now = None
        if not hasattr(self, 'createdOn'):
            now = datetime.now(ICUtzinfo.default)
            self.createdOn = now
        if not hasattr(self, 'triageStatusChanged'):
            self.setTriageStatusChanged(when=now)

    def __str__ (self):
        if self.isStale():
            return super(ContentItem, self).__str__()
            # Stale items can't access their attributes

        return self.__unicode__().encode('utf8')

    def __unicode__(self):
        if self.isStale():
            return super(ContentItem, self).__unicode__()

        return unicode(getattr(self, 'displayName', self.itsName) or
                       self.itsUUID.str64())

    def InitOutgoingAttributes(self):
        """ Init any attributes on ourself that are appropriate for
        a new outgoing item.
        """
        try:
            super(ContentItem, self).InitOutgoingAttributes ()
        except AttributeError:
            pass

        # default the displayName
        self.displayName = messages.UNTITLED

    def ExportItemData(self, clipboardHandler):
        # Create data for this kind of item in the clipboard handler
        # The data is used for Drag and Drop or Cut and Paste
        try:
            super(ContentItem, self).ExportItemData(clipboardHandler)
        except AttributeError:
            pass

        # Let the clipboard handler know we've got a ContentItem to export
        clipboardHandler.ExportItemFormat(self, 'ContentItem')

    def onItemDelete(self, view, deferring):
        # Hook for stamp deletion ...
        from stamping import Stamp
        for stampObject in Stamp(self).stamps:
            onItemDelete = getattr(stampObject, 'onItemDelete', None)
            if onItemDelete is not None:
                onItemDelete(view, deferring)

    def addToCollection(self, collection):
        """Add self to the given collection.

        For most items, just call collection.add(self), but for recurring
        events, this method is intercepted by a proxy and buffered while the
        user selects from various possible meanings for adding a recurring event
        to a collection.

        """
        collection.add(self)

    def removeFromCollection(self, collection, cutting = False):
        """Remove self from the given collection.        

        For most items, just call collection.remove(self), but for recurring
        events, this method is intercepted by a proxy and buffered while the
        user selects from various possible meanings for removing a recurring
        event from a collection.

        Cutting is typically equivalent to remove, but recurrence has different
        behavior for cutting operations than delete.

        The special mine collection behavior that removed items should remain in
        the Dashboard is implemented here.

        """
        self._prepareToRemoveFromCollection(collection)
        collection.remove(self)

    def _prepareToRemoveFromCollection(self, collection):
        """
        If the collection is a mine collection and the item doesn't exist in any
        other 'mine' collections, manually add it to 'all' to keep the item
        'mine'.

        We don't want to do this blindly though, or all's inclusions will get
        unnecessarily full.

        We also don't want to remove collection from mine.sources. That will
        cause a notification storm as items temporarily leave and re-enter
        being 'mine'.
        
        """
        pim_ns = schema.ns('osaf.pim', self.itsView)
        mine = pim_ns.mine
        allCollection = pim_ns.allCollection

        if collection in mine.sources:
            for otherCollection in self.appearsIn:
                if otherCollection is collection:
                    continue
    
                if otherCollection in mine.sources:
                    # we found it in another 'mine'
                    break
            else:
                # we didn't find it in a 'mine' Collection
                allCollection.add(self)        

    def getMembershipItem(self):
        """ Get the item that should be used to test for membership
        tests i.e. if item in collection: should be if
        item.getMembershipItem() in collection

        For most items, this is just itself, but for recurring
        events, this method is intercepted by a proxy.
        """
        return self

    def changeEditState(self, modType=Modification.edited, who=None,
                        when=None):
        """
        @param modType: What kind of modification you are making. Used to set
                        the value of C{self.lastModification}.
        @type modType: C{Modification}
        
        @param who: May be C{None}, which is interpreted as the current user.
                    Used to set the value of {self.lastModifiedBy}.
        @type who: C{Contact}
        
        @param when: The date&time of this change. Used to set the value
                     of C{self.lastModified}. The default, C{None}, sets
                     the 
        @type when: C{datetime}
        """
        
        logger.debug("ContentItem.changeEditState() self=%s view=%s modType=%s who=%s when=%s", self, self.itsView, modType, who, when)
        
        currentModFlags = self.modifiedFlags
        
        if modType == Modification.sent:
            if Modification.sent in currentModFlags:
                raise ValueError, "You can't send an item twice"
            elif Modification.queued in currentModFlags:
                currentModFlags.remove(Modification.queued)
        elif modType == Modification.updated:
            if not Modification.sent in currentModFlags:
                raise ValueError, "You can't update an item till it's been sent"
            elif Modification.queued in currentModFlags:
                currentModFlags.remove(Modification.queued)
        # Clear the edited flag and error on send/update/queue
        if (modType in (Modification.sent, Modification.updated, 
                        Modification.queued)):
            if Modification.edited in currentModFlags:
                currentModFlags.remove(Modification.edited)
            del self.error

        currentModFlags.add(modType)
        self.lastModification = modType
        self.lastModified = when or datetime.now(ICUtzinfo.default)
        self.lastModifiedBy = who # None => me

    """
    ACCESSORS

    Accessors for Content Item attributes
    """
    def getEmailAddress (self, nameOrAddressString):
        """
          Lookup or create an EmailAddress based
        on the supplied string.
        This method is here for convenient access, so users
        don't need to import Mail.
        """
        from mail import EmailAddress
        return EmailAddress.getEmailAddress (self.itsView, nameOrAddressString)

    def getCurrentMeEmailAddress (self):
        """
          Lookup or create a current "me" EmailAddress.
        The "me" EmailAddress is whichever one has the current IMAP default address.
        This method is here for convenient access, so users
        don't need to import Mail.
        """
        from mail import EmailAddress
        return EmailAddress.getCurrentMeEmailAddress (self.itsView)


    READWRITE = 'read-write'
    READONLY = 'read-only'
    UNSHARED = 'unshared'

    def getSharedState(self):
        """
        Examine all the shares this item participates in; if any of those
        shares are writable the shared state is READWRITE.  If all the shares
        are read-only the shared state is READONLY.  Otherwise UNSHARED.
        """

        state = ContentItem.UNSHARED
        if hasattr(self, 'sharedIn'):
            for share in self.sharedIn:
                state = ContentItem.READONLY
                if share.mode in ('put', 'both'):
                    return ContentItem.READWRITE

        return state

    sharedState = property(getSharedState)

    def _updateCommonAttribute(self, attributeName, sourceAttributeName,
                               collectorMethod, default=Nil, picker=None):
        """
        Mechanism for coordinating updates to a common-display field
        (like displayWho and displayDate, but not displayName for now).
        """
        if self.isDeleted():
            return
        logger.debug("Collecting relevant %ss for %r %s",
                     attributeName, self, self)

        # Collect possible values. The collector method adds tuples to the
        # contenders list; each tuple starts with a value to sort by, and
        # ends with the attribute value to assign and the name of the attribute
        # it came from (which will be used later to pick a displayable string
        # to describe the source of the value).
        #
        # Examples: if we sort by the attribute value, only two values are
        # needed in the tuple: eg, (aDate, 'dateField). If the picking happens
        # based on an additional value (or values), the sort value(s) come
        # before the attribute value: eg (1, 'me@ex.com', 'to'),
        # (2, 'you@ex.com', 'from'). This works because sort sorts by the
        # values in order, and we access the attribute value and name using
        # negative indexes (so contender[-2] is the value, contender[-1] is
        # the name).
        contenders = []
        collectorMethod(contenders)

        # Now that we have the contenders, pick one.
        contenderCount = len(contenders)
        if contenderCount == 0:
            # No contenders: set the default, or delete the value if we don't
            # have one.
            if default is Nil:
                if hasattr(self, attributeName):
                    delattr(self, attributeName)
            else:
                setattr(self, attributeName, default)
            setattr(self, sourceAttributeName, '')
            logger.debug("No relevant %s for %r %s", attributeName, self, self)
            return
        elif contenderCount == 1:
            # We have exactly one possibility; just use it.
            result = contenders[0]
        else:
            # More than one: pick and choose.
            if picker:
                # Let the picker sort and choose
                result = picker(contenders)
            else:
                # No picker - use the first one.
                contenders.sort()
                result = contenders[0]

        logger.debug("Relevant %s for %r %s is %s", attributeName, self, self, result)
        assert result[-2] is not None
        setattr(self, attributeName, result[-2])
        setattr(self, sourceAttributeName, result[-1])

    def addDisplayWhos(self, whos):
        # Eventually, when 'creator' is supported, we'll add it here with a
        # very low priority. For now, an empty 'whos' list will result in no
        # 'who' column display, which is what we want.
        pass

    def updateDisplayWho(self, op, attr):
        self._updateCommonAttribute('displayWho', 'displayWhoSource', self.addDisplayWhos)

    def addDisplayDates(self, dates):
        from osaf.pim.reminders import Remindable
        Remindable(self).addDisplayDates(dates)

    def updateDisplayDate(self, op, attr):
        def picker(contenders):
            # We want to pick the first date after 'now'
            nowTuple = (datetime.now(tz=ICUtzinfo.default), 'now')
            contenders.append(nowTuple)
            contenders.sort()
            nowIndex = contenders.index(nowTuple)
            try:
                result = contenders[nowIndex+1]
            except IndexError:
                result = contenders[nowIndex-1]
            return result

        self._updateCommonAttribute('displayDate', 'displayDateSource',
                                    self.addDisplayDates, picker=picker)

    @schema.observer(lastModified)
    def onLastModifiedChanged(self, op, attr):
        self.updateDisplayDate(op, attr)

    @schema.observer(triageStatus)
    def setTriageStatusChanged(self, op='set', attribute=None, when=None):
        """
        Update triageStatusChanged, which is the number of seconds since the
        epoch that triageStatus was changed, negated for proper sort order.
        As a schema.observer of triageStatus, it's called automatically, but
        can also be called directly to set a specific time:
           item.setTriageStatusChanged(when=someDateTime)
        """
        self._setChangedTime('triageStatusChanged', when=when)

    @schema.observer(_unpurgedTriageStatus)
    def setUnpurgedTriageStatusChanged(self, op='set', attribute=None, when=None):
        """ Just like setTriageStatusChanged, but for the unpurged status """
        self._setChangedTime('_unpurgedTriageStatusChanged', when=when)

    def _setChangedTime(self, attributeName, when=None):
        """
        Common code for setTriageStatusChanged and 
        setUnpurgedTriageStatusChanged
        """
        # Don't if we're in the middle of sharing...
        if getattr(self, '_share_importing', False):
            return

        when = when or datetime.now(tz=ICUtzinfo.default)
        setattr(self, attributeName, -time.mktime(when.utctimetuple()))

    def applyUnpurgedTriageStatus(self):
       """ If this item has unpurged status, purge it. """
       _unpurged = getattr(self, '_unpurgedTriageStatus', None)
       if _unpurged is not None:
           self.triageStatus = _unpurged
           self.triageStatusChanged = self._unpurgedTriageStatusChanged
           del self._unpurgedTriageStatus
           del self._unpurgedTriageStatusChanged

    def getBasedAttributes(self, attribute):
        """ Determine the schema attributes that affect this attribute
        (which might be a Calculated attribute) """
        # Recurse to handle redirection if necessary
        attr = self.itsKind.getAttribute(attribute, True)

        # If it's Calculated, see what it's based on;
        # otherwise, just return a list containing its own name.
        descriptor = getattr(self.__class__, attribute, None)
        try:
            basedOn = descriptor.basedOn
        except AttributeError:
            return (attribute,)
        else:
            return tuple(desc.name for desc in basedOn)



    def isAttributeModifiable(self, attribute):
        # fast path -- item is unshared; have at it!
        if not self.sharedIn:
            return True

        # slow path -- item is shared; we need to look at all the *inbound*
        # shares this item participates in -- if *any* of those inbound shares
        # are writable, the attribute is modifiable; otherwise, if *all* of
        # those inbound shares are read-only, but none of those shares
        # actually *share* that attribute (i.e., it's being filtered either
        # by sharing cloud or explicit filter), then it's modifiable.
        me = schema.ns("osaf.pim", self.itsView).currentContact.item
        basedAttributeNames = None # we'll look these up if necessary
        isSharedInAnyReadOnlyShares = False
        for share in self.sharedIn:
            if getattr(share, 'sharer', None) is not me:   # inbound share
                if share.mode in ('put', 'both'):   # writable share
                    return True
                else:                               # read-only share
                    # We found a read-only share; this attribute isn't
                    # modifiable if it's one of the attributes shared for
                    # this item in this share. (First, map this attribute to
                    # the 'real' attributes it depends on, if we haven't yet.)
                    if basedAttributeNames is None:
                        basedAttributeNames = self.getBasedAttributes(attribute)
                    for attr in basedAttributeNames:
                        if attr in share.getSharedAttributes(self.itsKind):
                            isSharedInAnyReadOnlyShares = True

        return not isSharedInAnyReadOnlyShares

class Tag(ContentItem):

    schema.kindInfo(
        description =
            "A generic tag object that can be associated with any ContentItem"
    )

    items = schema.Sequence(
        description='All the ContentItems associated with this Tag',
        inverse=ContentItem.tags,
        initialValue=[]
    )

    supertags = schema.Sequence(
        description='Allows a tag hierarchy',
        initialValue=[]
    )

    subtags = schema.Sequence(
        description='Allows a tag hierarchy',
        inverse=supertags,
        initialValue=[]
    )


class Project(ContentItem):

    schema.kindInfo(
        description =
            "Users can create projects to help organize their work. Users can "
            "take content items (like tasks and mail messages) and assign "
            "them to different projects.\n\n"
            "Examples:\n"
            '   my "Housewarming Party" project\n'
            "   my department's \"Move to new building\" project\n"
            "   my company's \"Open Seattle Store\" project\n"
    )

    parentProject = schema.One(
        doc = 'Projects can be organized into hierarchies. Each project can have one parent.',
    )
    subProjects = schema.Sequence(
        doc = 'Projects can be organized into hierarchies. Each project can have many sub-projects.',
        inverse = parentProject,
    )


class Group(ContentItem):

    schema.kindInfo(
        description =
            "See http://wiki.osafoundation.org/twiki/bin/view/Jungle/CollectionProject\n\n"
            "Issues:\n"
            '   We still need to work out some issues about how '
                '"playlists"/"item collections" are modeled.\n'
            '   We need to find a name for these things.\n'
    )

class UserNotification(ContentItem):

    schema.kindInfo(
        description = "Notifications meant for the user to see"
    )

    items = schema.Sequence(inverse=ContentItem.notifications)

    timestamp = schema.One(schema.DateTimeTZ,
        doc="DateTime this notification ocurred"
    )

    def __init__(self, *args, **kw):
        super(UserNotification, self).__init__(*args, **kw)
        if not hasattr(self, 'timestamp'):
            self.timestamp = datetime.now(ICUtzinfo.default)

    @schema.observer(timestamp)
    def onTimestampChanged(self, op, attr):
        self.updateDisplayDate(op, attr)

    def addDisplayDates(self, dates):
        super(UserNotification, self).addDisplayDates(dates)
        timestamp = getattr(self, 'timestamp', None)
        if timestamp is not None:
            dates.append((timestamp, 'timestamp'))


class Principal(ContentItem):
    # @@@MOR These should be moved out so that authentication can be made
    # more general, but they're here for convenience for now.
    login = schema.One(schema.Text)
    password = schema.One(schema.Text)


    members = schema.Sequence(initialValue=[])
    memberOf = schema.Sequence(initialValue=[], inverse=members)

    def isMemberOf(self, pid):

        if self.itsUUID == pid:
            return True

        for member in getattr(self.itsView.findUUID(pid), 'members', []):
            if self.isMemberOf(member.itsUUID):
                return True

        return False
