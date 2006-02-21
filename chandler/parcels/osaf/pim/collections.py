__copyright__ = "Copyright (c) 2003-2004 Open Source Applications Foundation"
__license__ = "http://osafoundation.org/Chandler_0.1_license_terms.htm"
__parcel__ = "osaf.pim"

from application import schema
from repository.item.Sets import Set, MultiUnion, Union, MultiIntersection, Intersection, Difference, KindSet, FilteredSet
from repository.item.Item import Item
from chandlerdb.item.ItemError import NoSuchIndexError
from osaf.pim import items
import logging, os, re
from osaf.pim.structs import ColorType

logger = logging.getLogger(__name__)
DEBUG = logger.getEffectiveLevel() <= logging.DEBUG


class CollectionColors(schema.Item):
    """
    Temporarily put the CollectionColors here until we refactor collection
    to remove display information
    """
    colors           = schema.Sequence (ColorType)
    colorIndex       = schema.One (schema.Integer)

    def nextColor (self):
        color = self.colors [self.colorIndex]
        self.colorIndex += 1
        if self.colorIndex == len (self.colors):
            self.colorIndex = 0
        return color


class AbstractCollection(items.ContentItem):

    """
    The base class for all Collection types.

    Collections are items and provide an API for client to subscribe
    to their notifications.

    The general usage paradigm for collections is to instantiate a collection
    and then set the values of attributes as necessary (instead of during
    construction)
    """
    schema.kindInfo(
        displayName=u"AbstractCollection"
    )

    # the repository set underlying the Collection
    rep = schema.One(schema.TypeReference('//Schema/Core/AbstractSet'))
    # the set of subscribers 
    subscribers = schema.Many(initialValue=set())

    """
      The following collection attributes may be moved once the dust
    settles on pje's external attribute mechanism
    """
    renameable              = schema.One(schema.Boolean, defaultValue = True)
    color                   = schema.One(ColorType)
    iconName                = schema.One(schema.Text)
    iconNameHasKindVariant  = schema.One(schema.Boolean, defaultValue = False)
    colorizeIcon            = schema.One(schema.Boolean, defaultValue = True)
    dontDisplayAsCalendar   = schema.One(schema.Boolean, defaultValue = False)
    outOfTheBoxCollection   = schema.One(schema.Boolean, defaultValue = False)
    """
      A dictionary mapping a KindName string to a new displayName.
    """
    displayNameAlternatives = schema.Mapping (schema.Text)

    collectionList = schema.Sequence(
        'AbstractCollection',
        doc="Views, e.g. the Calendar, that display collections need to know "
            "which collection are combined to make up the calendar. collectionList"
            "is an optional parameter for this purpose."
    )

    invitees = schema.Sequence(
        "osaf.pim.mail.EmailAddress",
        doc="The people who are being invited to share in this item; filled "
            "in when the user types in the DV's 'invite' box, then cleared on "
            "send (entries copied to the share object).\n\n"
            "Issue: Bad that we have just one of these per item collection, "
            "though an item collection could have multiple shares post-0.5",
        inverse="inviteeOf",
        initialValue=()
    )   

    # redirections 
    about = schema.Descriptor(redirectTo="displayName")

    schema.addClouds(
        copying = schema.Cloud(
            invitees,
            byRef=['contentsOwner']
        ),
        sharing = schema.Cloud( none = ["displayName"] ),
    )

    def setup(self):
        """
        setup the color of a collection
        """
        if not hasattr (self, 'color'):
            self.color = schema.ns('osaf.pim', self.itsView).collectionColors.nextColor()
        return self

    def _collectionChanged(self, op, change, name, other):

        if change == 'dispatch':
            for subscriber in self.subscribers:
                subscriber.onCollectionEvent(op, self, name, other)
        else:
            self.itsView.queueNotification(self, op, change, name, other)
            super(AbstractCollection, self)._collectionChanged(op, change, name, other)

    def __contains__(self, *args, **kwds):
        return self.rep.__contains__(*args, **kwds)

    def addIndex (self, *args, **kwds):
        return self.rep.addIndex(*args, **kwds)

    def getByIndex (self, *args, **kwds):
        return self.rep.getByIndex(*args, **kwds)

    def findInIndex (self, *args, **kwds):
        return self.rep.findInIndex(*args, **kwds)

    def __iter__(self, *args, **kwds):
        return self.rep.__iter__(*args, **kwds)

    def iterkeys(self, *args, **kwds):
       return self.rep.iterkeys(*args, **kwds)

    def itervalues(self, *args, **kwds):
        return self.rep.itervalues(*args, **kwds)

    def setDescending(self, *args, **kwds):
        return self.rep.setDescending(*args, **kwds)

    def isDescending(self, *args, **kwds):
        return self.rep.isDescending(*args, **kwds)

    def __nonzero__(self):
        return True

    def __str__(self):
        """ for debugging """
        return "<%s%s:%s %s>" %(type(self).__name__, "", self.itsName,
                            self.itsUUID.str16())

    def _inspect(self, indent=0):
        """ more debugging """
    
        indexes = self.rep._indexes
        if indexes is None:
            indexes = ''
        else:
            indexes = ', '.join((str(t) for t in indexes.iteritems()))
        return "%s%s\n%s  indexes: %s%s" %('  ' * indent, self._repr_(),
                                           '  ' * indent, indexes,
                                           self._inspect_(indent + 1))
    
    def _inspect_(self, indent):
        """ more debugging """
        raise NotImplementedError, "%s._inspect_" %(type(self))
        
    def isEmpty(self):
        """
        Return True if the collection has no members
        """
        try:
            # eventually Andi will give us a better API for this so we
            # don't have to make an iterator object
            iter(self).next()
            return False
        except StopIteration:
            return True

    def isReadOnly(self):
        """
        Return True iff participating in only read-only shares
        """
        if not self.shares:
            return False

        for share in self.shares:
            if share.mode in ('put', 'both'):
                return False

        return True

    readOnly = property(isReadOnly)


class KindCollection(AbstractCollection):
    """
    A Collection of all of the items of a particular kind

    The C{kind} attribute to the C{Kind} determines the C{Kind} of the items
    in the C{KindCollection}

    The C{recursive} attribute determines whether items of subkinds are
    included (C{True}) in the C{KindCollection}
    """
    schema.kindInfo(
        displayName=u"KindCollection"
    )

    kind = schema.One(schema.TypeReference('//Schema/Core/Kind'), initialValue=None)
    recursive = schema.One(schema.Boolean, initialValue=False)

    def onValueChanged(self, name):
        if name == "kind" or name == "recursive":
            self.rep = KindSet(self.kind, self.recursive)

    def _inspect_(self, indent):
        """ more debugging """

        return "\n%skind: %s" %('  ' * indent, self.kind.itsPath)


def installParcel(parcel, old_version = None):
    """
    Parcel install time hook
    """
    pass


class ListCollection(AbstractCollection):
    """
    A collection that contains only those items that are explicitly added to it.

    Backed by a ref-collection
    """
    schema.kindInfo(
        displayName=u"ListCollection"
    )

    refCollection = schema.Sequence(otherName='collections',initialValue=[])

    trashFor = schema.Sequence('InclusionExclusionCollection', otherName='trash', initialValue=[])

    def __init__(self, *args, **kw):
        super(ListCollection, self).__init__(*args, **kw)
        self.rep = Set((self,'refCollection'))

    def add(self, item):
        self.refCollection.add(item)

    def clear(self):
        self.refCollection.clear()

    def first(self):
        return self.refCollection.first()

    def remove(self, item):
        self.refCollection.remove(item)

    def empty(self):
        for item in self:
            item.delete(True)

    def __len__(self):
        return len(self.refCollection)

    def _inspect_(self, indent):
        """ more debugging """
    
        return ''


class DifferenceCollection(AbstractCollection):
    """
    A collection containing the set theoretic difference of two collections

    Assign the C{sources} attribute (a list) with the collections to be
    differenced
    """
    schema.kindInfo(
        displayName=u"DifferenceCollection"
    )

    sources = schema.Sequence(AbstractCollection, initialValue=[])

    schema.addClouds(
        copying = schema.Cloud(byCloud=[sources]),
    )

    def onValueChanged(self, name):
        if name == "sources":
            if self.sources != None:
                assert len(self.sources) <= 2, "DifferenceCollection can only handle 2 sources"

                if len(self.sources) == 2:
                    self.rep = Difference((self.sources[0], "rep"),(self.sources[1], "rep"))

    def _inspect_(self, indent):
        """ more debugging """

        return '\n%s' %('\n'.join([src._inspect(indent) for src in self.sources]))


class UnionCollection(AbstractCollection):
    """
    A collection containing the set theoretic union of at least 2 collections

    Assign the C{sources} attribute (a list) with the collections to be
    unioned
    """
    schema.kindInfo(
        displayName=u"UnionCollection"
    )

    sources = schema.Sequence(AbstractCollection, initialValue=[])

    schema.addClouds(
        copying = schema.Cloud(byCloud=[sources]),
    )

    def _sourcesChanged(self):
        num_sources = len(self.sources)

        if num_sources == 0:
            self.rep = MultiUnion()
        elif num_sources == 2:
            self.rep = Union((self.sources[0],"rep"),(self.sources[1],"rep"))
        else:
            self.rep = MultiUnion(*[(i, "rep") for i in self.sources])

    def addSource(self, source):

        if source not in self.sources:
            self.sources.append(source)
            self._sourcesChanged()

            view = self.itsView
            for uuid in source.iterkeys():
                view._notifyChange(self.rep.sourceChanged,
                                   'add', 'collection', source, 'rep', False,
                                   uuid)

    def removeSource(self, source):

        if source in self.sources:
            view = self.itsView
            for uuid in source.iterkeys():
                view._notifyChange(self.rep.sourceChanged,
                                   'remove', 'collection', source, 'rep', False,
                                   uuid)

            self.sources.remove(source)
            self._sourcesChanged()

    def _inspect_(self, indent):
        """ more debugging """

        return '\n%s' %('\n'.join([src._inspect(indent) for src in self.sources]))


class IntersectionCollection(AbstractCollection):
    """
    A collection containing the set theoretic intersection of at least 2 collections

    Assign the C{sources} attribute (a list) with the collections to be
    intersected
    """
    schema.kindInfo(
        displayName=u"IntersectionCollection"
    )

    sources = schema.Sequence(AbstractCollection, initialValue=[])

    schema.addClouds(
        copying = schema.Cloud(byCloud=[sources]),
    )

    def onValueChanged(self, name):
        if name == "sources":
            if self.sources != None and len(self.sources) > 1:
                # optimize for the binary case
                if len(self.sources) == 2:
                    self.rep = Intersection((self.sources[0],"rep"),(self.sources[1],"rep"))
                else:
                    self.rep = MultiIntersection(*[(i, "rep") for i in self.sources])
    def _inspect_(self, indent):
        """ more debugging """

        return '\n%s' %('\n'.join([src._inspect(indent) for src in self.sources]))


# regular expression for finding the attribute name used by
# hasLocalAttributeValue
delPat = re.compile(".*(hasLocalAttributeValue|hasTrueAttributeValue)\(([^\)]*)\).*")

class FilteredCollection(AbstractCollection):
    """
    A collection which is the result of applying a boolean predicate
    to every item of another collection
    
    Assign the C{source} attribute to specify the collection to be filtered

    Assign the C{filterExpression} attribute with a string containing
    a Python expression.  If the expression returns C{True} for an
    item in the C{source} it will be in the FilteredCollection.

    Assign the C{filterAttributes} attribute with a list of attribute
    names (Strings), which are accessed by the C{filterExpression}.
    Failure to provide this list will result in missing notifications
    """
    schema.kindInfo(
        displayName=u"FilteredCollection"
    )

    source = schema.One(AbstractCollection, initialValue=None)
    filterExpression = schema.One(schema.Text, initialValue="")
    filterAttributes = schema.Sequence(schema.Text, initialValue=[])

    schema.addClouds(
        copying = schema.Cloud(byCloud=[source]),
    )


    def onValueChanged(self, name):
        if name == "source" or name == "filterExpression" or name =="filterAttributes":
            if self.source != None:
                if self.filterExpression != u"" and self.filterAttributes != []:

                    # see if the expression contains hasLocalAttributeValue
                    m = delPat.match(self.filterExpression)
                    if m:
                        delatt = m.group(2)
                        if delatt is not None:
                            # strip leading quotes
                            if delatt.startswith("'") or delatt.startswith('"'):
                                delatt = delatt[1:-1] 
                            delatt = [ delatt.replace("item.","") ]
                    else:
                        delatt = []
                    attrTuples = []

                    # build a list of (item, monitor-operation) tuples
                    for i in self.filterAttributes:
                        attrTuples.append((i, "set"))
                        for j in delatt:
                            attrTuples.append((j, "remove"))

                    self.rep = FilteredSet((self.source, "rep"), self.filterExpression, attrTuples)

    def _inspect_(self, indent):
        """ more debugging """

        return "\n%sfilter: %s\n%s attrs: %s\n%s" %('  ' * indent, self.filterExpression, '  ' * indent, ', '.join(self.filterAttributes), self.source._inspect(indent))


class InclusionExclusionCollection(DifferenceCollection):
    """
    InclusionExclusionCollections implement inclusions, exclusions, source,
    and trash along with methods for add and remove
    """

    inclusions = schema.One(AbstractCollection)
    exclusions = schema.One(AbstractCollection)
    trash = schema.One(ListCollection, otherName='trashFor', initialValue=None)

    def add (self, item):
        """
          Add an item to the collection
        """

        if DEBUG:
            logger.debug("Adding %s to %s...",
                         item.getItemDisplayName().encode('ascii', 'replace'),
                         self.getItemDisplayName().encode('ascii', 'replace'))
        self.inclusions.add(item)

        if item in self.exclusions:
            if DEBUG:
                logger.debug("...removing from exclusions (%s)",
                             self.exclusions.getItemDisplayName().encode('ascii', 'replace'))
            self.exclusions.remove(item)

        # If a trash is associated with this collection, remove the item
        # from the trash.  This has the additional benefit of having the item
        # reappear in any collection which has the item in its inclusions

        if self.trash is not None and item in self.trash:
            if DEBUG:
                logger.debug("...removing from trash (%s)",
                             self.trash.getItemDisplayName().encode('ascii', 'replace'))
            self.trash.remove(item)

        if DEBUG:
            logger.debug("...done adding %s to %s",
                         item.getItemDisplayName().encode('ascii', 'replace'),
                         self.getItemDisplayName().encode('ascii', 'replace'))

    def remove (self, item):
        """
          Remove an item from the collection
        """

        if DEBUG:
            logger.debug("Removing %s from %s...",
                         item.getItemDisplayName().encode('ascii', 'replace'),
                         self.getItemDisplayName().encode('ascii', 'replace'))

        # Before we actually add this item to our exclusions list, let's see
        # how many other collections (that share our trash) this item is in.
        # If the item is only in this collection, we'll add it to the trash
        # later on.  We need to make this check now because in the following
        # step when we add the item to our exclusions list, that could
        # immediately add the item to the All collection which would be bad.
        # Bug 4551

        addToTrash = False
        if self.trash is not None:
            addToTrash = True
            for collection in self.trash.trashFor:
                if collection is not self and item in collection:
                    addToTrash = False
                    break

        if DEBUG:
            logger.debug("...adding to exclusions (%s)",
                         self.exclusions.getItemDisplayName().encode('ascii', 'replace'))
        self.exclusions.add (item)

        if item in self.inclusions:
            if DEBUG:
                logger.debug("...removing from inclusions (%s)",
                             self.inclusions.getItemDisplayName().encode('ascii', 'replace'))
            self.inclusions.remove (item)

        if addToTrash:
            if DEBUG:
                logger.debug("...adding to trash (%s)",
                             self.trash.getItemDisplayName().encode('ascii', 'replace'))
            self.trash.add(item)

        if DEBUG:
            logger.debug("...done removing %s from %s",
                         item.getItemDisplayName().encode('ascii', 'replace'),
                         self.getItemDisplayName().encode('ascii', 'replace'))

    def setup(self, source=None, exclusions=None,  trash="trashCollection"):
        """
        setup all the extra parts of a InclusionExclusionCollection. Sets the
        color, source, exclusions and trash collections. source, exclusions and
        trash may be collections or strings. If they are strings, then the
        corresponding collection is looked up in the osaf.pim namespace
        """

        def collectionLookup (collection):
            if isinstance (collection, str):
                collection = getattr (pimNameSpace, collection)
            return collection

        pimNameSpace = schema.ns('osaf.pim', self.itsView)
        
        source = collectionLookup (source)
        exclusions = collectionLookup (exclusions)
        trash = collectionLookup (trash)

        super (InclusionExclusionCollection, self).setup()

        if source is None:
            innerSource = ListCollection(itsParent=self,
                                         displayName=u"(Inclusions)")
            self.inclusions = innerSource
        else:
            innerSource = UnionCollection(itsParent=self,
                displayName=u"(Union of source and inclusions)")
            innerSource.addSource(source)
            inclusions = ListCollection(itsParent=self,
                                        displayName=u"(Inclusions)")
            innerSource.addSource(inclusions)
            self.inclusions = inclusions


        # Typically we will create an exclusions ListCollection; however,
        # a collection like 'All' will instead want to use the Trash collection
        # for exclusions

        if exclusions is None:
            exclusions = ListCollection(itsParent=self,
                                        displayName=u"(Exclusions)")
        self.exclusions = exclusions

        # You can designate a certain ListCollection to be used for this
        # collection's trash; in this case, an additional DifferenceCollection
        # will be created to remove any trash items from this collection. Any
        # collections which share a trash get the following benefits:
        # - Adding an item to the trash will make the item disappear from
        #   collections sharing that trash collection
        # - When an item is removed from a collection, it will automatically
        #   be moved to the trash if it doesn't appear in any collection which
        #   shares that trash

        if trash is not None:
            outerSource = DifferenceCollection(itsParent=self,
                displayName=u"(Difference between source and trash)")
            outerSource.sources = [innerSource, trash]
            self.trash = trash
        else:
            outerSource = innerSource
            self.trash = exclusions

        self.sources = [outerSource, exclusions]

        return self


class IndexedSelectionCollection (AbstractCollection):
    """
    A collection that adds an index, e.g.for sorting items, a
    selection and visiblity attribute to another source collection.
    """

    indexName   = schema.One(schema.Text, initialValue="__adhoc__")
    source      = schema.One(AbstractCollection, defaultValue=None)

    def getIndex (self):
        """
        Get the index. If it doesn't exist, create. Also create a RangeSet
        for storing the selection on the index

        If the C{indexName} attribute of this collection is set to
        "__adhoc__" then a numeric index will be created.  Otherwise
        the C{indexName} attribute should contain the name of the
        attribute (of an item) to be indexed.
        """
        if not self.rep.hasIndex (self.indexName):
            if self.indexName == "__adhoc__":
                self.rep.addIndex (self.indexName, 'numeric')
            else:
                self.rep.addIndex (self.indexName, 'attribute', attribute=self.indexName)
            self.rep.setRanges (self.indexName, [])
        return self.rep.getIndex(self.indexName)

    def __len__(self):
        if hasattr(self, 'rep'):
            # Get the index. It's necessary to get the length, and if
            # it doesn't exist getIndex will create it.
            self.getIndex()
            return len(self.rep)
        return 0

    def moveItemToLocation (self, item, location):
        """
        Moves an item to a new C{location} in an __adhoc__ index.
        """
        if location == 0:
            # Get the index. It's necessary to get the length, and if
            # it doesn't exist getIndex will create it.
            self.getIndex()
            before = None
        else:
            before = self [location - 1]
        self.rep.placeInIndex (item, before, self.indexName)             

    #
    # General selection methods
    # 

    def isSelectionEmpty(self):
        return len(self.getSelectionRanges()) == 0

    def clearSelection(self):
        return self.setSelectionRanges([])

    #
    # Range-based selection methods
    # 

    def getSelectionRanges (self):
        """
        Return the ranges associated with the current index as an
        array of tuples, where each tuple representsa start and end of
        the range.
        """
        return self.getIndex().getRanges()
        
    def setSelectionRanges (self, ranges):
        """
        Sets the ranges associated with the current index with
        C(ranges) which should be an array of tuples, where each tuple
        represents a start and end of the range.  The ranges must be
        sorted ascending, non-overlapping and postive.
        """
        self.rep.setRanges(self.indexName, ranges)

    def isSelected (self, range):
        """
        Returns True if the C(range) is completely inside the selected
        ranges of the index.  C(range) may be a tuple: (start, end) or
        an integer index, where negative indexing works like Python
        indexing.
        """
        return self.getIndex().isInRanges(range)

    def addSelectionRange (self, range):
        """
        Selects a C(range) of indexes. C(range) may be a tuple:
        (start, end) or an integer index, where negative indexing
        works like Python indexing.
        """
        self.rep.addRange(self.indexName, range)

    def removeSelectionRange (self, range):
        """
        unselects a C(range) of indexes. C(range) may be a tuple:
        (start, end) or an integer index, where negative indexing
        works like Python indexing..
        """
        self.rep.removeRange(self.indexName, range)
    #
    # Item-based selection methods
    #
    
    def setSelectionToItem (self, item):
        """
        Sets the entire selection to include only the C(item).
        """
        index = self.index (item)
        self.rep.setRanges(self.indexName, [(index, index)])

    def getFirstSelectedItem (self):
        """
        Returns the first selected item in the index or None if there
        is no selection.
        """
        index = self.getIndex()._ranges.firstSelectedIndex()
        if index == None:
            return None
        return self[index]

    def isItemSelected(self, item):
        """
        returns True/False based on if the item is actually selected or not
        """
        return self.isSelected(self.index(item))

    def iterSelection(self):
        """
        Generator to get the selection
        """
        ranges = self.getSelectionRanges()
        if ranges is not None:
            for start,end in ranges:
                for idx in range(start,end+1):
                    yield self[idx]

    def selectItem (self, item):
        """
        Selects an C(item) in the index.
        """
        self.addSelectionRange (self.index (item))

    def unselectItem (self, item):
        """
        unSelects an C(item) in the index.
        """
        self.removeSelectionRange (self.index (item))

    #
    # index-based methods
    #

    def __getitem__ (self, index):
        """
        Support indexing using []
        """
        # Get the index. It's necessary to get the length, and if it doesn't exist
        # getIndex will create it.
        self.getIndex()
        return self.rep.getByIndex (self.indexName, index)

    def index (self, item):
        """
        Return the position of item in the index.
        """

        # Get the index. It's necessary to get the length, and if it doesn't
        # exist getIndex will create it.

        self.getIndex()
        return self.rep.positionInIndex(self.indexName, item)

    def onValueChanged(self, name):
        if name == "source" and self.source != None:
            self.rep = Set((self.source, "rep"))

    def add(self, item):
        self.source.add(item)

    def clear(self):
        self.source.clear()

    def first(self):
        return self.source.first()

    def remove(self, item):
        self.source.remove(item)

    def empty(self):
        self.source.empty()

    def _inspect_(self, indent):
        """ more debugging """
    
        return "\n%s" %(self.source._inspect(indent))
