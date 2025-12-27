"""Baby Tracker core functionality."""

from .api import BabyTrackerAPI
from .database import BabyTrackerLocalDatabase
import os
from datetime import datetime, timezone
import sqlite3
import logging

from .models import Baby

_LOGGER = logging.getLogger(__name__)

class BabyTracker:
    """
    Unified wrapper for Baby Tracker functionality.
    Combines API and database access with a simple interface.
    Always requires network connectivity for adding records.
    """
    def __init__(self, db_path=None, async_mode=False):
        """Initialize the BabyTracker wrapper."""
        # Set up database path - use the provided path or a default in the config directory
        self.db_path = db_path
        self.async_mode = async_mode
        self.db = None
        
        # Create components
        self.api = BabyTrackerAPI(async_mode=async_mode, db_path=self.db_path)
        
        # State tracking
        self.is_authenticated = False
        self.last_sync_time = None
        
        # Create parent directory if it doesn't exist
        if self.db_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            _LOGGER.info(f"Database path set to: {self.db_path}")
    
    def authenticate(self, email, password, device_uuid=None):
        """
        Authenticate with the Baby Tracker service.
        
        Args:
            email: User email
            password: User password
            device_uuid: Optional device UUID (will generate if None)
            
        Returns:
            dict: Authentication result
        """
        try:
            # Always initialize the database object first
            self.db = BabyTrackerLocalDatabase(self.db_path)
            
            # Make sure API has reference to the database
            self.api.local_db = self.db
            
            # Check if we're already in a group
            in_group = self.is_in_group()
            
            # Ensure database directory exists
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            
            # If not in a group, we need to join
            if not in_group:
                # Use join_group instead of just login
                _LOGGER.info(f"Not in a group, joining with {email}")
                result = self.api.join_group(email, password, device_uuid)
            else:
                # Just log in
                _LOGGER.info(f"Already in a group, logging in with {email}")
                login_result = self.api.login(email, password, device_uuid)

                if not login_result:
                    return {
                        "status": "error",
                        "message": "Login failed"
                    }

                # After login, populate baby_info from database for the API
                baby_info_from_db = self.get_baby_info()
                if baby_info_from_db:
                    # Convert Baby model to dict for API
                    # Normalize timezone format (UTC -> +0000)
                    dob = baby_info_from_db.dob.replace(" UTC", " +0000") if baby_info_from_db.dob else ""
                    due_day = baby_info_from_db.due_day.replace(" UTC", " +0000") if baby_info_from_db.due_day else ""

                    self.api.baby_info = {
                        "objectID": baby_info_from_db.object_id,
                        "name": baby_info_from_db.name,
                        "dob": dob,
                        "dueDay": due_day,
                        "gender": baby_info_from_db.gender,
                        "pictureName": baby_info_from_db.picture_name,
                        "timestamp": baby_info_from_db.timestamp,
                        "BCObjectType": "Baby"
                    }
                    _LOGGER.info(f"Loaded baby info from database for API: {baby_info_from_db.name}")
                else:
                    # If no baby in database, try to get from devices
                    _LOGGER.warning("No baby found in database, attempting to get from devices")
                    self.api.get_baby_info_from_devices()

            self.is_authenticated = True

            # Get baby info
            baby_info = self.get_baby_info()
            
            return {
                "status": "success",
                "message": "Authentication successful",
                "baby_info": baby_info,
                "in_group": True
            }
        except Exception as e:
            _LOGGER.error(f"Authentication failed: {str(e)}")
            return {
                "status": "error", 
                "message": f"Authentication failed: {str(e)}"
            }

    def sync(self):
        """
        Synchronize data with the server.
        
        Returns:
            dict: Sync results with counts of transactions
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        
        result = {
            "status": "pending",
            "synced_transactions": 0,
            "last_sync_time": datetime.now()
        }
        
        try:
            # Sync transactions from server
            transactions = self.api.sync_transactions()
            result["synced_transactions"] = len(transactions)
            result["status"] = "success"
        except Exception as e:
            _LOGGER.error(f"Sync failed: {str(e)}")
            result["status"] = "error"
            result["message"] = f"Sync failed: {str(e)}"
        
        self.last_sync_time = result["last_sync_time"]
        return result
    
    # === Data Access Methods ===
    # These methods read from the local database
    def is_in_group(self):
        """
        Determine if we're in a group by checking database state.
        
        Returns:
            bool: True if in a group, False otherwise
        """
        # If database doesn't exist, definitely not in a group
        if not os.path.exists(self.db_path):
            _LOGGER.info(f"Database doesn't exist at {self.db_path}, not in a group.")
            return False
        
        try:
            # Connect directly to the database
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Check if Baby table exists and has records
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='Baby'")
            if not cursor.fetchone():
                _LOGGER.info("Baby table doesn't exist, not in a group.")
                conn.close()
                return False
            
            # Check if there's at least one baby record
            cursor.execute("SELECT COUNT(*) FROM Baby")
            baby_count = cursor.fetchone()[0]
            _LOGGER.info(f"Found {baby_count} baby records.")
            
            # Check if DeviceSyncInfo table exists and has records
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='DeviceSyncInfo'")
            has_device_table = cursor.fetchone() is not None
            
            device_count = 0
            if has_device_table:
                cursor.execute("SELECT COUNT(*) FROM DeviceSyncInfo")
                device_count = cursor.fetchone()[0]
                _LOGGER.info(f"Found {device_count} device records.")
            else:
                _LOGGER.info("DeviceSyncInfo table doesn't exist.")
            
            conn.close()
            
            # If we have babies and devices, we're in a group
            in_group = baby_count > 0
            _LOGGER.info(f"In group: {in_group}")
            return in_group
        except Exception as e:
            # If we can't check, assume not in a group
            _LOGGER.error(f"Error checking group status: {e}")
            return False
    
    def get_baby_info(self):
        """
        Get information about the baby.

        Returns:
            dict: Baby information
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_baby_info()

    def download_baby_picture(self, picture_name, save_dir):
        """
        Download a baby's picture and save it locally.

        Args:
            picture_name: The filename of the picture (e.g., '91B377F6-A50D-4576-B4ED-98028B5B1ABE.jpg')
            save_dir: Directory to save the picture to

        Returns:
            str: Local path to the saved picture, or None if download failed
        """
        if not self.is_authenticated:
            _LOGGER.error("Cannot download picture: not authenticated")
            return None

        if not picture_name:
            _LOGGER.debug("No picture name provided")
            return None

        try:
            # Create the save directory if it doesn't exist
            os.makedirs(save_dir, exist_ok=True)

            # Check if we already have this picture
            local_path = os.path.join(save_dir, picture_name)
            if os.path.exists(local_path):
                _LOGGER.debug(f"Picture already exists locally: {local_path}")
                return local_path

            # Check if we already tried and failed
            placeholder_path = local_path + ".failed"
            if os.path.exists(placeholder_path):
                _LOGGER.debug(f"Picture download previously failed: {picture_name}")
                return None

            # Download the picture from the API
            picture_data = self.api.get_picture(picture_name)
            if not picture_data:
                # Only log once per picture to avoid spam
                _LOGGER.debug(f"Could not download picture: {picture_name}")
                # Create an empty placeholder to prevent repeated attempts
                placeholder_path = local_path + ".failed"
                if not os.path.exists(placeholder_path):
                    with open(placeholder_path, 'w') as f:
                        f.write("download_failed")
                return None

            # Save the picture locally
            with open(local_path, 'wb') as f:
                f.write(picture_data)

            _LOGGER.info(f"Saved baby picture to: {local_path}")
            return local_path

        except Exception as e:
            _LOGGER.error(f"Error saving baby picture: {e}")
            return None

    def get_all_babies(self):
        """
        Get information about all babies.

        Returns:
            list: List of Baby objects
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_all_babies()

    def get_baby_by_name(self, name):
        """
        Get baby information by name.

        Args:
            name: Baby's name

        Returns:
            Baby: Baby object or None
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_baby_by_name(name)
    
    def get_feeding_summary(self, days=7, baby_id=None):
        """
        Get a summary of feeding data.

        Args:
            days: Number of days to include
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Feeding summary statistics
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return {}

        return self.db.get_feeding_summary(days, baby_id)

    def get_diaper_summary(self, days=7, baby_id=None):
        """
        Get a summary of diaper data.

        Args:
            days: Number of days to include
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Diaper summary statistics
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return {}

        return self.db.get_diaper_summary(days, baby_id)

    def get_all_pumped_sessions(self):
        """Get all pumped milk sessions."""
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []
                
        return self.db.get_all_pumped_sessions()

    def get_feedings(self, limit=50):
        """
        Get feeding records.
        
        Args:
            limit: Maximum number of records to return
            
        Returns:
            list: Feeding records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []
                
        return self.db.get_feedings(limit=limit)
    def time_since_last_feeding(self):
        """
        Get the time since recent feeding.
        
        Returns:
            dict: time record
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None
        return self.db.time_since_last_feeding()
    
    def get_last_feeding(self):
        """
        Get the most recent feeding.
        
        Returns:
            dict: Feeding record
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None
                
        return self.db.get_last_feeding()
    
    def get_last_temperature(self):
        """
        Get the most recent temperature reading.

        Returns:
            dict: Temperature record
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_temperature()

    def get_last_diaper(self):
        """
        Get the most recent diaper change by querying the Diaper table directly.
        Does NOT rely on the Progress table.

        Returns:
            dict: Diaper record with time, status, and details
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_diaper_direct()

    def get_last_sleep(self):
        """
        Get the most recent sleep by querying the Sleep table directly.
        Does NOT rely on the Progress table.

        Returns:
            dict: Sleep record with time, duration, and is_sleeping status
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_sleep_direct()

    def is_currently_sleeping(self):
        """
        Check if the baby is currently sleeping.

        Returns:
            bool: True if baby is currently sleeping (sleep duration=0), False otherwise
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return False

        return self.db.is_currently_sleeping()

    def get_last_nursing(self):
        """
        Get the most recent nursing session by querying the Nursing table directly.
        Does NOT rely on the Progress table.

        Returns:
            dict: Nursing record with time and durations
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_nursing_direct()

    def get_last_feed_time(self):
        """
        Get the time of the most recent feeding (any type) by querying tables directly.
        Does NOT rely on the Progress table.

        Returns:
            dict: Feed time info with type
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_feed_time_direct()

    def get_last_bath(self):
        """
        Get the most recent bath by querying the Bath table directly.

        Returns:
            dict: Bath record with time and type
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_bath_direct()

    def get_bath_records(self, limit=50):
        """
        Get bath records.

        Args:
            limit: Maximum number of records to return

        Returns:
            list: Bath records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_bath_records(limit)

    def log_bath(self, bath_type=None, note="", time=None):
        """
        Log a new bath record.

        Args:
            bath_type: Optional bath type (Bubble Bath, Sponge Bath, etc.)
            note: Optional note
            time: Optional time (defaults to now)

        Returns:
            dict: Result of the operation
        """
        _LOGGER.warning(f"=== core.log_bath called: bath_type={bath_type}, note={note}")
        if not self.is_authenticated:
            _LOGGER.error("=== log_bath: Not authenticated")
            return {"status": "error", "message": "Not authenticated"}

        # Use current time if not provided
        if not time:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        else:
            time_str = time.strftime("%Y-%m-%d %H:%M:%S +0000") if isinstance(time, datetime) else time

        # Include bath type in the note if provided
        if bath_type and note:
            full_note = f"{bath_type}: {note}"
        elif bath_type:
            full_note = bath_type
        else:
            full_note = note

        try:
            response = self.api.post_bath(
                time_str=time_str,
                bath_type=bath_type,
                note=note
            )
            # Trigger a sync to update local database right after posting
            self.sync()
            return {"status": "success", "message": "Bath record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add bath record: {str(e)}")
            return {"status": "error", "message": f"Failed to add bath record: {str(e)}"}

    def get_bath_types(self):
        """
        Get list of available bath types.

        Returns:
            list: Bath type names
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_bath_types()

    def get_last_pump(self, baby_id=None):
        """
        Get the most recent pump session by querying the Pump table directly.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Pump session record with time, durations, and amounts
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_pump_direct(baby_id)

    def get_pump_records(self, limit=50, baby_id=None):
        """
        Get pump session records.

        Args:
            limit: Maximum number of records to return
            baby_id: Optional baby ID to filter by

        Returns:
            list: Pump session records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_pump_records(limit, baby_id)

    def log_pump(self, baby_id, left_duration, right_duration, left_amount, right_amount,
                 is_english_scale, note, time=None):
        """
        Log a new pump session record directly to the database.

        Args:
            baby_id: Baby ID
            left_duration: Duration on left side (minutes)
            right_duration: Duration on right side (minutes)
            left_amount: Amount from left side
            right_amount: Amount from right side
            is_english_scale: Whether amounts are in oz (True) or ml (False)
            note: Optional note
            time: Optional time (defaults to now)

        Returns:
            bool: True if successful
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return False

        return self.db.log_pump(
            baby_id=baby_id,
            left_duration=left_duration,
            right_duration=right_duration,
            left_amount=left_amount,
            right_amount=right_amount,
            is_english_scale=is_english_scale,
            note=note,
            time=time
        )

    def get_pump_summary(self, days=7, baby_id=None):
        """
        Get a summary of pump session data.

        Args:
            days: Number of days to include
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Pump session summary statistics
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return {}

        return self.db.get_pump_summary(days, baby_id)

    def get_last_medicine(self):
        """
        Get the most recent medicine administration.

        Returns:
            dict: Medicine record with name, amount, unit, time, and note
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_medicine()

    def get_last_growth(self, baby_id=None):
        """
        Get the most recent growth measurement.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Growth record with weight, length, head, and units
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_growth_direct(baby_id)

    def get_growth_records(self, limit=50, baby_id=None):
        """
        Get growth measurement records.

        Args:
            limit: Maximum number of records to return
            baby_id: Optional baby ID to filter by

        Returns:
            list: Growth records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_growth_records(limit, baby_id)

    def log_growth(self, baby_id, weight, length, head, is_english_weight_scale,
                   is_english_length_scale, note="", time=None):
        """
        Log a new growth measurement record.

        Args:
            baby_id: Baby ID
            weight: Weight measurement
            length: Length/height measurement
            head: Head circumference measurement
            is_english_weight_scale: True for lbs, False for kg
            is_english_length_scale: True for inches, False for cm
            note: Optional note
            time: Optional time (defaults to now)

        Returns:
            bool: True if successful
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return False

        return self.db.log_growth(
            baby_id=baby_id,
            weight=weight,
            length=length,
            head=head,
            is_english_weight_scale=is_english_weight_scale,
            is_english_length_scale=is_english_length_scale,
            note=note,
            time=time
        )

    # ===== MILESTONE TRACKING =====

    def get_last_milestone(self, baby_id=None):
        """
        Get the most recent milestone.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Milestone record with milestone name and note
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_milestone_direct(baby_id)

    def get_milestone_records(self, limit=50, baby_id=None):
        """
        Get milestone records.

        Args:
            limit: Maximum number of records to return
            baby_id: Optional baby ID to filter by

        Returns:
            list: Milestone records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_milestone_records(limit, baby_id)

    def get_milestone_selections(self):
        """
        Get list of available milestones.

        Returns:
            list: Milestone selection records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_milestone_selections()

    def log_milestone(self, baby_id, milestone_selection_id, note="", time=None):
        """
        Log a new milestone achievement.

        Args:
            baby_id: Baby ID
            milestone_selection_id: Milestone selection ID
            note: Optional note
            time: Optional time (defaults to now)

        Returns:
            bool: True if successful
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return False

        return self.db.log_milestone(
            baby_id=baby_id,
            milestone_selection_id=milestone_selection_id,
            note=note,
            time=time
        )

    # ===== DOCTOR VISIT TRACKING =====

    def get_last_doctor_visit(self, baby_id=None):
        """
        Get the most recent doctor visit.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Doctor visit record with visit details
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_doctor_visit_direct(baby_id)

    def get_doctor_visit_records(self, limit=50, baby_id=None):
        """
        Get doctor visit records.

        Args:
            limit: Maximum number of records to return
            baby_id: Optional baby ID to filter by

        Returns:
            list: Doctor visit records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_doctor_visit_records(limit, baby_id)

    def log_doctor_visit(self, baby_id, is_appointment=True, visit_type=0,
                        note="", doctor_note="", symptom="", time=None):
        """
        Log a new doctor visit.

        Args:
            baby_id: Baby ID
            is_appointment: Whether this is a scheduled appointment
            visit_type: Type of visit
            note: Optional note
            doctor_note: Doctor's notes
            symptom: Symptoms
            time: Optional time (defaults to now)

        Returns:
            bool: True if successful
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return False

        return self.db.log_doctor_visit(
            baby_id=baby_id,
            is_appointment=is_appointment,
            visit_type=visit_type,
            note=note,
            doctor_note=doctor_note,
            symptom=symptom,
            time=time
        )

    # ===== VACCINE TRACKING =====

    def get_last_vaccine(self, baby_id=None):
        """
        Get the most recent vaccine.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Vaccine record with vaccine name and note
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_vaccine_direct(baby_id)

    def get_vaccine_records(self, limit=50, baby_id=None):
        """
        Get vaccine records.

        Args:
            limit: Maximum number of records to return
            baby_id: Optional baby ID to filter by

        Returns:
            list: Vaccine records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_vaccine_records(limit, baby_id)

    def get_vaccine_selections(self):
        """
        Get list of available vaccines.

        Returns:
            list: Vaccine selection records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_vaccine_selections()

    def log_vaccine(self, baby_id, vacc_id, note="", doc_visit_id="", time=None):
        """
        Log a new vaccine administration.

        Args:
            baby_id: Baby ID
            vacc_id: Vaccine selection ID
            note: Optional note
            doc_visit_id: Optional doctor visit ID
            time: Optional time (defaults to now)

        Returns:
            bool: True if successful
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return False

        return self.db.log_vaccine(
            baby_id=baby_id,
            vacc_id=vacc_id,
            note=note,
            doc_visit_id=doc_visit_id,
            time=time
        )

    def get_medicine_selections(self):
        """
        Get list of available medicines.
        
        Returns:
            list: Medicine selection records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []
                
        return self.db.get_medicine_selections()

    def get_medicine_records(self, limit=50):
        """
        Get medicine administration records.
        
        Args:
            limit: Maximum number of records to return
            
        Returns:
            list: Medicine administration records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []
                
        return self.db.get_medicine_records(limit)

    def get_activity_types(self):
        """
        Get list of available activity types.
        
        Returns:
            list: Activity type records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []
                
        return self.db.get_activity_types()

    def get_activity_records(self, limit=50):
        """
        Get other activity records.
        
        Args:
            limit: Maximum number of records to return
            
        Returns:
            list: Activity records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return []
                
        return self.db.get_activity_records(limit)
        
    # === Data Entry Methods ===
    # These methods always go through the API
    
    def add_diaper(self, time_str=None, pee=True, poo=False, pee_color=0, poo_color=0, 
                  texture=0, amount=2, note=""):
        """
        Add a diaper change record through the API.
        
        Args:
            time_str: Time string (optional, defaults to now)
            pee: Whether diaper was wet
            poo: Whether diaper was dirty
            pee_color: Color code for pee (0-5)
            poo_color: Color code for poo (0-5)
            texture: Texture code (0-5)
            amount: Amount (usually 2)
            note: Optional note text
            
        Returns:
            dict: Result of the operation
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        
        # Determine status (0=wet, 1=poopy, 2=mixed, 3=dry)
        status = 2 if pee and poo else 1 if poo else 0 if pee else 3
        
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        
        try:
            response = self.api.post_diaper(
                time_str=time_str,
                pee_color=pee_color,
                poo_color=poo_color,
                texture=texture,
                amount=amount,
                status=status,
                note=note
            )
            # Trigger a sync to update local database right after posting
            self.sync()
            return {"status": "success", "message": "Diaper record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add diaper record: {str(e)}")
            return {"status": "error", "message": f"Failed to add diaper record: {str(e)}"}
    
    def add_nursing(self, time_str=None, left_duration=0, right_duration=0, 
                   both_duration=0, finish_side=1, note=""):
        """
        Add a nursing session record through the API.
        
        Args:
            time_str: Time string (optional, defaults to now)
            left_duration: Duration on left side (minutes)
            right_duration: Duration on right side (minutes)
            both_duration: Duration on both sides (minutes)
            finish_side: Which side finished on (0=right, 1=left, 2=both)
            note: Optional note text
            
        Returns:
            dict: Result of the operation
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        
        try:
            response = self.api.post_nursing(
                time_str=time_str,
                left_duration=left_duration,
                right_duration=right_duration,
                both_duration=both_duration,
                finish_side=finish_side,
                note=note
            )
            # Trigger a sync to update local database right after posting
            self.sync()
            return {"status": "success", "message": "Nursing record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add nursing record: {str(e)}")
            return {"status": "error", "message": f"Failed to add nursing record: {str(e)}"}
    
    def add_pumped(self, time_str=None, amount=0, is_english_measure=False, note=""):
        """
        Add a pumped milk record through the API.
        
        Args:
            time_str: Time string (optional, defaults to now)
            amount: Amount of milk (in ml if is_english_measure=False, in oz if is_english_measure=True)
            is_english_measure: Whether amount is in oz (True) or ml (False)
            note: Optional note text
            
        Returns:
            dict: Result of the operation
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        
        try:
            response = self.api.post_pumped(
                time_str=time_str,
                amount=amount,
                is_english_measure=is_english_measure,
                note=note
            )
            # Trigger a sync to update local database right after posting
            self.sync()
            return {"status": "success", "message": "Pumped milk record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add pumped milk record: {str(e)}")
            return {"status": "error", "message": f"Failed to add pumped milk record: {str(e)}"}
    
    def add_formula(self, time_str=None, amount=0, is_english_measure=False, note=""):
        """
        Add a formula feeding record through the API.
        
        Args:
            time_str: Time string (optional, defaults to now)
            amount: Amount of formula (in ml if is_english_measure=False, in oz if is_english_measure=True)
            is_english_measure: Whether amount is in oz (True) or ml (False)
            note: Optional note text
            
        Returns:
            dict: Result of the operation
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        
        try:
            response = self.api.post_formula(
                time_str=time_str,
                amount=amount,
                is_english_measure=is_english_measure,
                note=note
            )
            # Trigger a sync to update local database right after posting
            self.sync()
            return {"status": "success", "message": "Formula feeding record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add formula feeding record: {str(e)}")
            return {"status": "error", "message": f"Failed to add formula feeding record: {str(e)}"}
    
    def add_temperature(self, time_str=None, temperature=98.6, is_fahrenheit=True, note=""):
        """
        Add a temperature record through the API.
        
        Args:
            time_str: Time string (optional, defaults to now)
            temperature: Temperature value
            is_fahrenheit: Whether temperature is in Fahrenheit (True) or Celsius (False)
            note: Optional note text
            
        Returns:
            dict: Result of the operation
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        
        try:
            response = self.api.post_temperature(
                time_str=time_str,
                temperature=temperature,
                is_fahrenheit=is_fahrenheit,
                note=note
            )
            # Trigger a sync to update local database right after posting
            self.sync()
            return {"status": "success", "message": "Temperature record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add temperature record: {str(e)}")
            return {"status": "error", "message": f"Failed to add temperature record: {str(e)}"}
            
    def add_medicine(self, time_str=None, med_id=None, amount=0, note=""):
        """
        Add a medicine administration record through the API.
        
        Args:
            time_str: Time string (optional, defaults to now)
            med_id: ID of the medicine to administer
            amount: Amount of medicine administered
            note: Optional note text
            
        Returns:
            dict: Result of the operation
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        
        try:
            response = self.api.post_medicine(
                time_str=time_str,
                med_id=med_id,
                amount=amount,
                note=note
            )
            # Trigger a sync to update local database right after posting
            self.sync()
            return {"status": "success", "message": "Medicine record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add medicine record: {str(e)}")
            return {"status": "error", "message": f"Failed to add medicine record: {str(e)}"}

    def log_sleep_event(self, baby_id, is_start=True, note=""):
        """
        Log a sleep start or end event.

        Args:
            baby_id: Baby's ID
            is_start: True for sleep start, False for sleep end/wake up
            note: Optional note text

        Returns:
            dict: Result of the operation
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}

        try:
            from datetime import datetime, timezone

            # Get current timestamp
            current_time = datetime.now(timezone.utc)
            time_unix = int(current_time.timestamp())
            time_str = current_time.strftime("%Y-%m-%d %H:%M:%S +0000")

            if is_start:
                # Starting sleep: post with duration = 0
                response = self.api.post_sleep(
                    time_str=time_str,
                    duration=0,
                    note=note
                )
                _LOGGER.info(f"Sleep started for baby {baby_id}, objectID: {response.get('objectID')}")
            else:
                # Ending sleep: get start time and objectID from local DB, calculate duration, UPDATE existing record
                _LOGGER.warning(f"=== Wake up requested for baby {baby_id}")
                if not self.db:
                    if os.path.exists(self.db_path):
                        self.db = BabyTrackerLocalDatabase(self.db_path)
                        self.api.local_db = self.db
                    else:
                        _LOGGER.error("=== Database not initialized")
                        return {"status": "error", "message": "Database not initialized"}

                _LOGGER.warning(f"=== Querying for active sleep with BabyID={baby_id}")
                cursor = self.db.conn.execute('''
                    SELECT ID, Time FROM Sleep
                    WHERE BabyID = ? AND Duration = 0
                    ORDER BY Time DESC
                    LIMIT 1
                ''', (baby_id,))

                row = cursor.fetchone()
                _LOGGER.warning(f"=== Database query result: {row}")
                if row:
                    sleep_object_id, start_time = row
                    duration_seconds = time_unix - start_time
                    # Convert to minutes (API uses minutes, not seconds)
                    duration_minutes = duration_seconds // 60

                    _LOGGER.warning(f"=== Found active sleep: objectID={sleep_object_id}, start_time={start_time}, duration={duration_minutes}min")

                    # UPDATE the existing sleep record (don't create a new one)
                    start_time_str = datetime.fromtimestamp(start_time, timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
                    response = self.api.update_sleep(
                        object_id=sleep_object_id,
                        time_str=start_time_str,
                        duration_minutes=duration_minutes,
                        note=note
                    )
                    _LOGGER.warning(f"=== update_sleep response: {response}")
                    _LOGGER.info(f"Sleep ended for baby {baby_id}, duration: {duration_minutes} minutes (objectID: {sleep_object_id})")
                else:
                    _LOGGER.warning(f"=== No active sleep session found for baby {baby_id}")
                    return {"status": "error", "message": "No active sleep session found"}

            # Trigger a sync to update local database
            self.sync()
            return {"status": "success", "message": "Sleep event logged"}
        except Exception as e:
            _LOGGER.error(f"Failed to log sleep event: {str(e)}")
            return {"status": "error", "message": f"Failed to log sleep event: {str(e)}"}

    def add_activity(self, time_str=None, activity_name="Tummy Time", duration=0, location_id=None, note=""):
        """
        Add an other activity record through the API.
        
        Args:
            time_str: Time string (optional, defaults to now)
            activity_name: Name of the activity (e.g., "Tummy Time")
            duration: Duration in minutes
            location_id: Optional location ID
            note: Optional note text
            
        Returns:
            dict: Result of the operation
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        
        try:
            response = self.api.post_other_activity(
                time_str=time_str,
                activity_name=activity_name,
                duration=duration,
                location_id=location_id,
                note=note
            )
            # Trigger a sync to update local database right after posting
            self.sync()
            return {"status": "success", "message": "Activity record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add activity record: {str(e)}")
            return {"status": "error", "message": f"Failed to add activity record: {str(e)}"}