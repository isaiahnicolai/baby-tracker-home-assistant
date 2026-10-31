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
"""

from .models import Baby, Diaper, Medication, MedicationSelection, Medicine, MedicineSelection, Nursing, Formula, OtherActivity, OtherActivityDesc, Pump, Pumped, Temperature, Sleep, OtherFeed, OtherFeedSelection, Milestone, MilestoneSelection, DoctorVisit, Vaccine, VaccineSelection, Growth, Bath, BathType
from .database import BabyTrackerLocalDatabase
import logging
import base64
import json

_LOGGER = logging.getLogger(__name__)

# Op codes (TransactionLogOpCode in the Android app)
OP_INSERT, OP_UPDATE, OP_DELETE, OP_RELIVE, OP_CONFLICT = 0, 1, 2, 3, 4

# Merge results (BTDatabaseImple: Success, Ignored, Rejected, Error).
# Only ERROR means the transaction could not be applied.
SUCCESS, IGNORED, REJECTED, ERROR = "success", "ignored", "rejected", "error"

# Local table for each synced object type
TABLE_FOR_TYPE = {
    "Baby": "Baby",
    "Diaper": "Diaper",
    "Nursing": "Nursing",
    "Pumped": "Pumped",
    "Pump": "Pump",
    "Formula": "Formula",
    "Temperature": "Temperature",
    "Sleep": "Sleep",
    "OtherFeed": "OtherFeed",
    "OtherFeedSelection": "OtherFeedSelection",
    "Medication": "Medicine",
    "Medicine": "Medicine",
    "MedicationSelection": "MedicineSelection",
    "MedicineSelection": "MedicineSelection",
    "OtherActivity": "OtherActivity",
    "OtherActivityDesc": "OtherActivityDesc",
    "OtherActivityDescription": "OtherActivityDesc",
    "Milestone": "Milestone",
    "MilestoneSelection": "MilestoneSelection",
    "DoctorVisit": "DoctorVisit",
    "Vaccine": "Vaccine",
    "VaccineSelection": "VaccineSelection",
    "Growth": "Growth",
    "Bath": "Bath",
    "BathType": "BathDesc",
}

# Where each selection type is used (BTDatabaseImple.selectionUsed). Selections
# not listed have no in-use check, as in the app.
SELECTION_USAGE = {
    "OtherActivityDesc": [("OtherActivity", "DescID")],
    "OtherActivityDescription": [("OtherActivity", "DescID")],
    "MilestoneSelection": [("Milestone", "MilestoneSelectionID")],
    "MedicineSelection": [("Medicine", "MedID")],
    "MedicationSelection": [("Medicine", "MedID")],
    "VaccineSelection": [("Vaccine", "VaccID")],
    "OtherFeedSelection": [("OtherFeed", "TypeID")],
    "BathType": [("Bath", "DescID")],
}

# Activities that belong to a baby. Pump is account-level in the app (no BabyID).
BABY_REQUIRED_TYPES = {
    "Diaper", "Nursing", "Pumped", "Formula", "Temperature", "Sleep", "OtherFeed",
    "Medication", "Medicine", "OtherActivity", "Milestone", "DoctorVisit",
    "Vaccine", "Growth", "Bath",
}

MODEL_FOR_TYPE = {
    "Baby": Baby,
    "Diaper": Diaper,
    "Nursing": Nursing,
    "Pumped": Pumped,
    "Pump": Pump,
    "Formula": Formula,
    "Temperature": Temperature,
    "Sleep": Sleep,
    "OtherFeed": OtherFeed,
    "Medication": Medication,
    "Medicine": Medicine,  # Support both Medication and Medicine
    "MedicationSelection": MedicationSelection,
    "MedicineSelection": MedicineSelection,  # Support both names
    "OtherFeedSelection": OtherFeedSelection,
    "OtherActivity": OtherActivity,
    "OtherActivityDesc": OtherActivityDesc,
    "OtherActivityDescription": OtherActivityDesc,  # Support both names
    "Milestone": Milestone,
    "MilestoneSelection": MilestoneSelection,
    "DoctorVisit": DoctorVisit,
    "Vaccine": Vaccine,
    "VaccineSelection": VaccineSelection,
    "Growth": Growth,
    "Bath": Bath,
    "BathType": BathType,
}


class TransactionHandler:
    """Handles Baby Tracker transactions"""

    def __init__(self, database: BabyTrackerLocalDatabase):
        """Initialize with a database connection"""
        self.db = database
        db = database
        # Insert handlers are all INSERT OR REPLACE, so they also serve as the
        # "overwrite" step of a timestamp-guarded update
        self._upsert = {
            "Baby": db.insert_baby_transaction,
            "Diaper": db.insert_diaper_transaction,
            "Nursing": db.insert_nursing_transaction,
            "Pumped": db.insert_pumped_transaction,
            "Formula": db.insert_formula_transaction,
            "Temperature": db.insert_temperature_transaction,
            "Sleep": db.insert_sleep_transaction,
            "OtherFeed": db.insert_other_feed_transaction,
            "OtherFeedSelection": db.insert_other_feed_selection_transaction,
            "Pump": db.insert_pump_transaction,
            "Medication": db.insert_medicine_transaction,
            "Medicine": db.insert_medicine_transaction,
            "MedicationSelection": db.insert_medicine_selection_transaction,
            "MedicineSelection": db.insert_medicine_selection_transaction,
            "OtherActivity": db.insert_other_activity_transaction,
            "OtherActivityDesc": db.insert_other_activity_desc_transaction,
            "OtherActivityDescription": db.insert_other_activity_desc_transaction,
            "Milestone": db.insert_milestone_transaction,
            "MilestoneSelection": db.insert_milestone_selection_transaction,
            "DoctorVisit": db.insert_doctor_visit_transaction,
            "Vaccine": db.insert_vaccine_transaction,
            "VaccineSelection": db.insert_vaccine_selection_transaction,
            "Growth": db.insert_growth_transaction,
            "Bath": db.insert_bath_transaction,
        }
        self._delete = {
            "Baby": db.delete_baby_transaction,
            "Diaper": db.delete_diaper_transaction,
            "Nursing": db.delete_nursing_transaction,
            "Pumped": db.delete_pumped_transaction,
            "Formula": db.delete_formula_transaction,
            "Temperature": db.delete_temperature_transaction,
            "Sleep": db.delete_sleep_transaction,
            "OtherFeed": db.delete_other_feed_transaction,
            "OtherFeedSelection": db.delete_other_feed_selection_transaction,
            "Pump": db.delete_pump_transaction,
            "Medication": db.delete_medicine_transaction,
            "Medicine": db.delete_medicine_transaction,
            "MedicationSelection": db.delete_medicine_selection_transaction,
            "MedicineSelection": db.delete_medicine_selection_transaction,
            "OtherActivity": db.delete_other_activity_transaction,
            "OtherActivityDesc": db.delete_other_activity_desc_transaction,
            "OtherActivityDescription": db.delete_other_activity_desc_transaction,
            "Milestone": db.delete_milestone_transaction,
            "DoctorVisit": db.delete_doctor_visit_transaction,
            "Vaccine": db.delete_vaccine_transaction,
            "Growth": db.delete_growth_transaction,
            "Bath": db.delete_bath_transaction,
        }

    def process_transaction(self, transaction, apply_to_db=True):
        """Apply a transaction; returns False only if it could not be applied."""
        return self.merge(transaction) != ERROR

    def merge(self, transaction):
        """Apply a transaction and return SUCCESS, IGNORED, REJECTED or ERROR."""
        if "Transaction" not in transaction or "SyncID" not in transaction or "OPCode" not in transaction:
            _LOGGER.warning(f"Incomplete transaction: {transaction}")
            return ERROR

        sync_id = transaction["SyncID"]
        try:
            op_code = int(transaction["OPCode"])
            decoded_data = json.loads(base64.b64decode(transaction["Transaction"]).decode('utf-8'))
            object_type = decoded_data.get("BCObjectType", "")
            _LOGGER.debug(f"Processing transaction {sync_id} (OpCode: {op_code}): {object_type} - {decoded_data.get('objectID', '')}")

            if op_code == OP_CONFLICT:
                return self._merge_conflict(decoded_data)

            model_obj = self._create_model_from_data(decoded_data)
            if not model_obj:
                _LOGGER.debug(f"Skipping unsupported object type: {object_type}")
                return IGNORED

            if op_code == OP_INSERT:
                return self._merge_insert(model_obj)
            if op_code == OP_UPDATE:
                return self._merge_update(model_obj)
            if op_code == OP_DELETE:
                return self._merge_delete(model_obj)
            if op_code == OP_RELIVE:
                return self._merge_relive(model_obj)

            _LOGGER.warning(f"Unhandled operation code: {op_code}")
            return ERROR
        except Exception as e:
            _LOGGER.error(f"Error processing transaction {sync_id}: {e}", exc_info=True)
            return ERROR

    # ----- merge operations -------------------------------------------------

    def _table(self, model_obj):
        return TABLE_FOR_TYPE.get(model_obj.object_type)

    def _usages(self, object_type):
        if object_type == "Baby":
            return [(t, "BabyID") for t in self.db.BABY_REFERENCE_TABLES]
        return SELECTION_USAGE.get(object_type, [])

    def _apply(self, model_obj):
        handler = self._upsert.get(model_obj.object_type)
        if not handler:
            _LOGGER.debug(f"No insert handler for object type: {model_obj.object_type}")
            return IGNORED
        return SUCCESS if handler(model_obj.to_dict()) else ERROR

    def _merge_insert(self, model_obj):
        table = self._table(model_obj)
        if table and self.db.get_row_timestamp(table, model_obj.object_id) is not None:
            return self._merge_update(model_obj)

        # Baby and selection names are unique; a different record with the same
        # name is a conflict, which the older record wins
        if model_obj.object_type == "Baby" or model_obj.object_type in SELECTION_USAGE:
            name = getattr(model_obj, "name", None)
            clash = self.db.find_id_by_name(table, name) if name else None
            if clash and clash[0] != model_obj.object_id:
                local_id, local_ts = clash
                if local_ts < self.db.convert_timestamp(model_obj.timestamp):
                    _LOGGER.info(f"{model_obj.object_type} '{name}' already exists locally and is older; keeping it")
                    return REJECTED
                self.db.merge_references(table, self._usages(model_obj.object_type), model_obj.object_id, local_id)

        return self._apply(model_obj)

    def _merge_update(self, model_obj):
        table = self._table(model_obj)
        local_ts = self.db.get_row_timestamp(table, model_obj.object_id) if table else None
        if local_ts is None:
            return self._apply(model_obj)
        if local_ts < self.db.convert_timestamp(model_obj.timestamp):
            return self._apply(model_obj)
        # Local copy is the same age or newer
        return IGNORED

    def _merge_delete(self, model_obj):
        object_type = model_obj.object_type
        if object_type == "Baby" or object_type in SELECTION_USAGE:
            # A pending relive swallows the echoed delete
            if self.db.pop_relive(model_obj.object_id):
                return SUCCESS
            if self.db.is_referenced(self._usages(object_type), model_obj.object_id):
                _LOGGER.info(f"Not deleting {object_type} {model_obj.object_id}: it still has records")
                return REJECTED

        table = self._table(model_obj)
        if table and self.db.get_row_timestamp(table, model_obj.object_id) is None:
            return IGNORED
        handler = self._delete.get(object_type)
        if handler:
            return SUCCESS if handler(model_obj.to_dict()) else ERROR
        if table:
            return SUCCESS if self.db.delete_row(table, model_obj.object_id) else ERROR
        return IGNORED

    def _merge_relive(self, model_obj):
        if model_obj.object_type != "Baby" and model_obj.object_type not in SELECTION_USAGE:
            _LOGGER.warning(f"Relive is only valid for babies and selections, got {model_obj.object_type}")
            return ERROR
        table = self._table(model_obj)
        if self.db.get_row_timestamp(table, model_obj.object_id) is not None:
            self.db.add_relive(model_obj.object_id)
            return SUCCESS
        return self._merge_insert(model_obj)

    def _merge_conflict(self, data):
        """ConflictRecord {winner, loser}: fold the loser into the winner."""
        winner_data, loser_data = data.get("winner"), data.get("loser")
        if not isinstance(winner_data, dict) or not isinstance(loser_data, dict):
            return ERROR
        loser = self._create_model_from_data(loser_data)
        winner = self._create_model_from_data(winner_data)
        if not loser or not winner:
            return IGNORED
        if loser.object_type != "Baby" and loser.object_type not in SELECTION_USAGE:
            return ERROR
        table = self._table(loser)
        if self.db.get_row_timestamp(table, loser.object_id) is None:
            return IGNORED
        if winner.object_id != loser.object_id:
            self.db.merge_references(table, self._usages(loser.object_type), winner.object_id, loser.object_id)
        return self._apply(winner)

    # ----- model construction ----------------------------------------------

    def _create_model_from_data(self, data):
        """Create an appropriate model object based on data type"""
        object_type = data.get("BCObjectType", "")

        # Special handling: OtherActivity with desc.name == "Bath" should be treated as a Bath
        if object_type == "OtherActivity":
            try:
                desc = data.get("desc", {})
                desc_name = desc.get("name", "") if isinstance(desc, dict) else ""
                if desc_name == "Bath":
                    _LOGGER.info(f"Converting OtherActivity with desc.name='Bath' to Bath record")
                    # Handle pictureLoaded which could be bool or string
                    pic_loaded = data.get("pictureLoaded", False)
                    if isinstance(pic_loaded, str):
                        pic_loaded = pic_loaded.lower() == "true"
                    # Transform the data to Bath format
                    bath_data = {
                        "BCObjectType": "Bath",
                        "objectID": data.get("objectID", ""),
                        "timestamp": data.get("timestamp", ""),
                        "time": data.get("time", ""),
                        "note": data.get("note", ""),
                        "baby": data.get("baby", {}),
                        "hasPicture": pic_loaded,
                        "descID": desc.get("objectID", ""),
                        # Map desc to bathType format
                        "bathType": {
                            "objectID": desc.get("objectID", ""),
                            "name": desc.get("name", "Bath"),
                        }
                    }
                    object_type = "Bath"
                    data = bath_data
            except Exception as e:
                _LOGGER.warning(f"Failed to convert OtherActivity to Bath: {e}, continuing as OtherActivity")

        # Verify baby information is present for types that require it
        if object_type in BABY_REQUIRED_TYPES:
            baby_data = data.get("baby", {})
            if not isinstance(baby_data, dict) or not baby_data.get("objectID"):
                raise ValueError(f"Missing baby information for {object_type} object: {data.get('objectID', 'unknown')}")

        model_class = MODEL_FOR_TYPE.get(object_type)
        if not model_class:
            return None
        model = model_class(data)

        if object_type in BABY_REQUIRED_TYPES and not model.baby_id:
            raise ValueError(f"Failed to set baby_id for {object_type} object: {model.object_id}")

        return model


class TransactionLogOpCode:
    """Enum representing the different operation codes for transactions"""
    INSERT = "0"  # Used when creating a new record
    UPDATE = "1"  # Used when updating an existing record
    DELETE = "2"  # Used when deleting a record
    RELIVE = "3"  # Used to restore a previously deleted record
    CONFLICT = "4"  # Used for handling sync conflicts
