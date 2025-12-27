#transaction.py

from .models import Baby, Diaper, Medication, MedicationSelection, Medicine, MedicineSelection, Nursing, Formula, OtherActivity, OtherActivityDesc, Pump, Pumped, Temperature, Sleep, OtherFeed, Milestone, MilestoneSelection, DoctorVisit, Vaccine, VaccineSelection, Growth, Bath, BathType
from .database import BabyTrackerLocalDatabase
import logging
import base64
import json
import os 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("BabyTrackerTransaction")


class TransactionHandler:
    """Handles Baby Tracker transactions"""
    
    def __init__(self, database:BabyTrackerLocalDatabase):
        """Initialize with a database connection"""
        self.db = database
    
    def process_transaction(self, transaction, apply_to_db=True):
        """Process a transaction and apply it to the database if needed"""
        if "Transaction" not in transaction or "SyncID" not in transaction or "OPCode" not in transaction:
            logger.warning(f"Incomplete transaction: {transaction}")
            return False
            
        sync_id = transaction["SyncID"]
        op_code = int(transaction["OPCode"])
        
        try:
            # Decode the transaction data
            transaction_data = base64.b64decode(transaction["Transaction"])
            decoded_data = json.loads(transaction_data.decode('utf-8'))
            object_type = decoded_data.get("BCObjectType", "")
            object_id = decoded_data.get("objectID", "")

            # Debug: Log raw Bath transactions to compare formats
            if object_type == "Bath":
                logger.warning(f"=== RAW BATH TRANSACTION FROM SERVER: {json.dumps(decoded_data, indent=2)}")
            
            logger.info(f"Processing transaction {sync_id} (OpCode: {op_code}): {object_type} - {object_id}")
            
            # Create the appropriate model object
            model_obj = self._create_model_from_data(decoded_data)

            if not model_obj:
                logger.debug(f"Skipping unsupported object type: {object_type}")
                return True  # Return True to skip unsupported types (not a failure)
                
            # Process based on operation code
            if op_code == 0:  # INSERT
                return self._handle_insert(model_obj)
            elif op_code == 1:  # UPDATE
                return self._handle_update(model_obj)
            elif op_code == 2:  # DELETE
                return self._handle_delete(model_obj)
         
            else:
                logger.warning(f"Unhandled operation code: {op_code}")
                return False
                
        except Exception as e:
            logger.error(f"Error processing transaction {sync_id}: {e}", exc_info=True)
            return False
            
    def _create_model_from_data(self, data):
        """Create an appropriate model object based on data type"""
        object_type = data.get("BCObjectType", "")

        # Special handling: OtherActivity with desc.name == "Bath" should be treated as a Bath
        if object_type == "OtherActivity":
            try:
                desc = data.get("desc", {})
                desc_name = desc.get("name", "") if isinstance(desc, dict) else ""
                if desc_name == "Bath":
                    logger.info(f"Converting OtherActivity with desc.name='Bath' to Bath record")
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
                logger.warning(f"Failed to convert OtherActivity to Bath: {e}, continuing as OtherActivity")
        
        # Check if this object type requires a baby reference
        baby_required_types = [
            "Diaper", "Nursing", "Pumped", "Formula",
            "Temperature", "Sleep", "OtherFeed", "Medication", "Medicine",
            "OtherActivity", "Pump", "Milestone", "DoctorVisit", "Vaccine",
            "Growth", "Bath"
        ]
        
        # Verify baby information is present for types that require it
        if object_type in baby_required_types:
            baby_data = data.get("baby", {})
            if not isinstance(baby_data, dict) or not baby_data.get("objectID"):
                error_msg = f"Missing baby information for {object_type} object: {data.get('objectID', 'unknown')}"
                logger.error(error_msg)
                raise ValueError(error_msg)
        
        # Map object types to model classes
        type_map = {
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
        
        # Create and return the appropriate model
        model_class = type_map.get(object_type)
        if model_class:
            model = model_class(data)
            
            # Double-check that baby_id was set correctly in the model if required
            if object_type in baby_required_types and not model.baby_id:
                error_msg = f"Failed to set baby_id for {object_type} object: {model.object_id}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            return model
        return None
        
    def _handle_insert(self, model_obj):
        """Handle INSERT operations"""
        # Map model types to database insert methods
        
        handlers = {
            "Diaper": self.db.insert_diaper_transaction,
            "Nursing": self.db.insert_nursing_transaction,
            "Pumped": self.db.insert_pumped_transaction,
            "Formula": self.db.insert_formula_transaction,
            "Temperature": self.db.insert_temperature_transaction,
            "Sleep": self.db.insert_sleep_transaction,
            "OtherFeed": self.db.insert_other_feed_transaction,
            "Pump": self.db.insert_pump_transaction,
            "Medication": self.db.insert_medicine_transaction,
            "Medicine": self.db.insert_medicine_transaction,  # Support both names
            "MedicationSelection": self.db.insert_medicine_selection_transaction,
            "MedicineSelection": self.db.insert_medicine_selection_transaction,  # Support both names
            "OtherActivity": self.db.insert_other_activity_transaction,
            "Milestone": self.db.insert_milestone_transaction,
            "DoctorVisit": self.db.insert_doctor_visit_transaction,
            "Vaccine": self.db.insert_vaccine_transaction,
            "Growth": self.db.insert_growth_transaction,
            "Bath": self.db.insert_bath_transaction,
        }

        # Get the handler and call it
        handler = handlers.get(model_obj.object_type)
        if handler:
            return handler(model_obj.to_dict())
        logger.debug(f"No insert handler for object type: {model_obj.object_type}")
        return True  # Skip unsupported types gracefully
    def _handle_update(self, model_obj):
        """Handle UPDATE operations"""
        # Map model types to database update methods
        handlers = {
            "Diaper": self.db.update_diaper_transaction,
            "Nursing": self.db.update_nursing_transaction,
            "Pumped": self.db.update_pumped_transaction,
            "Formula": self.db.update_formula_transaction,
            "Temperature": self.db.update_temperature_transaction,
            "Sleep": self.db.update_sleep_transaction,
            "OtherFeed": self.db.update_other_feed_transaction,
            "Pump": self.db.update_pump_transaction,
            "Medication": self.db.update_medicine_transaction,
            "Medicine": self.db.update_medicine_transaction,  # Support both names
            "MedicationSelection": self.db.update_medicine_selection_transaction,
            "MedicineSelection": self.db.update_medicine_selection_transaction,  # Support both names
            "OtherActivity": self.db.update_other_activity_transaction,
            "OtherActivityDesc": self.db.update_other_activity_desc_transaction,
            "OtherActivityDescription": self.db.update_other_activity_desc_transaction,
            "Milestone": self.db.update_milestone_transaction,
            "DoctorVisit": self.db.update_doctor_visit_transaction,
            "Vaccine": self.db.update_vaccine_transaction,
            "Growth": self.db.update_growth_transaction,
            "Bath": self.db.update_bath_transaction,
        }

        # Get the handler and call it
        handler = handlers.get(model_obj.object_type)
        if handler:
            return handler(model_obj.to_dict())
        logger.debug(f"No update handler for object type: {model_obj.object_type}")
        return True  # Skip unsupported types gracefully
        
    def _handle_delete(self, model_obj):
        """Handle DELETE operations"""
        # Map model types to database delete methods
        handlers = {
            "Diaper": self.db.delete_diaper_transaction,
            "Nursing": self.db.delete_nursing_transaction,
            "Pumped": self.db.delete_pumped_transaction,
            "Formula": self.db.delete_formula_transaction,
            "Temperature": self.db.delete_temperature_transaction,
            "Sleep": self.db.delete_sleep_transaction,
            "OtherFeed": self.db.delete_other_feed_transaction,
            "Pump": self.db.delete_pump_transaction,
            "Medication": self.db.delete_medicine_transaction,
            "Medicine": self.db.delete_medicine_transaction,  # Support both names
            "MedicationSelection": self.db.delete_medicine_selection_transaction,
            "MedicineSelection": self.db.delete_medicine_selection_transaction,  # Support both names
            "OtherActivity": self.db.delete_other_activity_transaction,
            "OtherActivityDesc": self.db.delete_other_activity_desc_transaction,
            "OtherActivityDescription": self.db.delete_other_activity_desc_transaction,
            "Milestone": self.db.delete_milestone_transaction,
            "DoctorVisit": self.db.delete_doctor_visit_transaction,
            "Vaccine": self.db.delete_vaccine_transaction,
            "Growth": self.db.delete_growth_transaction,
            "Bath": self.db.delete_bath_transaction,
        }

        # Get the handler and call it
        handler = handlers.get(model_obj.object_type)
        if handler:
            return handler(model_obj.to_dict())
        logger.debug(f"No delete handler for object type: {model_obj.object_type}")
        return True  # Skip unsupported types gracefully
class SyncCallback:
    """Callback for asynchronous API operations"""
    def sync_done(self, result):
        """Called when a sync operation is completed"""
        pass
        
    def sync_progress(self, result):
        """Called to provide progress updates"""
        pass

class SyncResult:
    """Result of a sync operation"""
    def __init__(self):
        self.result_code = 0  # 0 means success
        self.result_value = None
        self.call_context = None
        self.error = None
class TransactionLogOpCode:
    """Enum representing the different operation codes for transactions"""
    INSERT = "0"  # Used when creating a new record
    UPDATE = "1"  # Used when updating an existing record
    DELETE = "2"  # Used when deleting a record
    RELIVE = "3"  # Used to restore a previously deleted record
    CONFLICT = "4"  # Used for handling sync conflicts


class DeviceSyncInfo:
    """Information about a synced device"""
    def __init__(self, device_uuid, last_sync_id, device_name="", device_os_info=""):
        self.device_uuid = device_uuid
        self.last_sync_id = last_sync_id
        self.device_name = device_name
        self.device_os_info = device_os_info
        
    @property
    def DeviceUUID(self):
        return self.device_uuid
        
    @property
    def LastSyncID(self):
        return self.last_sync_id
        
    @property
    def DeviceName(self):
        return self.device_name
        
    @property
    def DeviceOSInfo(self):
        return self.device_os_info
