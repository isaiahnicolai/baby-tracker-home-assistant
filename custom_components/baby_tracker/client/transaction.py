#transaction.py
"""
Applies sync transactions to the local database.

Merge behaviour follows the Android app's BTDatabaseImple (mergeTransactionLogsImple
and the mergeInsert*/mergeUpdate*/mergeDelete* methods):

- INSERT of an existing row is treated as an UPDATE.
- UPDATE only overwrites when the local row is strictly older (Timestamp <);
  a missing row is inserted.
- DELETE of a baby or selection that is still in use is rejected.
- RELIVE restores a deleted baby/selection; CONFLICT merges two babies or
  selections that clashed on name, re-pointing the loser's records to the winner.

Merging can also queue transactions of our own, as the app does (the `isJoining`
flag in BTDatabaseImple's merge methods suppresses them): a ConflictRecord when
an incoming baby/selection loses a name clash, a RELIVE when an incoming delete
is refused because the record is in use, and a repeat of every delete that was
applied. See `enqueue`.

How each record type is stored is defined in records.py.
"""

from . import records
from .database import BabyTrackerLocalDatabase
import logging
import base64
import json
import time
import uuid

_LOGGER = logging.getLogger(__name__)

# Op codes (TransactionLogOpCode in the Android app)
OP_INSERT, OP_UPDATE, OP_DELETE, OP_RELIVE, OP_CONFLICT = 0, 1, 2, 3, 4

# Merge results (BTDatabaseImple: Success, Ignored, Rejected, Error).
# Only ERROR means the transaction could not be applied.
SUCCESS, IGNORED, REJECTED, ERROR = "success", "ignored", "rejected", "error"


class TransactionHandler:
    """Handles Baby Tracker transactions"""

    def __init__(self, database: BabyTrackerLocalDatabase, enqueue=None):
        """
        Initialize with a database connection.

        enqueue(op_code, record_dict) queues a transaction of ours for upload;
        without it nothing is echoed.
        """
        self.db = database
        self.enqueue = enqueue
        # True while joining a group (the initial seed and first sync): nothing is echoed
        self.joining = False
        # Per merge: the transaction as received, and whether we may queue echoes for it
        self._raw = None
        self._emit = False

    def process_transaction(self, transaction, apply_to_db=True, echo=True, own_device=False):
        """
        Apply a transaction; returns False only if it could not be applied.

        echo=False is for our own new records, own_device=True for transactions
        downloaded from our own device ID (they are our past work coming back).
        """
        return self.merge(transaction, echo=echo, own_device=own_device) != ERROR

    def merge(self, transaction, echo=True, own_device=False):
        """Apply a transaction and return SUCCESS, IGNORED, REJECTED or ERROR."""
        if "Transaction" not in transaction or "SyncID" not in transaction or "OPCode" not in transaction:
            _LOGGER.warning(f"Incomplete transaction: {transaction}")
            return ERROR

        sync_id = transaction["SyncID"]
        try:
            op_code = int(transaction["OPCode"])
            data = json.loads(base64.b64decode(transaction["Transaction"]).decode('utf-8'))
            _LOGGER.debug(f"Processing transaction {sync_id} (OpCode: {op_code}): "
                          f"{data.get('BCObjectType', '')} - {data.get('objectID', '')}")
            self._raw = data
            self._emit = bool(echo and not own_device and not self.joining and self.enqueue)

            if op_code == OP_CONFLICT:
                return self._merge_conflict(data)

            record = self._normalize(data)
            if record is None:
                _LOGGER.debug(f"Skipping unsupported object type: {data.get('BCObjectType', '')}")
                return IGNORED

            if op_code == OP_INSERT:
                return self._merge_insert(record)
            if op_code == OP_UPDATE:
                return self._merge_update(record)
            if op_code == OP_DELETE:
                return self._merge_delete(record)
            if op_code == OP_RELIVE:
                if own_device:
                    # A relive we sent, coming back: it must not mark the record as
                    # awaiting a delete that was already dealt with
                    return IGNORED
                return self._merge_relive(record)

            _LOGGER.warning(f"Unhandled operation code: {op_code}")
            return ERROR
        except Exception as e:
            _LOGGER.error(f"Error processing transaction {sync_id}: {e}", exc_info=True)
            return ERROR

    # ----- merge operations -------------------------------------------------

    @staticmethod
    def _type(record):
        return records.canonical_type(record.get("BCObjectType", ""))

    def _table(self, record):
        return records.record_type(self._type(record)).table

    def _is_named(self, record):
        """Babies and selections: unique by name, protected from deletion while used."""
        return self._type(record) == "Baby" or records.record_type(self._type(record)).selection

    def _echo(self, op_code, record):
        """Queue a transaction of ours triggered by this merge (unless joining, or it is our own)."""
        if not self._emit:
            return
        try:
            self.enqueue(op_code, record)
        except Exception as e:  # the merge itself succeeded; the app only logs this too
            _LOGGER.error(f"Could not queue op {op_code} for upload: {e}")

    def _local_timestamp(self, record):
        return self.db.get_row_timestamp(self._table(record), record.get("objectID", ""))

    def _apply(self, record):
        self.db.upsert_record(self._type(record), record)
        return SUCCESS

    def _merge_insert(self, record):
        if self._local_timestamp(record) is not None:
            return self._merge_update(record)

        # A different record with the same name is a conflict; the older one wins
        if self._is_named(record) and record.get("name"):
            clash = self.db.find_id_by_name(self._table(record), record["name"])
            if clash and clash[0] != record.get("objectID"):
                local_id, local_ts = clash
                if local_ts < self.db.convert_timestamp(record.get("timestamp")):
                    _LOGGER.info(f"{self._type(record)} '{record['name']}' already exists locally and is older; keeping it")
                    # buildConflictRecord(winner = ours, loser = theirs)
                    winner = self.db.get_named_wire(self._type(record), local_id)
                    if winner is not None:
                        self._echo(OP_CONFLICT, {
                            "BCObjectType": "ConflictRecord",
                            "objectID": str(uuid.uuid4()),
                            "timestamp": records.format_date(time.time()),
                            "newFlage": True,
                            "winner": winner,
                            "loser": self._raw,
                        })
                    return REJECTED
                self.db.merge_references(self._table(record), records.usages(self._type(record)),
                                         record["objectID"], local_id)

        return self._apply(record)

    def _merge_update(self, record):
        local_ts = self._local_timestamp(record)
        if local_ts is None or local_ts < self.db.convert_timestamp(record.get("timestamp")):
            return self._apply(record)
        # Local copy is the same age or newer
        return IGNORED

    def _merge_delete(self, record):
        object_id = record.get("objectID", "")
        if self._is_named(record):
            # A pending relive swallows the echoed delete
            if self.db.pop_relive(object_id):
                return SUCCESS
            if self.db.is_referenced(records.usages(self._type(record)), object_id):
                _LOGGER.info(f"Not deleting {self._type(record)} {object_id}: it still has records")
                # Tell the other devices to bring it back: a RELIVE of our copy
                local = self.db.get_named_wire(self._type(record), object_id)
                if local is not None:
                    self._echo(OP_RELIVE, local)
                return REJECTED
        if self._local_timestamp(record) is None:
            return IGNORED
        self.db.delete_record(self._type(record), object_id)
        # Repeat the delete under our device, as the app does after every merged delete
        self._echo(OP_DELETE, self._raw)
        return SUCCESS

    def _merge_relive(self, record):
        if not self._is_named(record):
            _LOGGER.warning(f"Relive is only valid for babies and selections, got {self._type(record)}")
            return ERROR
        if self._local_timestamp(record) is not None:
            self.db.add_relive(record["objectID"])
            return SUCCESS
        return self._merge_insert(record)

    def _merge_conflict(self, data):
        """ConflictRecord {winner, loser}: fold the loser into the winner."""
        winner, loser = data.get("winner"), data.get("loser")
        if not isinstance(winner, dict) or not isinstance(loser, dict):
            return ERROR
        winner, loser = self._normalize(winner), self._normalize(loser)
        if winner is None or loser is None:
            return IGNORED
        if not self._is_named(loser):
            return ERROR
        if self._local_timestamp(loser) is None:
            return IGNORED
        if winner["objectID"] != loser["objectID"]:
            self.db.merge_references(self._table(loser), records.usages(self._type(loser)),
                                     winner["objectID"], loser["objectID"])
        return self._apply(winner)

    # ----- record normalisation ---------------------------------------------

    def _normalize(self, data):
        """
        Validate a decoded record and return it ready to store, or None if its
        type isn't one we keep.
        """
        object_type = records.canonical_type(data.get("BCObjectType", ""))

        # Baths logged as an "other activity" named Bath are kept as baths, so
        # the bath sensors see them. Deliberate (added 2025-12); not app behaviour.
        if object_type == "OtherActivity":
            desc = data.get("desc")
            if isinstance(desc, dict) and desc.get("name") == "Bath":
                _LOGGER.debug("Treating OtherActivity named 'Bath' as a Bath record")
                data = {**data, "BCObjectType": "Bath", "bathType": desc}
                data.pop("desc", None)
                object_type = "Bath"

        record_type = records.record_type(object_type)
        if record_type is None:
            return None
        if record_type.baby and not records.ref_id(data, "baby"):
            raise ValueError(f"Missing baby information for {object_type} object: {data.get('objectID', 'unknown')}")
        return {**data, "BCObjectType": object_type}
