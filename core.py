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
    
    def get_feeding_summary(self, days=7):
        """
        Get a summary of feeding data.
        
        Args:
            days: Number of days to include
            
        Returns:
            dict: Feeding summary statistics
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return {}
                
        return self.db.get_feeding_summary(days)
    
    def get_diaper_summary(self, days=7):
        """
        Get a summary of diaper data.
        
        Args:
            days: Number of days to include
            
        Returns:
            dict: Diaper summary statistics
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path)
                self.api.local_db = self.db
            else:
                return {}
                
        return self.db.get_diaper_summary(days)

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