
__revision__  = "$Revision$"
__date__      = "$Date$"
__copyright__ = "Copyright (c) 2002 Open Source Applications Foundation"
__license__   = "http://osafoundation.org/Chandler_0.1_license_terms.htm"

import cStringIO

from datetime import datetime
from struct import pack

from bsddb.db import DBLockDeadlockError, DBNotFoundError
from bsddb.db import DB_DIRTY_READ, DB_LOCK_WRITE
from dbxml import XmlDocument, XmlValue

from repository.item.Item import Item
from repository.item.Values import Values, ItemValue
from repository.item.ItemRef import RefDict, TransientRefDict
from repository.persistence.Repository import Repository, RepositoryError
from repository.persistence.Repository import VersionConflictError
from repository.persistence.Repository import OnDemandRepositoryView
from repository.persistence.Repository import RepositoryNotifications
from repository.util.UUID import UUID
from repository.util.SAX import XMLGenerator
from repository.util.Lob import Text, Binary
from repository.util.Streams import ConcatenatedInputStream, NullInputStream


class XMLRepositoryView(OnDemandRepositoryView):

    def __init__(self, repository):

        super(XMLRepositoryView, self).__init__(repository)

        self._log = []
        self._notifications = RepositoryNotifications(repository)
        
    def logItem(self, item):
        
        if super(XMLRepositoryView, self).logItem(item):
            self._log.append(item)
            return True
        
        return False

    def _newItems(self):

        for item in self._log:
            if item.isNew():
                yield item

    def dirlog(self):

        for item in self._log:
            print item.itsPath

    def cancel(self):

        for item in self._log:
            if item.isDeleted():
                del self._deletedRegistry[item.itsUUID]
                item._status &= ~Item.DELETED
            else:
                item.setDirty(0)
                item._unloadItem()

        del self._log[:]
        self._notRoots.clear()

        self.prune(10000)

    def queryItems(self, query, load=True):

        store = self.repository.store
        items = []
        
        for doc in store.queryItems(self.version, query):
            uuid = store.getDocUUID(doc)
            if not uuid in self._deletedRegistry:
                # load and doc, trick to pass doc directly to find
                item = self.find(uuid, load=load and doc)
                if item is not None:
                    items.append(item)

        return items

    def searchItems(self, query, load=True):

        store = self.repository.store
        results = []
        docs = store.searchItems(self.version, query)
        for (uuid, (ver, attribute)) in docs.iteritems():
            if not uuid in self._deletedRegistry:
                item = self.find(uuid, load=load)
                if item is not None:
                    results.append((item, attribute))

        return results


class XMLRepositoryLocalView(XMLRepositoryView):

    def __init__(self, repository):

        super(XMLRepositoryLocalView, self).__init__(repository)

        self._indexWriter = None
        self._lock_id = self.repository._env.lock_id()
        
    def createRefDict(self, item, name, otherName, persist):

        if persist:
            return XMLRefDict(self, item, name, otherName)
        else:
            return TransientRefDict(item, name, otherName)

    def getLobType(self, mode):

        if mode == 'text':
            return XMLText
        if mode == 'binary':
            return XMLBinary

        raise ValueError, mode

    def _startTransaction(self):

        return self.repository.store._startTransaction()

    def _commitTransaction(self):

        if self._indexWriter is not None:
            self.repository.store._index.optimizeIndex(self._indexWriter)
            self._indexWriter.close()
            self._indexWriter = None
            
        self.repository.store._commitTransaction()

    def _abortTransaction(self):

        if self._indexWriter is not None:
            self._indexWriter.close()
            self._indexWriter = None
            
        self.repository.store._abortTransaction()

    def _getIndexWriter(self):

        if self._indexWriter is None:
            store = self.repository.store
            if store.txn is None:
                raise RepositoryError, "Can't index outside transaction"
            self._indexWriter = store._index.getIndexWriter()

        return self._indexWriter

    def commit(self):

        repository = self.repository
        store = repository.store
        data = store._data
        names = store._names
        versions = store._versions
        history = store._history
        env = repository._env

        self._notifications.clear()
        histNotifications = None
        
        before = datetime.now()
        count = len(self._log)
        size = 0L
        txnStarted = False
        lock = None
        
        while True:
            try:
                txnStarted = self._startTransaction()
                unloads = {}

                newVersion = versions.getVersion()
                if count > 0:
                    lock = env.lock_get(self._lock_id, self.itsUUID._uuid,
                                        DB_LOCK_WRITE)
                    newVersion += 1
                    versions.put(self.itsUUID._uuid, pack('>l', ~newVersion))

                    ood = {}
                    for item in self._log:
                        if not item.isNew():
                            uuid = item._uuid
                            version = versions.getDocVersion(uuid)
                            assert version is not None
                            if version > item._version:
                                ood[uuid] = item

                    if ood:
                        self._mergeItems(ood, self.version, newVersion,
                                         history)
                
                    for item in self._log:
                        size += self._saveItem(item, newVersion,
                                               data, names, versions, history,
                                               ood)

                if newVersion > self.version:
                    histNotifications = RepositoryNotifications(repository)
                    
                    def unload(uuid, version, docId, status, parent):

                        if status & Item.DELETED:
                            histNotifications.history(uuid, 'deleted',
                                                      parent=parent)
                        elif status & Item.NEW:
                            histNotifications.history(uuid, 'added')
                        else:
                            histNotifications.history(uuid, 'changed')

                        item = self._registry.get(uuid)
                        if (item is not None and
                            not item._status & Item.SAVED and
                            item._version < newVersion):
                            unloads[item._uuid] = item

                    history.apply(unload, self.version, newVersion)
            
                if txnStarted:
                    self._commitTransaction()

                if lock:
                    env.lock_put(lock)
                    lock = None

                break

            except DBLockDeadlockError:
                self.logger.info('restarting commit aborted by deadlock')
                if txnStarted:
                    self._abortTransaction()
                if lock:
                    env.lock_put(lock)
                    lock = None

                continue
            
            except:
                self.logger.exception('aborting transaction (%ld bytes)', size)
                if txnStarted:
                    self._abortTransaction()
                if lock:
                    env.lock_put(lock)
                    lock = None

                raise

        if self._log:
            for item in self._log:
                if not item._status & Item.MERGED:
                    item._version = newVersion
                item._status &= ~(Item.NEW | Item.DIRTY |
                                  Item.MERGED | Item.SAVED)
            del self._log[:]

        if newVersion > self.version:
            self.logger.debug('refreshing view from version %d to %d',
                              self.version, newVersion)
            self.version = newVersion
            for item in unloads.itervalues():
                self.logger.debug('unloading version %d of %s',
                                  item._version, item)
                item._unloadItem()
                    
        self._notRoots.clear()

        if histNotifications is not None:
            histNotifications.dispatchHistory()
        self._notifications.dispatchChanges()

        if count > 0:
            self.logger.info('%s committed %d items (%ld bytes) in %s',
                             self, count, size,
                             datetime.now() - before)
        self.prune(10000)

    def _saveItem(self, item, newVersion, data, names, versions, history, ood):

        uuid = item._uuid
        isNew = item.isNew()
        isDeleted = item.isDeleted()
        isDebug = self.isDebug()
        
        if isDeleted:
            del self._deletedRegistry[uuid]
            if isNew:
                return 0

        if isDebug:
            self.logger.debug('saving version %d of %s',
                              newVersion, item.itsPath)

        if uuid in ood:
            docId, oldDirty, newDirty = ood[uuid]
            mergeWith = (data.getDocument(docId).getContent(),
                         oldDirty, newDirty)
            if isDebug:
                self.logger.debug('merging %s (%0.4x:%0.4x) with newest version',
                                  item.itsPath, oldDirty, newDirty)
        else:
            mergeWith = None
            
        out = cStringIO.StringIO()
        generator = XMLGenerator(out, 'utf-8')
        generator.startDocument()
        item._saveItem(generator, newVersion, mergeWith)
        generator.endDocument()
        content = out.getvalue()
        out.close()

        size = len(content)

        doc = XmlDocument()
        doc.setContent(content)
        if isDeleted:
            doc.setMetaData('', '', 'deleted', XmlValue('True'))

        try:
            docId = data.putDocument(doc)
        except:
            self.logger.exception("putDocument failed, xml is: %s", content)
            raise

        if isDeleted:
            parent, name = item.__dict__['_origName']
            versions.setDocVersion(uuid, newVersion, 0)
            history.writeVersion(uuid, newVersion, 0, item._status, parent)
            self._notifications.changed(uuid, 'deleted', parent=parent)
            names.writeName(parent, name, newVersion, None)

        else:
            versions.setDocVersion(uuid, newVersion, docId)
            history.writeVersion(uuid, newVersion, docId, item._status)

            if isNew:
                names.writeName(item.itsParent.itsUUID, item._name,
                                newVersion, uuid)
                self._notifications.changed(uuid, 'added')
            else:
                if '_origName' in item.__dict__:
                    parent, name = item.__dict__['_origName']
                    names.writeName(parent, name, newVersion, None)
                    names.writeName(item.itsParent.itsUUID, item._name,
                                    newVersion, uuid)
                    del item.__dict__['_origName']
                self._notifications.changed(uuid, 'changed')
                    
        return size

    def _mergeItems(self, items, oldVersion, newVersion, history):

        def check(uuid, version, docId, status, parentId):
            item = items.get(uuid)
            if item is not None:
                newDirty = item.getDirty()
                oldDirty = status & item.DIRTY
                if newDirty & oldDirty:
                    raise VersionConflictError, item
                else:
                    if (newDirty == item.VDIRTY or oldDirty == item.VDIRTY or
                        newDirty == item.RDIRTY or oldDirty == item.RDIRTY or
                        newDirty == item.VRDIRTY or oldDirty == item.VRDIRTY):
                        items[uuid] = (docId, oldDirty, newDirty)
                    else:
                        raise NotImplementedError, 'Item %s may be mergeable but this particular merge (0x%x:0x%x) is not implemented yet' %(item.itsPath, newDirty, oldDirty)    

        history.apply(check, oldVersion, newVersion)


class XMLRepositoryClientView(XMLRepositoryView):

    def createRefDict(self, item, name, otherName, persist):

        if persist:
            return XMLClientRefDict(self, item, name, otherName)
        else:
            return TransientRefDict(item, name, otherName)


class XMLRefDict(RefDict):

    class _log(list):

        def append(self, value):
            if len(self) == 0 or value != self[-1]:
                super(XMLRefDict._log, self).append(value)


    def __init__(self, view, item, name, otherName):
        
        self._log = XMLRefDict._log()
        self._item = None
        self._uuid = UUID()
        self.view = view
        self._deletedRefs = {}
        
        super(XMLRefDict, self).__init__(item, name, otherName)

    def _getRepository(self):

        return self.view

    def _loadRef(self, key):

        view = self.view
        
        if view is not view.repository.view:
            raise RepositoryError, 'current thread is not owning thread'

        if key in self._deletedRefs:
            return None

        return self._loadRef_(key)

    def _loadRef_(self, key):

        version = self._item._version
        cursorKey = self._packKey(key)

        return self.view.repository.store._refs.loadRef(version, key,
                                                        cursorKey)

    def _changeRef(self, key, alias=None):

        if not self.view.isLoading():
            self._log.append((0, key, alias))
        
        super(XMLRefDict, self)._changeRef(key, alias)

    def _removeRef(self, key, _detach=False):

        if not self.view.isLoading():
            link = self._get(key, load=False)
            self._log.append((1, key, link._alias))
            self._deletedRefs[key] = key
        else:
            raise ValueError, 'detach during load'

        super(XMLRefDict, self)._removeRef(key, _detach)

    def _writeRef(self, key, version, uuid, previous, next, alias):

        self._value.truncate(0)
        self._value.seek(0)
        if uuid is not None:
            self._writeValue(uuid)
            self._writeValue(previous)
            self._writeValue(next)
            self._writeValue(alias)
        else:
            self._writeValue(None)
        value = self._value.getvalue()
            
        self.view.repository.store._refs.put(self._packKey(key, version),
                                             value)

    def _writeValue(self, value):
        
        if isinstance(value, UUID):
            self._value.write('\0')
            self._value.write(value._uuid)

        elif isinstance(value, str):
            self._value.write('\1')
            self._value.write(pack('>H', len(value)))
            self._value.write(value)

        elif isinstance(value, unicode):
            value = value.encode('utf-8')
            self._value.write('\1')
            self._value.write(pack('>H', len(value)))
            self._value.write(value)

        elif value is None:
            self._value.write('\2')

        else:
            raise NotImplementedError, "value: %s, type: %s" %(value,
                                                               type(value))

    def _eraseRef(self, key):

        self.view.repository.store._refs.delete(self._packKey(key))

    def resolveAlias(self, alias):

        key = None
        
        if self._aliases:
            key = self._aliases.get(alias)

        if key is None:
            view = self.view
            key = view.repository.store._names.readName(self._uuid, alias,
                                                        view.version)

        return key

    def _setItem(self, item):

        if self._item is not None and self._item is not item:
            raise ValueError, 'Item is already set'
        
        self._item = item
        if item is not None:
            self._prepareKey(item._uuid, self._uuid)

    def _packKey(self, key, version=None):

        self._key.truncate(32)
        self._key.seek(0, 2)
        self._key.write(key._uuid)
        if version is not None:
            self._key.write(pack('>l', ~version))

        return self._key.getvalue()

    def _prepareKey(self, uItem, uuid):

        self._uuid = uuid

        self._key = cStringIO.StringIO()
        self._key.write(uItem._uuid)
        self._key.write(uuid._uuid)

        self._value = cStringIO.StringIO()
            
    def _xmlValues(self, generator, version, mode):

        if mode == 'save':
            names = self.view.repository.store._names
            for op, key, oldAlias in self._log:
                try:
                    value = self._get(key, load=False)
                except KeyError:
                    value = None
    
                if op == 0:               # change
                    if value is not None:
                        ref = value._value
                        previous = value._previousKey
                        next = value._nextKey
                        alias = value._alias
    
                        uuid = ref.other(self._item).itsUUID
                        self._writeRef(key, version,
                                       uuid, previous, next, alias)
                        if oldAlias is not None:
                            names.writeName(self._uuid, oldAlias,
                                            version, None)
                        if alias is not None:
                            names.writeName(self._uuid, alias,
                                            version, uuid)
                        
                elif op == 1:             # remove
                    self._writeRef(key, version, None, None, None, None)
                    if oldAlias is not None:
                        names.writeName(key, version, oldAlias, None)

                else:                     # error
                    raise ValueError, op

            if self._log:
                self.view._notifications.changed(self._item._uuid, self._name)

            del self._log[:]
            self._deletedRefs.clear()
            
            if len(self) > 0:
                generator.startElement('db', {})
                generator.characters(self._uuid.str64())
                generator.endElement('db')

        elif mode == 'serialize':
            super(XMLRefDict, self)._xmlValues(generator, version, mode)

        else:
            raise ValueError, mode


class XMLClientRefDict(XMLRefDict):

    def _prepareKey(self, uItem, uuid):

        self._uItem = uItem
        self._uuid = uuid
            
    def _loadRef_(self, key):

        return self.view.repository.store.loadRef(self._item._version,
                                                  self._uItem, self._uuid, key)

    def _writeRef(self, key, version, uuid, previous, next, alias):
        raise NotImplementedError, "XMLClientRefDict._writeRef"


class XMLText(Text, ItemValue):

    def __init__(self, view, *args, **kwds):

        Text.__init__(self, *args, **kwds)
        ItemValue.__init__(self)
        
        self._uuid = None
        self._view = view
        self._version = 0

    def _xmlValue(self, generator):

        uuid = self.getUUID()
        
        if self._dirty:
            store = self._view.repository.store
            if self._append:
                out = store._text.appendFile(self._makeKey())
            else:
                self._version += 1
                out = store._text.createFile(self._makeKey())
            out.write(self._data)
            out.close()
            self._data = ''

            if self._indexed:
                store._index.indexDocument(self._view._getIndexWriter(),
                                           self.getReader(),
                                           uuid,
                                           self._getItem().itsUUID,
                                           self._getAttribute(),
                                           self.getVersion())
            self._dirty = False

        attrs = {}
        attrs['version'] = str(self._version)
        attrs['mimetype'] = self.mimetype
        attrs['encoding'] = self.encoding
        if self._compression:
            attrs['compression'] = self._compression
        attrs['type'] = 'uuid'
        if self._indexed:
            attrs['indexed'] = 'True'
        
        generator.startElement('text', attrs)
        generator.characters(uuid.str64())
        generator.endElement('text')

    def getUUID(self):

        if self._uuid is None:
            self._uuid = UUID()
            self._setDirty()

        return self._uuid

    def getVersion(self):

        return self._version

    def _makeKey(self):

        return pack('>16sl', self.getUUID()._uuid, ~self._version)

    def _textEnd(self, data, attrs):

        self.mimetype = attrs.get('mimetype', 'text/plain')
        self._compression = attrs.get('compression', None)
        self._version = long(attrs.get('version', '0'))
        self._indexed = attrs.get('indexed', 'False') == 'True'

        if attrs.has_key('encoding'):
            self._encoding = attrs['encoding']

        if attrs.get('type', 'text') == 'text':
            writer = self.getWriter()
            writer.write(data)
            writer.close()
        else:
            self._uuid = UUID(data)

    def _setData(self, data):

        super(XMLText, self)._setData(data)
        self._setDirty()

    def _getInputStream(self):

        if self._data:
            dataIn = super(XMLText, self)._getInputStream()
        else:
            dataIn = None

        text = self._view.repository.store._text
        key = self._makeKey()
        
        if dataIn is not None:
            if self._append:
                if text.fileExists(key):
                    return ConcatenatedInputStream(text.openFile(key), dataIn)
                else:
                    return dataIn
            else:
                return dataIn
        elif text.fileExists(key):
            return text.openFile(key)
        else:
            return NullInputStream()
        

class XMLBinary(Binary, ItemValue):

    def __init__(self, view, *args, **kwds):

        Binary.__init__(self, *args, **kwds)
        ItemValue.__init__(self)

        self._uuid = None
        self._view = view
        self._version = 0
        
    def _xmlValue(self, generator):

        uuid = self.getUUID()

        if self._dirty:
            store = self._view.repository.store
            if self._append:
                out = store._binary.appendFile(self._makeKey())
            else:
                self._version += 1
                out = store._binary.createFile(self._makeKey())
            out.write(self._data)
            out.close()

            self._dirty = False

        attrs = {}
        attrs['version'] = str(self._version)
        attrs['mimetype'] = self.mimetype
        if self._compression:
            attrs['compression'] = self._compression
        attrs['type'] = 'uuid'
        
        generator.startElement('binary', attrs)
        generator.characters(uuid.str64())
        generator.endElement('binary')

    def getUUID(self):

        if self._uuid is None:
            self._uuid = UUID()
            self._setDirty()

        return self._uuid

    def getVersion(self):

        return self._version

    def _makeKey(self):

        return pack('>16sl', self._uuid._uuid, ~self._version)

    def _binaryEnd(self, data, attrs):

        self.mimetype = attrs.get('mimetype', 'text/plain')
        self._compression = attrs.get('compression', None)
        self._version = long(attrs.get('version', '0'))

        if attrs.get('type', 'binary') == 'binary':
            writer = self.getWriter()
            writer.write(data)
            writer.close()
        else:
            self._uuid = UUID(data)

    def _setData(self, data):

        super(XMLBinary, self)._setData(data)
        self._setDirty()

    def _getInputStream(self):

        if self._data:
            dataIn = super(XMLBinary, self)._getInputStream()
        else:
            dataIn = None

        binary = self._view.repository.store._binary
        key = self._makeKey()
        
        if dataIn is not None:
            if self._append:
                if binary.fileExists(key):
                    return ConcatenatedInputStream(binary.openFile(key),
                                                   dataIn)
                else:
                    return dataIn
            else:
                return dataIn
        elif binary.fileExists(key):
            return binary.openFile(key)
        else:
            return NullInputStream()
