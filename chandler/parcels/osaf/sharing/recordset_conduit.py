#   Copyright (c) 2003-2007 Open Source Applications Foundation
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

from osaf import pim
import conduits, errors, formats, eim, shares, model
from i18n import ChandlerMessageFactory as _
import logging
from itertools import chain
from application import schema
from repository.item.Item import Item
from repository.persistence.RepositoryError import MergeError
from chandlerdb.util.c import UUID

logger = logging.getLogger(__name__)


__all__ = [
    'RecordSetConduit',
    'DiffRecordSetConduit',
    'MonolithicRecordSetConduit',
    'ResourceRecordSetConduit',
    'ResourceState',
    'InMemoryDiffRecordSetConduit',
    'InMemoryMonolithicRecordSetConduit',
    'InMemoryResourceRecordSetConduit',
]







def mergeFunction(code, item, attribute, value):
    # 'value' is the one from *this* view
    # getattr(item, attribute) is the value from a different view

    if code == MergeError.DELETE:
        return True

    return value # Change from *this* view wins




class RecordSetConduit(conduits.BaseConduit):

    translator = schema.One(schema.Class)
    serializer = schema.One(schema.Class)
    syncToken = schema.One(schema.Text, defaultValue="")
    filters = schema.Many(schema.Text, initialValue=set())
    lastVersion = schema.One(schema.Long, initialValue=0)

    def sync(self, modeOverride=None, activity=None, forceUpdate=None,
        debug=False):


        if forceUpdate:
            # We want to fetch all items from the server, not just changes
            # since the previous sync
            self.syncToken = ""

        rv = self.itsView

        try:
            stats = self._sync(modeOverride=modeOverride,
                activity=activity, forceUpdate=forceUpdate,
                debug=debug)

            if activity:
                activity.update(msg="Saving...", totalWork=None)
            rv.commit(mergeFunction)
            logger.debug("View version is now: %s", rv.itsVersion)

        except Exception, exception:
            logger.exception("Sharing Error")
            rv.cancel() # Discard any changes we made
            raise

        return stats


    def _sync(self, modeOverride=None, activity=None, forceUpdate=None,
        debug=False):

        doLog = logger.info if debug else logger.debug


        def _callback(*args, **kwds):
            if activity:
                activity.update(*args, **kwds)

        rv = self.itsView

        stats = []
        receiveStats = { 'share' : self.share.itsUUID, 'op' : 'get',
            'added' : set(), 'modified' : set(), 'removed' : set() }
        sendStats = { 'share' : self.share.itsUUID, 'op' : 'put',
            'added' : set(), 'modified' : set(), 'removed' : set() }

        if modeOverride:
            if modeOverride == 'put':
                send = True
                receive = False
            else: # get
                send = False
                receive = True
        else:
            send = self.share.mode in ('put', 'both')
            receive = self.share.mode in ('get', 'both')

        doLog("================ start of sync =================")
        doLog("Mode: %s", self.share.mode)
        doLog("Mode override: %s", modeOverride)
        doLog("Send: %s", send)
        doLog("Receive: %s", receive)

        translator = self.translator(rv)

        if self.share.established:
            doLog("Previous sync included up to version: %s",
                self.lastVersion)
            version = self.lastVersion + 1
            # Old share items won't have their displayName set; set it:
            if not self.share.displayName and self.share.contents is not None:
                self.share.displayName = self.share.contents.displayName
        else:
            version = 0
            # This is our first sync; if we're already assigned a collection,
            # that means this is our initial publish; don't receive
            if self.share.contents is not None:
                self.share.displayName = self.share.contents.displayName
                if send:
                    receive = False

        doLog("Current view version: %s", rv.itsVersion)


        remotelyRemoved = set() # The aliases of remotely removed items
        remotelyAdded = set() # The aliases of remotely added items
        locallyAdded = set( ) # The aliases of locally add items
        localItems = set() # The aliases of all items we're to process

        if receive:

            _callback(msg="Fetching changes", totalWork=None)
            inbound, extra, isDiff = self.getRecords(debug=debug, activity=
                activity)


            ids = inbound.keys()
            ids.sort()
            for id in ids:
                logger.info("<<<< Inbound recordset: %s", id)
                rs = inbound[id]
                if rs is None:
                    logger.info("<< !! Deletion")
                else:
                    for rec in rs.inclusions:
                        logger.info("<< ++ %s", rec)
                    for rec in rs.exclusions:
                        logger.info("<< -- %s", rec)
            logger.info("Inbound 'extra': %s", extra)

            inboundCount = len(inbound)
            _callback(msg="Received %d change(s)" % inboundCount)

            if self.share.contents is None:
                # We're importing a collection; either create it if it
                # doesn't exist, or grab the matching one we already have.
                collectionUuid = extra.get('uuid', None)

                def setup_collection(collection):
                    if not pim.has_stamp(collection, shares.SharedItem):
                        shares.SharedItem(collection).add()
                    self.share.contents = collection

                if collectionUuid:
                    translator.withItemForUUID(
                        collectionUuid, pim.SmartCollection
                    )(setup_collection)
                else:
                    # We weren't provided a collection, so let's create our own
                    setup_collection(pim.SmartCollection(itsView=rv))


            # If the inbound collection name is provided we change the local
            # collection name (only if initial subscribe -- latter syncs don't
            # change the name)
            self.share.displayName = extra.get('name', _(u"Untitled"))
            if not self.share.established:
                self.share.contents.displayName = self.share.displayName

            # Add remotely changed items
            for alias in inbound.keys():
                rs = inbound[alias]
                if rs is None: # skip deletions
                    doLog("Inbound removal: %s", alias)
                    del inbound[alias]
                    remotelyRemoved.add(alias)

                    # Since this item was remotely removed, all pending
                    # changes should go away.
                    if self.hasState(alias):
                        state = self.getState(alias)
                        if hasattr(state, "_pending"):
                            del state._pending


                else:
                    uuid = translator.getUUIDForAlias(alias)
                    if uuid:
                        item = rv.findUUID(uuid)
                    else:
                        item = None

                    if self.hasState(alias):
                        # clear out any pendingRemoval
                        state = self.getState(alias)
                        state.pendingRemoval = False
                        if item is not None:
                            state.updateConflicts(item)

                    if (item is not None and
                        item.isLive() and
                        not pim.EventStamp(item).isGenerated):
                        # An inbound modification to an item we already have
                        localItems.add(alias)
                        doLog("Inbound mod to live/non-generated: %s", alias)

                    else:
                        doLog("Inbound mod to non-existent/generated: %s",
                            alias)
                        remotelyAdded.add(alias)
                        if self.hasState(alias):
                            # This is an item we completely deleted since our
                            # last sync.  We need to grab its previous state
                            # out of the baseline, apply any pending changes
                            # and the new inbound chagnes to it, and use that
                            # as the new inbound
                            state = self.getState(alias)
                            rs = state.agreed + state.pending + rs
                            doLog("Reconstituting from state: %s", rs)
                            inbound[alias] = rs
                            state.clear()


        else:
            inbound = {}
            isDiff = True

        _callback(msg="Checking for local changes", totalWork=None)

        # Generate records for all local items to be merged -- those that
        # have either been changed locally or remotely:


        # Add locally changed items
        locallyChangedUuids = set()

        if forceUpdate:
            # A filter was changed, so we need to publish all items again
            for item in self.share.contents:
                locallyChangedUuids.add(item.itsUUID)

        else:
            # This loop tries to avoid loading any non-dirty items:
            # When statistics logging is added, we can verify this loop is doing
            # what we expect
            for changedUuid, x in rv.mapHistoryKeys(fromVersion=version,
                toVersion=rv.itsVersion):
                if changedUuid in self.share.contents:
                    locallyChangedUuids.add(changedUuid)

            # for changedUuid in locallyChangedUuids:
            #     print "----"
            #     print "Item Changes for", changedUuid, rv.findUUID(changedUuid).displayName
            #     rv.repository.printItemChanges(rv.findUUID(changedUuid),
            #         fromVersion=version, toVersion=rv.itsVersion)


        localCount = len(locallyChangedUuids)
        _callback(msg="Found %d local change(s)" % localCount)

        for changedUuid in locallyChangedUuids:
            item = rv.findUUID(changedUuid)
            # modifications that have been changed purely by
            # auto-triage shouldn't have recordsets created for them
            if (isinstance(item, pim.Note) and
                pim.EventStamp(item).isTriageOnlyModification() and
                item.doAutoTriageOnDateChange):
                doLog("Skipping a triage-only modification: %s",
                    changedUuid)
                continue

            alias = translator.getAliasForItem(item)

            if not self.hasState(alias):
                # a new, locally created item
                locallyAdded.add(alias)

            doLog("Locally modified item: %s / alias: %s", item.itsUUID, alias)
            localItems.add(alias)
            uuid = item.itsUUID.str16()

        localCount = len(localItems)
        if localCount:
            _callback(msg="%d recordset(s) to generate" % localCount,
                totalWork=localCount, workDone=0)

        # Compute local records
        rsNewBase = { }
        i = 0
        for alias in localItems:
            uuid = translator.getUUIDForAlias(alias)
            if uuid:
                item = rv.findUUID(uuid)
            else:
                item = None

            if (item is not None and
                item.isLive() and
                not pim.EventStamp(item).isGenerated):

                rs = eim.RecordSet(translator.exportItem(item))
                self.share.addSharedItem(item)
                doLog("Computing local records for alias: %s", alias)
            else:
                rs = eim.RecordSet()
                doLog("No live/non-generated item for: %s", alias)
            rsNewBase[alias] = rs
            i += 1
            _callback(msg="Generated %d of %d recordset(s)" % (i, localCount),
                work=1)


        filter = self.getFilter()
        filterFn = filter.sync_filter if filter else (lambda rs: rs)

        # Merge
        toApply = {}
        toSend = {}
        toAutoResolve = {}

        aliases = set(rsNewBase) | set(inbound)
        mergeCount = len(aliases)
        if mergeCount:
            _callback(msg="%d recordset(s) to merge" % mergeCount,
                totalWork=mergeCount, workDone=0)

        i = 0
        for alias in aliases:
            state = self.getState(alias)

            if state.pendingRemoval:
                # This item has a pending inbound removal, so we don't bother
                # merging it
                continue

            rsInternal = rsNewBase.get(alias, eim.RecordSet())

            if not isDiff:
                # Ensure rsExternal is the whole state
                if not inbound.has_key(alias): # Not remotely changed
                    rsExternal = state.agreed + state.pending
                else:
                    rsExternal = inbound.get(alias)
            else:
                rsExternal = inbound.get(alias, eim.RecordSet())

            readOnly = (self.share.mode == 'get')
            doLog("----- Merging %s %s", alias,
                "(Read-only merge)" if readOnly else "")

            uuid = translator.getUUIDForAlias(alias)
            if (uuid is not None and uuid != alias and not state.agreed and
                inbound.has_key(alias)):
                # to fix bug 8665, new inbound modifications are incorrectly
                # seen as conflicts, set the agreed state in records for new
                # modifications to be all Inherit values.  Without this, local
                # Inherit values will be treated as conflicts
                inherit_records = []
                for record in rsInternal.inclusions:
                    keys = [f for f in record.__fields__
                            if isinstance(f, eim.key)]
                    if len(keys) != 1:
                        continue
                    non_uuid_fields = len(record.__fields__) - 1
                    args = (record.uuid,) + non_uuid_fields * (eim.Inherit,)
                    inherit_records.append(type(record)(*args))
                state.agreed += eim.RecordSet(inherit_records)

            dSend, dApply, pending = state.merge(rsInternal, rsExternal,
                isDiff=isDiff, filter=filter, readOnly=readOnly, debug=debug)


            if readOnly:
                # Cosmo doesn't give us deletions for ModifiedByRecords and
                # that messes with the no-send aspect of the merge function
                # because old ModByRecords aren't cleaned out.
                state.agreed = state.agreed + eim.Diff(
                    [], [r for r in state.agreed.inclusions
                         if isinstance(r, model.ModifiedByRecord)]
                )

            if uuid:
                item = rv.findUUID(uuid)
            else:
                item = None


            if receive and pending and item is not None:

                for rConflict, field in iterConflicts(pending):
                    rLocal = findMatch(rConflict, rsInternal)
                    rAgreed = findMatch(rConflict, state.agreed)
                    doLog("Local: %s", rLocal)
                    doLog("Remote: %s", rConflict)
                    doLog("Agreed: %s", rAgreed)

                    if rLocal: # rLocal will be None if the conflict is
                               # a record deletion, which this auto-resolve
                               # code doesn't yet support

                        if rAgreed in (eim.NoChange, eim.Inherit):
                            agreedValue = rAgreed
                        else:
                            agreedValue = (field.__get__(rAgreed) if rAgreed
                                else eim.NoChange)

                        localValue = field.__get__(rLocal)
                        remoteValue = field.__get__(rConflict)

                        decision = translator.resolve(type(rConflict), field,
                            agreedValue, localValue, remoteValue)

                        if decision == -1: # local wins
                            dLocal = eim.Diff([rLocal])
                            dSend += dLocal
                            state.agreed += dLocal

                        elif decision == 1: # remote wins
                            dConflict = eim.Diff([rConflict])
                            dApply += dConflict
                            state.agreed += dConflict

                        if decision:
                            newPending = state.pending
                            newPending.remove(rConflict)
                            state.pending = newPending
                            doLog("State updated to: %s", state)

            state.updateConflicts(item)

            if send and dSend:
                toSend[alias] = dSend

            if receive and dApply:
                toApply[alias] = dApply

            if receive and pending:
                toAutoResolve[alias] = pending

            i += 1
            _callback(msg="Merged %d of %d recordset(s)" % (i, mergeCount),
                work=1)


        # Examine inbound removal of items with local changes
        if send:

            pendingRemovals = set() # aliases of remotely removed items
                                    # which have local changes

            toSendBack = set() # aliases of remotely removed items to re-send

            for alias in toSend.keys():
                uuid = translator.getUUIDForAlias(alias)
                changedItem = rv.findUUID(uuid)

                if isinstance(changedItem, pim.Occurrence):
                    if alias in remotelyRemoved:
                        toSendBack.add(alias)
                    masterItem = changedItem.inheritFrom
                    masterAlias = translator.getAliasForItem(masterItem)
                    if masterAlias in remotelyRemoved:
                        # We're a changed modification with an inbound
                        # deletion of our master.  Tag the master and its
                        # modifications with a removal conflict.
                        doLog("Remotely removed master %s has local mod "
                            "changes: %s", masterAlias, alias)
                        toSendBack.add(masterAlias)

                elif getattr(changedItem, 'inheritTo', False):
                    # This is a master
                    if alias in remotelyRemoved:
                        toSendBack.add(alias)

                else:
                    # This item is not recurring
                    if alias in remotelyRemoved:
                        doLog("Remotely removed item has local changes: %s",
                            alias)
                        pendingRemovals.add(alias)

            for alias in toSendBack:
                if self.hasState(alias):
                    state = self.getState(alias)

                    # This was removed remotely, but we have local changes.
                    # We need to send the entire state of the item, not just
                    # a diff.  Also, remove the alias from remotelyRemoved
                    # so that the item doesn't get removed from the collection
                    # further down.
                    toSend[alias] = filterFn(state.agreed)
                    if alias in remotelyRemoved:
                        remotelyRemoved.remove(alias)

                    uuid = translator.getUUIDForAlias(alias)
                    changedItem = rv.findUUID(uuid)
                    if pim.has_stamp(changedItem, pim.EventStamp):
                        event = pim.EventStamp(changedItem)
                        for mod in getattr(event, 'modifications', []):
                            modAlias = translator.getAliasForItem(mod)
                            if self.hasState(modAlias):
                                modState = self.getState(modAlias)
                                toSend[modAlias] = filterFn(modState.agreed)
                                if modAlias in remotelyRemoved:
                                    remotelyRemoved.remove(modAlias)
                                    doLog("Sending back modification: %s",
                                        modAlias)

            for alias in pendingRemovals:
                if self.hasState(alias):
                    state = self.getState(alias)

                    # This was removed remotely, but we have local changes.
                    # We clear agreed/pending from the state, and add a conflict
                    # for the removal.
                    # Also, remove the alias from remotelyRemoved
                    # so that the item doesn't get removed from the collection
                    # further down.

                    uuid = translator.getUUIDForAlias(alias)
                    changedItem = rv.findUUID(uuid)

                    if alias in toSend:
                        del toSend[alias]
                    state.clear()
                    state.pendingRemoval = True
                    if alias in remotelyRemoved:
                        remotelyRemoved.remove(alias)
                    doLog("Removal conflict: %s", alias)
                    if changedItem is not None:
                        state.updateConflicts(changedItem)

                    # I may use this, but commenting out for now
                    # if pim.has_stamp(changedItem, pim.EventStamp):
                    #     event = pim.EventStamp(changedItem)
                    #     for mod in getattr(event, 'modifications', []):
                    #         modAlias = translator.getAliasForItem(mod)
                    #         if self.hasState(modAlias):
                    #             modState = self.getState(modAlias)
                    #             if modAlias in toSend:
                    #                 del toSend[modAlias]
                    #             modState.clear()
                    #             modState.pendingRemoval = True
                    #             if modAlias in remotelyRemoved:
                    #                 remotelyRemoved.remove(modAlias)
                    #             doLog("Removal conflict: %s", modAlias)
                    #             modState.updateConflicts(mod)

        if receive:

            applyCount = len(toApply)
            if applyCount:
                _callback(msg="%d inbound change(s) to apply" % applyCount,
                    totalWork=applyCount, workDone=0)

            # Apply
            translator.startImport()
            i = 0
            aliases = toApply.keys()
            # Sort aliases so masters come before modifications...
            aliases.sort()
            for alias in aliases:
                rs = toApply[alias]

                # If the only change is a modifiedyBy record, ignore this rs
                for r in chain(rs.inclusions, rs.exclusions):
                    if not isinstance(r, model.ModifiedByRecord):
                        break
                else:
                    # This rs contains nothing but modifiedBy records
                    doLog("Skipping application of ModifiedBy for %s [%s]",
                        alias, rs)
                    continue

                doLog("Applying changes to %s [%s]", alias, rs)

                uuid = translator.getUUIDForAlias(alias)
                if uuid:
                    item = rv.findUUID(uuid)
                else:
                    item = None

                logger.info("** Applying to UUID: %s / alias: %s", uuid, alias)
                for rec in rs.inclusions:
                    logger.info("** ++ %s", rec)
                for rec in rs.exclusions:
                    logger.info("** -- %s", rec)

                try:
                    translator.importRecords(rs)
                except Exception, e:
                    errors.annotate(e, "Record import failed", details=str(rs))
                    raise

                uuid = translator.getUUIDForAlias(alias)
                if uuid:
                    item = rv.findUUID(uuid)
                else:
                    item = None

                if item is not None:
                    # Set triage status, based on the values we loaded
                    # We'll only autotriage if we're not sharing triage status;
                    # We'll only pop to Now if this is an established share.
                    # Do nothing if neither.
                    established = self.share.established
                    newTriageStatus = 'auto' \
                        if extra.get('forceDateTriage', False) or \
                           'cid:triage-filter@osaf.us' in self.filters \
                        else None
                    if newTriageStatus or established:
                        pim.setTriageStatus(item, newTriageStatus,
                            popToNow=established)

                    # Per bug 8809:
                    # Set "read" state to True if this is an initial subscribe
                    # but False otherwise.  self.share.established is False
                    # during an initial subscribe and True on subsequent
                    # syncs.  Also, make sure we apply this to the master item:
                    item_to_change = getattr(item, 'inheritFrom', item)
                    item_to_change.read = not established
                    doLog("Marking item %s: %s" % (
                        ("read" if item_to_change.read else "unread"), uuid))

                if alias in remotelyAdded:
                    receiveStats['added'].add(alias)
                else:
                    receiveStats['modified'].add(alias)
                i += 1
                _callback(msg="Applied %d of %d change(s)" % (i, applyCount),
                    work=1)


            translator.finishImport()

            # Auto-resolve conflicts
            conflicts = []
            for alias, rs in toAutoResolve.items():
                uuid = translator.getUUIDForAlias(alias)
                if uuid:
                    item = rv.findUUID(uuid)
                    if item is not None:
                        for conflict in shares.SharedItem(item).getConflicts():
                            conflicts.append(conflict)

            translator.resolveConflicts(conflicts)



            # Make sure any items that came in are added to the collection
            _callback(msg="Adding items to collection", totalWork=None)

            for alias in inbound:
                uuid = translator.getUUIDForAlias(alias)
                if uuid:
                    item = rv.findUUID(uuid)
                else:
                    item = None

                # Add the item to contents
                if item is not None and item.isLive():
                    self.share.contents.add(item)
                    self.share.addSharedItem(item)


            # For each remote removal, remove the item from the collection
            # locally
            # At this point, we know there were no local modifications
            _callback(msg="Removing items from collection", totalWork=None)

            for alias in remotelyRemoved:
                uuid = translator.getUUIDForAlias(alias)
                if uuid:
                    item = rv.findUUID(uuid)
                else:
                    item = None

                if item is not None and item in self.share.contents:
                    self.share.removeSharedItem(item)
                    if isinstance(item, pim.Occurrence):
                        # A recordset deletion on an occurrence is treated
                        # as an "unmodification" i.e., a modification going
                        # back to a simple occurrence.  But don't do anything
                        # if our master is being removed.
                        masterItem = item.inheritFrom
                        masterAlias = translator.getAliasForItem(masterItem)
                        if masterAlias not in remotelyRemoved:
                            pim.EventStamp(item).unmodify()
                            doLog("Locally unmodifying alias: %s", alias)
                        else:
                            doLog("Master was remotely removed for alias: %s",
                                alias)
                    else:
                        self.share.contents.remove(item)
                        doLog("Locally removing  alias: %s", alias)
                    receiveStats['removed'].add(alias)

                self.removeState(alias)


        # For each item that was in the collection before but is no longer,
        # remove its state; if sending, add an empty recordset to toSend
        # TODO: Optimize by removing item loading
        statesToRemove = set()
        for state in self.share.states:
            alias = self.share.states.getAlias(state)
            uuid = translator.getUUIDForAlias(alias)
            if uuid:
                item = rv.findUUID(uuid)
            else:
                item = None

            if (item is None or
                item not in self.share.contents and
                alias not in remotelyRemoved):
                if send:
                    toSend[alias] = None
                statesToRemove.add(alias)

                doLog("Remotely removing item: %s", alias)

        removeCount = len(statesToRemove)
        if removeCount:
            _callback(msg="%d local removal(s) detected" % removeCount,
                totalWork=None)


        # Send if there is something to send or even if this is just an
        # initial publish of an empty collection:
        if send and (toSend or not self.share.established):
            sendCount = len(toSend)
            _callback(msg="Sending %d outbound change(s)" % sendCount,
                totalWork=None)

            extra = { 'rootName' : 'collection',
                      'uuid' : self.share.contents.itsUUID.str16(),
                      'name' : self.share.displayName
                    }

            aliases = toSend.keys()
            aliases.sort()
            for alias in aliases:
                logger.info(">>>> Sending recordset: %s", alias)
                rs = toSend[alias]
                if rs is None:
                    logger.info(">> !! Deletion")
                    sendStats['removed'].add(alias)
                else:
                    for rec in rs.inclusions:
                        logger.info(">> ++ %s", rec)
                    for rec in rs.exclusions:
                        logger.info(">> -- %s", rec)

                    if alias in locallyAdded:
                        # the sending of a new item
                        sendStats['added'].add(alias)
                    else:
                        # an update to a previously synced item
                        sendStats['modified'].add(alias)

            self.putRecords(toSend, extra, debug=debug, activity=activity)
        else:
            doLog("Nothing to send")


        for alias in statesToRemove:
            doLog("Removing state: %s", alias)
            self.removeState(alias)
            uuid = translator.getUUIDForAlias(alias)
            if uuid:
                item = rv.findUUID(uuid)
                if item is not None:
                    # Make sure not to remodify an unmodification...
                    isGenerated = pim.EventStamp(item).isGenerated
                    self.share.removeSharedItem(item)
                    if isGenerated:
                        pim.EventStamp(item).unmodify()

        # Note the repository version number
        self.lastVersion = rv.itsVersion

        self.share.established = True

        _callback(msg="Done")

        doLog("================== end of sync =================")

        if receive:
            receiveStats['applied'] = str(toApply)
            stats.append(receiveStats)
        if send:
            sendStats['sent'] = str(toSend)
            stats.append(sendStats)
        return stats




    def getState(self, alias):
        state = self.share.states.getByAlias(alias)
        if state is None:
            state = self.newState(alias)
        return state

    def newState(self, alias):
        state = shares.State(itsView=self.itsView, peer=self.share)
        self.share.states.append(state, alias)
        return state

    def removeState(self, alias):
        state = self.share.states.getByAlias(alias)
        if state is not None:
            self.share.states.remove(state)
            state.delete(True)

    def hasState(self, alias):
        return self.share.states.getByAlias(alias) is not None


    def getFilter(self):
        filter = eim.Filter(None, u'Temporary filter')
        for uri in getattr(self, 'filters', []):
            filter += eim.lookupSchemaURI(uri)
        return filter

    def getRecords(self, debug=False, activity=None):
        raise NotImplementedError

    def putRecords(self, toSend, extra, debug=False, activity=None):
        raise NotImplementedError

    def fileStyle(self):
        return formats.STYLE_DIRECTORY


    def isAttributeModifiable(self, item, attribute):
        # recordset conduits allow any attribute to be modifiable without
        # interfering with external changes (they are merged and checked for
        # conflicts)
        return True


class DiffRecordSetConduit(RecordSetConduit):

    def getRecords(self, debug=False, activity=None):
        doLog = logger.info if debug else logger.debug
        text = self.get()
        doLog("Received from server [%s]", text)

        inbound, extra = self.serializer.deserialize(self.itsView, text)
        return inbound, extra, True

    def putRecords(self, toSend, extra, debug=False, activity=None):
        doLog = logger.info if debug else logger.debug
        text = self.serializer.serialize(self.itsView, toSend, **extra)
        doLog("Sending to server [%s]", text)
        self.put(text)





class MonolithicRecordSetConduit(RecordSetConduit):

    etag = schema.One(schema.Text, initialValue="")

    def getRecords(self, debug=False, activity=None):
        doLog = logger.info if debug else logger.debug
        text = self.get()
        doLog("Received from server [%s]", text)

        if text:
            try:
                inbound, extra = self.serializer.deserialize(self.itsView, text)
            except Exception, e:
                errors.annotate(e, "Failed to deserialize",
                    details=text.decode('utf-8'))
                raise
            return inbound, extra, False

        else:
            return { }, { }, False

    def putRecords(self, toSend, extra, debug=False, activity=None):
        # get the full state of every item not being deleted
        doLog = logger.info if debug else logger.debug
        fullToSend = { }
        for state in self.share.states:
            alias = self.share.states.getAlias(state)
            if toSend.has_key(alias) and toSend[alias] is None:
                pass
            else:
                rs = state.agreed + state.pending
                fullToSend[alias] = rs
        
        extra['monolithic'] = True
        text = self.serializer.serialize(self.itsView, fullToSend, **extra)
        doLog("Sending to server [%s]", text)
        self.put(text)

    def fileStyle(self):
        return formats.STYLE_SINGLE





class ResourceRecordSetConduit(RecordSetConduit):

    def getRecords(self, debug=False, activity=None):
        # Get and return records, extra
        doLog = logger.info if debug else logger.debug

        inbound = { }
        extra = { }

        # get list of remote items, store in dict keyed on path, value = etag
        if activity:
            activity.update(msg="Getting list of resources", totalWork=None)
        self.resources = self.getResources()

        # If one of our local states isn't in the resource list, that means
        # it's been removed from the server:
        paths = { }
        for state in self.share.states:
            if hasattr(state, 'path'):
                alias = self.share.states.getAlias(state)
                if state.path not in self.resources:
                    if state.agreed:
                        # Only consider this a remote deletion if we had
                        # agreed data from the last sync
                        inbound[alias] = None # indicator of remote deletion
                else:
                    paths[state.path] = (alias, state)

        # Examine old and new etags to see what needs to be fetched:
        toFetch = set()
        for path, etag in self.resources.iteritems():
            if path in paths:
                state = paths[path][1]
                if etag != state.etag:
                    # Need to fetch this path since its etag doesn't match
                    doLog("Need to fetch: etag mismatch for %s "
                        "(%s vs %s)", path, state.etag, etag)
                    toFetch.add(path)
            else:
                # Need to fetch this path since we don't yet have it
                doLog("Need to fetch: don't yet have %s", path)
                toFetch.add(path)

        fetchCount = len(toFetch)
        doLog("%d resources to get", fetchCount)
        if activity:
            activity.update(msg="%d resources to get" % fetchCount,
                totalWork=fetchCount, workDone=0)

        i = 0
        for path in toFetch:
            if activity:
                i += 1
                activity.update(msg="Getting %d of %d" % (i, fetchCount),
                    work=1)
            text, etag = self.getResource(path)
            doLog("Received from server [%s]", text)
            records, extra = self.serializer.deserialize(self.itsView, text)
            for alias, rs in records.iteritems():
                inbound[alias] = rs
                state = self.getState(alias)
                state.path = path
                state.etag = etag

        return inbound, extra, False


    def putRecords(self, toSend, extra, debug=False, activity=None):
        doLog = logger.info if debug else logger.debug

        sendCount = len(toSend)

        if activity:
            activity.update(msg="Sending %d resources" % sendCount,
                totalWork=sendCount, workDone=0)

        i = 0
        for alias, rs in toSend.iteritems():
            state = self.getState(alias)
            path = getattr(state, "path", None)
            etag = getattr(state, "etag", None)

            if activity:
                i += 1
                activity.update(msg="Sending %d of %d" % (i, sendCount),
                    work=1)

            if rs is None:
                # delete the resource
                if path:
                    self.deleteResource(path, etag)
                    doLog("Deleting path %s", path)
            else:
                if not path:
                    # need to compute a path
                    path = self.getPath(UUID().str16())

                # rs needs to include the entire recordset, not diffs
                rs = state.agreed + state.pending

                doLog("Full resource records: %s", rs)

                text = self.serializer.serialize(self.itsView, {alias : rs},
                                                 **extra)
                doLog("Sending to server [%s]", text)
                etag = self.putResource(text, path, etag, debug=debug)
                state.path = path
                state.etag = etag
                doLog("Put path %s, etag now %s", path, etag)


    def newState(self, alias):
        state = ResourceState(itsView=self.itsView, peer=self.share)
        self.share.states.append(state, alias)
        return state


    def getPath(self, uuid):
        return uuid


class ResourceState(shares.State):
    path = schema.One(schema.Text)
    etag = schema.One(schema.Text)






shareDict = { }

class InMemoryDiffRecordSetConduit(DiffRecordSetConduit):

    def get(self):
        self.syncToken, text = self.serverGet(self.shareName, self.syncToken)
        return text

    def put(self, text):
        if self.syncToken:
            self.syncToken = self.serverPost(self.shareName, self.syncToken,
                                             text)
        else:
            self.syncToken = self.serverPut(self.shareName, text)

    def exists(self):
        return shareDict.has_key(self.shareName)

    def destroy(self):
        del shareDict[self.shareName]

    def create(self):
        self._getCollection(self.shareName)

    # simulate cosmo:

    def _getCollection(self, path):
        return shareDict.setdefault(path, { "token" : 0, "items" : {} })


    def serverPut(self, path, text):
        recordsets, extra = self.serializer.deserialize(self.itsView, text)
        coll = self._getCollection(path)
        if extra.has_key("name"):
            coll["name"] = extra["name"]
        if extra.has_key("uuid"):
            coll["uuid"] = extra["uuid"]
        newToken = coll["token"]
        newToken += 1
        for uuid, rs in recordsets.items():
            itemHistory = coll["items"].setdefault(uuid, [])
            itemHistory.append( (newToken, rs) )
        coll["token"] = newToken
        return str(newToken)

    def serverPost(self, path, token, text):
        token = int(token)
        coll = self._getCollection(path)
        current = coll["token"]

        if token != current:
            raise errors.TokenMismatch("%s != %s" % (token, current))

        return self.serverPut(path, text)

    def serverGet(self, path, token):

        if token:
            token = int(token)
        else:
            token = 0

        coll = self._getCollection(path)

        current = coll["token"]
        if token > current:
            raise errors.MalformedToken(token)


        empty = eim.Diff()
        recordsets = { }
        for uuid, itemHistory in coll["items"].iteritems():
            rs = eim.Diff()
            for historicToken, diff in itemHistory:
                if historicToken > token:
                    if diff is None:
                        # This item was removed
                        rs = None
                    if diff is not None:
                        if rs is None:
                            rs = eim.Diff()
                        rs = rs + diff
            if rs != empty:
                recordsets[uuid] = rs


        extra = { }
        if coll.has_key("uuid"): extra["uuid"] = coll["uuid"]
        if coll.has_key("name"): extra["name"] = coll["name"]
        text = self.serializer.serialize(self.itsView, recordsets,
                                         rootName="collection", **extra)

        return str(current), text

    def dump(self, text=""):

        print "\nState of InMemoryDiffRecordSetConduit (%s):" % text
        for path, coll in shareDict.iteritems():
            print "\nCollection:", path
            print "\n   Latest token:", coll["token"]
            for uuid, itemHistory in coll["items"].iteritems():
                print "\n   - History for item:", uuid, "\n"
                for historicToken, diff in itemHistory:
                    if diff is None:
                        print "       [%d] <Deleted>" % historicToken
                    else:
                        print "       [%d] %s" % (historicToken, diff)




class InMemoryMonolithicRecordSetConduit(MonolithicRecordSetConduit):

    def get(self):
        self.etag, text = self.serverGet(self._getPath(), self.etag)
        return text

    def put(self, text):
        self.etag = self.serverPut(self._getPath(), text, self.etag)

    def exists(self):
        return shareDict.has_key(self._getPath())

    def destroy(self):
        del shareDict[self._getPath()]

    def create(self):
        self._getCollection(self._getPath())

    def _getPath(self):
        return "/".join([self.sharePath, self.shareName])

    def _getCollection(self, path):
        return shareDict.setdefault(path, { "etag" : 0, "text" : None })


    def serverPut(self, path, text, etag):
        if etag:
            etag = int(etag)
        else:
            etag = 0

        coll = self._getCollection(path)
        current = coll["etag"]
        if current > etag:
            raise errors.TokenMismatch("Remote content has been updated")

        coll["text"] = text
        current += 1
        coll["etag"] = current
        return str(current)


    def serverGet(self, path, etag):

        if etag:
            etag = int(etag)
        else:
            etag = 0

        coll = self._getCollection(path)

        current = coll["etag"]
        if etag >= current:
            # content not modified
            return str(current), None

        return str(current), coll["text"]








class InMemoryResourceRecordSetConduit(ResourceRecordSetConduit):

    def getResource(self, path):
        coll = self._getCollection()
        if coll['resources'].has_key(path):
            text, etag = coll['resources'][path]
            return text, str(etag)

    def putResource(self, text, path, etag=None, debug=False):
        doLog = logger.info if debug else logger.debug
        if etag is None:
            etag = 0
        else:
            etag = int(etag)

        coll = self._getCollection()
        if coll['resources'].has_key(path):
            oldText, oldTag = coll['resources'][path]
            if etag != oldTag:
                raise errors.TokenMismatch("Mismatched etags on PUT")
        coll['etag'] += 1
        coll['resources'][path] = (text, coll['etag'])
        doLog("Put [%s]", text)
        return str(coll['etag'])

    def deleteResource(self, path, etag=None):
        if etag is None:
            etag = 0
        else:
            etag = int(etag)

        coll = self._getCollection()
        if coll['resources'].has_key(path):
            oldText, oldTag = coll['resources'][path]
            if etag != oldTag:
                raise errors.TokenMismatch("Mismatched etags on DELETE")
            else:
                del coll['resources'][path]

    def exists(self):
        return shareDict.has_key(self.shareName)

    def destroy(self):
        del shareDict[self.shareName]

    def create(self):
        self._getCollection()

    def getResources(self):
        resources = { }

        coll = self._getCollection()
        for path, (text, etag) in coll['resources'].iteritems():
            resources[path] = str(etag)

        return resources

    def _getCollection(self):
        return shareDict.setdefault(self.shareName,
            { "etag" : 0, "resources" : {} })




def iterConflicts(dPending):
    # Break a pending Diff into records, each containing one conflicting
    # field.  This results in records that could be applied if you want the
    # pending change to win in a conflict.
    for r in dPending.inclusions:
        cls = type(r)
        data = [(f.__get__(r) if isinstance(f, eim.key) else eim.NoChange)
            for f in cls.__fields__]
        for f, value in zip(cls.__fields__, r[1:]):
            if not isinstance(f, eim.key) and value is not eim.NoChange:
                data[f.offset-1] = value
                yield cls(*data), f
                data[f.offset-1] = eim.NoChange

def findMatch(record, recordSet):
    # Given a record as returned from iterConflicts, find the record with the
    # same key within recordSet and return a copy of that record, but only
    # the fields that were not NoChange in the first arg record will be filled
    # in in the copy (while the rest will be NoChange).  This results in a
    # record that could be applied if you choose the local value to win in a
    # conflict.
    cls = type(record)
    key = record.getKey()

    for r in recordSet.inclusions:
        if key == r.getKey():
            data = [(f.__get__(r) if f.__get__(record) is not eim.NoChange
                else eim.NoChange) for f in cls.__fields__]
            return cls(*data)

    return None


def prettyPrintRecordSetDict(d):
    for uuid, rs in d.iteritems():
        print uuid
        if rs is None:
            print "   Deletion"
        else:
            for record in rs.inclusions:
                print "   " + str(record)
            if rs.exclusions:
                print "   Exclusions:"
                for record in rs.exclusions:
                    print "   " + str(record)
