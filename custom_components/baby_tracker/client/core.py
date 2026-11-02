"""Baby Tracker core functionality."""

from .api import JOIN_PENDING, AccountResetError, AuthenticationError, BabyTrackerAPI
from .database import IN_PROGRESS_SLEEP_SECONDS, BabyTrackerLocalDatabase
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import functools
import logging
import threading
import time as _time
import uuid

from . import dbconn as sqlite3  # sqlite3 with a busy timeout and WAL
from . import insights, photos, records
from .dbconn import remove_sidecar_files
from .models import Baby
from .transaction import OP_UPDATE

_LOGGER = logging.getLogger(__name__)

PICTURE_RETRY_SECONDS = 24 * 3600  # how long a picture the server doesn't have is left alone


def _now_string():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")


def _time_str(time):
    """API date string for a datetime/string time, or None for now."""
    if isinstance(time, datetime):
        return time.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
    return time or None

class BabyTracker:
    """
    Unified wrapper for Baby Tracker functionality.
    Combines API and database access with a simple interface.
    Always requires network connectivity for adding records.
    """
    def __init__(self, db_path=None, async_mode=False, time_zone=None, tz=None):
        """
        Initialize the BabyTracker wrapper.

        Args:
            time_zone: IANA zone name, used for the timezone offset sent to the server
                (and for day boundaries when tz is not given)
            tz: tzinfo that "today" and night hours are worked out in. Defaults to the
                zone named by time_zone, else the system's local zone.
        """
        # Set up database path - use the provided path or a default in the config directory
        self.db_path = db_path
        self.async_mode = async_mode
        self.db = None
        if tz is None and time_zone:
            try:
                tz = ZoneInfo(time_zone)
            except Exception as e:
                _LOGGER.warning(f"Unknown time zone {time_zone!r}, using host zone: {e}")
        self.tz = tz  # None means the system's local zone

        # Create components
        self.api = BabyTrackerAPI(async_mode=async_mode, db_path=self.db_path,
                                  time_zone=time_zone or tz)
        
        # State tracking
        self.is_authenticated = False
        self._credentials = None  # (email, password, device_uuid) of the last authenticate, to sign in again
        self.last_sync_time = None
        # Held by sync and every write (see _serialized, below). Re-entrant: force_resync
        # authenticates and syncs.
        self._lock = threading.RLock()
        
        # Create parent directory if it doesn't exist
        if self.db_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            _LOGGER.info(f"Database path set to: {self.db_path}")
    
    def authenticate(self, email, password, device_uuid=None, sync_history=True):
        """
        Authenticate with the Baby Tracker service.

        Args:
            email: User email
            password: User password
            device_uuid: Optional device UUID (will generate if None)
            sync_history: when joining a group for the first time, also replay
                the account's history now (False: the first sync() does it)

        Returns:
            dict: Authentication result
        """
        self._credentials = (email, password, device_uuid)
        try:
            # Always initialize the database object first
            self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
            
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
                result = self.api.join_group(email, password, device_uuid, sync_history=sync_history)
                if result.get("status") != "success":
                    return {"status": "error", "message": result.get("message") or "Joining the group failed"}
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
        except (AuthenticationError, AccountResetError):
            raise
        except Exception as e:
            _LOGGER.error(f"Authentication failed: {str(e)}")
            return {
                "status": "error", 
                "message": f"Authentication failed: {str(e)}"
            }

    def _post(self, what, post, **kwargs):
        """Run an api.post_* call, reporting failure as an error result."""
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        try:
            return post(**kwargs)
        except Exception as e:
            _LOGGER.error(f"Failed to add {what}: {e}")
            return {"status": "error", "message": f"Failed to add {what}: {e}"}

    def sync(self, picture_dir=None):
        """
        Synchronize data with the server: merge other devices' changes,
        download the activity pictures they refer to, then upload ours (the
        app's order).

        Args:
            picture_dir: directory to keep activity pictures in. Pictures are
                only downloaded (and deleted along with their activity) when
                this is given.

        Returns:
            dict: Sync results with counts of transactions
        """
        if not self.is_authenticated and self._credentials:
            # A failed force resync (or any lost session) leaves us signed out: sign in again
            # rather than failing every later sync
            _LOGGER.info("Not signed in; authenticating before syncing")
            auth = self.authenticate(*self._credentials)
            if auth.get("status") != "success":
                return {"status": "error", "message": f"Not authenticated: {auth.get('message')}"}
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}

        result = {
            "status": "pending",
            "synced_transactions": 0,
            "last_sync_time": datetime.now()
        }

        try:
            if picture_dir and self.db:
                self.db.picture_dir = picture_dir
            # Same order as the app: merge other devices' changes, download
            # photos, then upload ours
            transactions = self.api.sync_transactions()
            result["synced_transactions"] = len(transactions)
            if picture_dir:
                try:
                    result["downloaded_pictures"] = self.api.download_pending_pictures(picture_dir)
                except Exception as e:
                    # As in the app, a photo problem doesn't stop our records going up
                    _LOGGER.warning(f"Picture download failed: {e}")
                    result["picture_error"] = str(e)
            result["status"] = "success"
            try:
                result["uploaded_transactions"] = self.api.upload_pending()
            except (AuthenticationError, AccountResetError):
                raise
            except Exception as e:
                # What we downloaded is merged; the unsent records stay queued and go up on a later sync
                _LOGGER.warning(f"Upload failed, will retry on the next sync: {e}")
                result["upload_error"] = str(e)
        except (AuthenticationError, AccountResetError):
            raise
        except Exception as e:
            _LOGGER.error(f"Sync failed: {str(e)}")
            result["status"] = "error"
            result["message"] = f"Sync failed: {str(e)}"

        self.last_sync_time = result["last_sync_time"]
        return result

    def pending_upload_count(self):
        """How many records were logged here but haven't been uploaded to the server yet."""
        if not self.db:
            if self.db_path and os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return 0
        return len(self.db.get_pending_transactions())

    def force_resync(self, email, password, device_uuid=None):
        """
        Force a complete resync by deleting the local database and re-downloading
        all data from the server. This is useful when the group leader resets sync
        and all clients need to reconnect.

        Args:
            email: User email for re-authentication
            password: User password for re-authentication

        Returns:
            dict: Result of the force resync operation
        """
        _LOGGER.info("Starting force resync - deleting local database and re-syncing")

        try:
            # Records logged here but not yet uploaded live only in this database
            if self.db:
                try:
                    self.api.upload_pending()
                except AccountResetError:
                    # The queue belongs to the old group and can't be sent to the new one
                    _LOGGER.warning("Account was reset; discarding records that were never uploaded")
                except Exception as e:
                    pending = len(self.db.get_pending_transactions())
                    return {
                        "status": "error",
                        "message": f"{pending} record(s) haven't been uploaded yet ({e}); "
                                   "try again once the server is reachable",
                    }

            # Step 1: Delete the local database
            if os.path.exists(self.db_path):
                try:
                    os.remove(self.db_path)
                    remove_sidecar_files(self.db_path)
                    _LOGGER.info(f"Deleted database at: {self.db_path}")
                except Exception as e:
                    _LOGGER.error(f"Failed to delete database: {e}")
                    return {"status": "error", "message": f"Failed to delete database: {str(e)}"}

            # Step 2: Reset internal state
            self.db = None
            self.api.local_db = None
            self.api.transaction_handler = None
            self.api._merge_failures = {}
            self.api.baby_info = None
            self.api.devices = None
            # The new database is synced with whatever account we log in to now
            # (it is also the only way past an AccountResetError)
            self.api.account_id = None
            self.api.is_authenticated = False
            self.is_authenticated = False

            # Step 3: Re-join the group (downloads seed database and syncs all transactions)
            _LOGGER.info("Re-joining group to download fresh data")
            result = self.api.join_group(email, password, device_uuid)

            if result.get("status") == "success":
                # Re-initialize the database reference
                self.db = self.api.local_db
                self.is_authenticated = True
                _LOGGER.info("Force resync completed successfully")
                return {
                    "status": "success",
                    "message": f"Force resync completed. {result.get('message', '')}"
                }
            else:
                _LOGGER.error(f"Force resync failed: {result.get('message')}")
                return result

        except Exception as e:
            _LOGGER.error(f"Force resync failed: {str(e)}")
            return {"status": "error", "message": f"Force resync failed: {str(e)}"}
    
    def needs_first_sync(self):
        """
        Whether this client has not finished joining the account yet: there is no
        local database, or the account's history has not been fully replayed into it.
        The next authenticate() and sync() do (or finish) that, which can take a while.
        """
        if not self.is_in_group():
            return True
        try:
            db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
            return db.get_sync_state(JOIN_PENDING) is not None
        except Exception as e:  # noqa: BLE001 - an unreadable database needs the join redone
            _LOGGER.warning(f"Could not read the join state of {self.db_path}: {e}")
            return True

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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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

            # The app asks for pictureName + ".jpg"; a name that already carries an extension is used as it is
            picture_name = os.path.basename(picture_name.replace("\\", "/"))  # never a path
            if not os.path.splitext(picture_name)[1]:
                picture_name += ".jpg"

            # Check if we already have this picture
            local_path = os.path.join(save_dir, picture_name)
            if os.path.exists(local_path):
                _LOGGER.debug(f"Picture already exists locally: {local_path}")
                return local_path

            # A picture the server said it doesn't have isn't asked for again for a day (it may
            # be uploaded since)
            placeholder_path = local_path + ".failed"
            if os.path.exists(placeholder_path):
                if _time.time() - os.path.getmtime(placeholder_path) < PICTURE_RETRY_SECONDS:
                    _LOGGER.debug(f"Picture is not on the server: {picture_name}")
                    return None
                os.remove(placeholder_path)

            # Download the picture from the API
            picture_data = self.api.get_picture(picture_name)
            if not picture_data:
                _LOGGER.debug(f"Could not download picture: {picture_name}")
                # Only a definite "not found" is remembered. Any other failure (a timeout, a
                # server error, a dropped session) is tried again on the next refresh.
                if self.api.last_picture_status == 404:
                    with open(placeholder_path, 'w') as f:
                        f.write("not_found")
                return None

            # Save the picture locally
            with open(local_path, 'wb') as f:
                f.write(picture_data)

            _LOGGER.info(f"Saved baby picture to: {local_path}")
            return local_path

        except Exception as e:
            _LOGGER.error(f"Error saving baby picture: {e}")
            return None

    def download_baby_landscape_picture(self, picture_name, save_dir):
        """
        Download the landscape variant of a baby's picture, the app's "<pictureName>_l.jpg"
        (Baby.getPictureLandscapeFile), next to the portrait. Not every baby has one on the
        server; like the portrait it is remembered as missing for a day.

        Args:
            picture_name: The baby's pictureName, with or without ".jpg"
            save_dir: Directory to save the picture to

        Returns:
            str: Local path to the saved picture, or None if there is none
        """
        if not picture_name:
            return None
        base = os.path.basename(picture_name.replace("\\", "/"))
        if base.lower().endswith(".jpg"):
            base = base[:-4]
        return self.download_baby_picture(f"{base}_l.jpg", save_dir)

    def get_all_babies(self):
        """
        Get information about all babies.

        Returns:
            list: List of Baby objects
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return {}

        return self.db.get_diaper_summary(days, baby_id)

    def get_all_pumped_sessions(self):
        """Get all pumped milk sessions."""
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return []
                
        return self.db.get_all_pumped_sessions()

    def get_feedings(self, limit=50, baby_id=None):
        """
        Get feeding records.

        Args:
            limit: Maximum number of records to return
            baby_id: Optional baby ID to filter by

        Returns:
            list: Feeding records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_feedings(limit=limit, baby_id=baby_id)
    def time_since_last_feeding(self, baby_id=None):
        """
        Get the time since recent feeding.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: time record
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return None
        return self.db.time_since_last_feeding(baby_id)
    
    def get_last_feeding(self, baby_id=None):
        """
        Get the most recent feeding.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Feeding record
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_feeding(baby_id)
    
    def get_last_temperature(self, baby_id=None):
        """
        Get the most recent temperature reading.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Temperature record
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_temperature(baby_id)

    def get_daily_summary(self, baby_id=None):
        """Get today's daily summary totals."""
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return {}
        return self.db.get_daily_summary(baby_id)

    def get_sleep_analysis(self, baby_id=None, days=14):
        """Get sleep/bedtime analysis over the last N days."""
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return {}
        return self.db.get_sleep_analysis(baby_id, days)

    def get_today_wet_diaper_count(self, baby_id=None):
        """
        Get the count of wet diapers for today.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            int: Count of wet diapers today
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return 0

        return self.db.get_today_wet_diaper_count(baby_id)

    def get_last_diaper(self, baby_id=None):
        """
        Get the most recent diaper change by querying the Diaper table directly.
        Does NOT rely on the Progress table.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Diaper record with time, status, and details
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_diaper_direct(baby_id)

    def get_last_sleep(self, baby_id=None):
        """
        Get the most recent sleep by querying the Sleep table directly.
        Does NOT rely on the Progress table.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Sleep record with time, duration, and is_sleeping status
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_sleep_direct(baby_id)

    def is_currently_sleeping(self, baby_id=None):
        """
        Check if the baby is currently sleeping.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            bool: True if baby is currently sleeping (sleep duration=0), False otherwise
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return False

        return self.db.is_currently_sleeping(baby_id)

    def get_last_nursing(self, baby_id=None):
        """
        Get the most recent nursing session by querying the Nursing table directly.
        Does NOT rely on the Progress table.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Nursing record with time and durations
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_nursing_direct(baby_id)

    def get_last_feed_time(self, baby_id=None):
        """
        Get the time of the most recent feeding (any type) by querying tables directly.
        Does NOT rely on the Progress table.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Feed time info with type
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_feed_time_direct(baby_id)

    def get_last_bath(self, baby_id=None):
        """
        Get the most recent bath by querying the Bath table directly.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Bath record with time and type
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_bath_direct(baby_id)

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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_bath_records(limit)

    def log_bath(self, baby_id, bath_type=None, note="", time=None):
        """
        Log a new bath record.

        Args:
            bath_type: Optional bath type (Bubble Bath, Sponge Bath, etc.)
            note: Optional note
            time: Optional time (defaults to now)

        Returns:
            dict: Result of the operation
        """
        _LOGGER.debug(f"core.log_bath called: bath_type={bath_type}, note={note}")
        if not self.is_authenticated:
            _LOGGER.error("log_bath: Not authenticated")
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
                baby_id=baby_id,
                time_str=time_str,
                bath_type=bath_type,
                note=note
            )
            return {**response, "message": "Bath record added"}
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return False

        # Pumps belong to the account, not a baby (Android Pump has no BabyID),
        # so baby_id is accepted for compatibility but not sent
        return self._post("pump session", self.api.post_pump,
            time_str=_time_str(time),
            left_duration=left_duration,
            right_duration=right_duration,
            left_amount=left_amount,
            right_amount=right_amount,
            is_english_scale=is_english_scale,
            note=note
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return {}

        return self.db.get_pump_summary(days, baby_id)

    def get_last_medicine(self, baby_id=None):
        """
        Get the most recent medicine administration.

        Args:
            baby_id: Optional baby ID to filter by

        Returns:
            dict: Medicine record with name, amount, unit, time, and note
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_medicine(baby_id)

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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return False

        return self._post("growth measurement", self.api.post_growth,
            baby_id=baby_id,
            time_str=_time_str(time),
            weight=weight,
            length=length,
            head=head,
            is_english_weight_scale=is_english_weight_scale,
            is_english_length_scale=is_english_length_scale,
            note=note
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return False

        return self._post("milestone", self.api.post_milestone,
            baby_id=baby_id,
            milestone_selection_id=milestone_selection_id,
            time_str=_time_str(time),
            note=note
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return False

        # The app has no doctor-visit link on vaccines (DocVisitID is "NotUsed")
        return self._post("vaccine", self.api.post_vaccine,
            baby_id=baby_id,
            vacc_id=vacc_id,
            time_str=_time_str(time),
            note=note
        )

    def get_medicine_selections(self):
        """
        Get list of available medicines.
        
        Returns:
            list: Medicine selection records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
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
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return []
                
        return self.db.get_activity_types()

    def get_activity_records(self, limit=50, baby_id=None):
        """
        Get other activity records.

        Args:
            limit: Maximum number of records to return
            baby_id: Optional baby ID to filter by (defaults to the first baby)

        Returns:
            list: Activity records
        """
        if not self.db:
            if os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return []
                
        return self.db.get_activity_records(limit, baby_id)
        
    # === Data Entry Methods ===
    # These methods always go through the API
    
    def add_diaper(self, baby_id, time_str=None, pee=True, poo=False, pee_color=5, poo_color=5,
                  texture=5, amount=2, note=""):
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
        
        # DiaperStatus: 0=wet, 1=poopy, 2=mixed. The app stores dry as wet with
        # DiaperAmount None (0), never as status 3.
        status = 2 if pee and poo else 1 if poo else 0
        if not pee and not poo:
            amount = 0
        
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        
        try:
            response = self.api.post_diaper(
                baby_id=baby_id,
                time_str=time_str,
                pee_color=pee_color,
                poo_color=poo_color,
                texture=texture,
                amount=amount,
                status=status,
                note=note
            )
            return {**response, "message": "Diaper record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add diaper record: {str(e)}")
            return {"status": "error", "message": f"Failed to add diaper record: {str(e)}"}
    
    def add_nursing(self, baby_id, time_str=None, left_duration=0, right_duration=0, 
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
                baby_id=baby_id,
                time_str=time_str,
                left_duration=left_duration,
                right_duration=right_duration,
                both_duration=both_duration,
                finish_side=finish_side,
                note=note
            )
            return {**response, "message": "Nursing record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add nursing record: {str(e)}")
            return {"status": "error", "message": f"Failed to add nursing record: {str(e)}"}
    
    def add_pumped(self, baby_id, time_str=None, amount=0, is_english_measure=False, note=""):
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
                baby_id=baby_id,
                time_str=time_str,
                amount=amount,
                is_english_measure=is_english_measure,
                note=note
            )
            return {**response, "message": "Pumped milk record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add pumped milk record: {str(e)}")
            return {"status": "error", "message": f"Failed to add pumped milk record: {str(e)}"}
    
    def add_formula(self, baby_id, time_str=None, amount=0, is_english_measure=False, note=""):
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
                baby_id=baby_id,
                time_str=time_str,
                amount=amount,
                is_english_measure=is_english_measure,
                note=note
            )
            return {**response, "message": "Formula feeding record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add formula feeding record: {str(e)}")
            return {"status": "error", "message": f"Failed to add formula feeding record: {str(e)}"}
    
    def add_temperature(self, baby_id, time_str=None, temperature=98.6, is_fahrenheit=True, note=""):
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
                baby_id=baby_id,
                time_str=time_str,
                temperature=temperature,
                is_fahrenheit=is_fahrenheit,
                note=note
            )
            return {**response, "message": "Temperature record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add temperature record: {str(e)}")
            return {"status": "error", "message": f"Failed to add temperature record: {str(e)}"}
            
    def add_medicine(self, baby_id, time_str=None, med_id=None, amount=0, note=""):
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
                baby_id=baby_id,
                time_str=time_str,
                med_id=med_id,
                amount=amount,
                note=note
            )
            return {**response, "message": "Medicine record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add medicine record: {str(e)}")
            return {"status": "error", "message": f"Failed to add medicine record: {str(e)}"}

    def log_sleep_event(self, baby_id, is_start=True, note="", time=None):
        """
        Log a sleep start or end event.

        Args:
            baby_id: Baby's ID
            is_start: True for sleep start, False for sleep end/wake up
            note: Optional note text
            time: When it happened, a datetime or "YYYY-MM-DD HH:MM:SS +0000"
                (defaults to now)

        Returns:
            dict: Result of the operation
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}

        try:
            from datetime import datetime, timezone

            # The event's timestamp: when it was said to happen, else now
            if time and not isinstance(time, datetime):
                time = datetime.strptime(time, "%Y-%m-%d %H:%M:%S %z")
            current_time = time.astimezone(timezone.utc) if time else datetime.now(timezone.utc)
            time_unix = int(current_time.timestamp())
            time_str = current_time.strftime("%Y-%m-%d %H:%M:%S +0000")

            if is_start:
                # Starting sleep: post with duration = 0
                response = self.api.post_sleep(
                    baby_id=baby_id,
                    time_str=time_str,
                    duration=0,
                    note=note
                )
                _LOGGER.info(f"Sleep started for baby {baby_id}, objectID: {response.get('objectID')}")
            else:
                # Ending sleep: get start time and objectID from local DB, calculate duration, UPDATE existing record
                _LOGGER.debug(f"Wake up requested for baby {baby_id}")
                if not self.db:
                    if os.path.exists(self.db_path):
                        self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                        self.api.local_db = self.db
                    else:
                        _LOGGER.error("Database not initialized")
                        return {"status": "error", "message": "Database not initialized"}

                _LOGGER.debug(f"Querying for active sleep with BabyID={baby_id}")

                # Use a proper connection - BabyTrackerLocalDatabase does not have a .conn attribute
                conn = sqlite3.connect(self.db_path)
                try:
                    cursor = conn.execute('''
                        SELECT ID, Time FROM Sleep
                        WHERE BabyID = ? AND Duration = 0 AND Time >= ?
                        ORDER BY Time DESC
                        LIMIT 1
                    ''', (baby_id, time_unix - IN_PROGRESS_SLEEP_SECONDS))

                    row = cursor.fetchone()
                finally:
                    conn.close()

                _LOGGER.debug(f"Active sleep query result: {row}")
                if row:
                    sleep_object_id, start_time = row
                    duration_seconds = time_unix - start_time
                    if duration_seconds < 0:
                        return {"status": "error", "message": "The sleep can't end before it started"}
                    # Minutes (the API's unit). Never 0: a Duration of 0 means "still sleeping",
                    # so a sleep ended within its first minute would stay open
                    duration_minutes = max(1, round(duration_seconds / 60))

                    _LOGGER.debug(f"Found active sleep: objectID={sleep_object_id}, start_time={start_time}, duration={duration_minutes}min")

                    # UPDATE the existing sleep record (don't create a new one)
                    start_time_str = datetime.fromtimestamp(start_time, timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
                    response = self.api.update_sleep(
                        baby_id=baby_id,
                        object_id=sleep_object_id,
                        time_str=start_time_str,
                        duration_minutes=duration_minutes,
                        note=note
                    )
                    _LOGGER.debug(f"update_sleep response: {response}")
                    _LOGGER.info(f"Sleep ended for baby {baby_id}, duration: {duration_minutes} minutes (objectID: {sleep_object_id})")
                else:
                    _LOGGER.warning(f"No active sleep session found for baby {baby_id}")
                    return {"status": "error", "message": "No active sleep session found"}

            return {"status": "success", "message": "Sleep event logged"}
        except Exception as e:
            _LOGGER.error(f"Failed to log sleep event: {str(e)}")
            return {"status": "error", "message": f"Failed to log sleep event: {str(e)}"}

    def add_activity(self, baby_id, time_str=None, activity_name="Tummy Time", duration=0, location_id=None, note=""):
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
                baby_id=baby_id,
                time_str=time_str,
                activity_name=activity_name,
                duration=duration,
                location_id=location_id,
                note=note
            )
            return {**response, "message": "Activity record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add activity record: {str(e)}")
            return {"status": "error", "message": f"Failed to add activity record: {str(e)}"}

    def get_last_activity(self, baby_id=None):
        """The most recent other activity (tummy time and the like), or None."""
        if not self.db:
            if self.db_path and os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return None

        return self.db.get_last_activity(baby_id)

    def get_other_feed_selections(self):
        """The foods that can be logged with add_other_feed, as dicts with id and name."""
        if not self.db:
            if self.db_path and os.path.exists(self.db_path):
                self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
                self.api.local_db = self.db
            else:
                return []

        return self.db.get_other_feed_selections()

    def _create_selection(self, what, name, existing, post, **kwargs):
        """Create a selection unless one of that name exists (case-insensitive); either way report its id."""
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        name = (name or "").strip()
        if not name:
            return {"status": "error", "message": f"A {what} needs a name"}
        try:
            found = next((row for row in existing() if (row["name"] or "").strip().lower() == name.lower()), None)
            if found:
                return {"status": "success", "objectID": found["id"], "existing": True,
                        "message": f"The {what} {found['name']} already existed"}
            response = post(name=name, **kwargs)
            return {**response, "existing": False, "message": f"Created the {what} {name}"}
        except Exception as e:
            _LOGGER.error(f"Failed to create {what}: {e}")
            return {"status": "error", "message": f"Failed to create {what}: {e}"}

    def create_medicine(self, name, amount_per_time=0.0, unit="", interval_hours=0, prescription=False):
        """
        Create a medicine (once: an existing one of that name, ignoring case, is returned as is).

        Returns:
            dict: {"status": "success", "objectID": <the medicine's id>, "message": ...}
        """
        return self._create_selection(
            "medicine", name, self.get_medicine_selections, self.api.post_medicine_selection,
            amount_per_time=amount_per_time, unit=unit, interval_hours=interval_hours, prescription=prescription)

    def create_food(self, name, is_bottle=False):
        """
        Create a food for add_other_feed (once: an existing one of that name, ignoring case, is returned as is).

        Returns:
            dict: {"status": "success", "objectID": <the food's id>, "message": ...}
        """
        return self._create_selection(
            "food", name, self.get_other_feed_selections, self.api.post_other_feed_selection, is_bottle=is_bottle)

    def add_other_feed(self, baby_id, time_str=None, feed_type_id=None, amount=0, unit="",
                       is_english_measure=True, note=""):
        """
        Add a solids/supplement feed of one of the account's foods (see
        get_other_feed_selections) through the API.

        Args:
            time_str: Time string (optional, defaults to now)
            feed_type_id: ID of the OtherFeedSelection
            amount: How much, in the given unit
            unit: The unit's name, e.g. "tbsp"
            is_english_measure: Whether the amount is in English units
            note: Optional note text

        Returns:
            dict: Result of the operation
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}

        if not time_str:
            time_str = _time_str(datetime.now().astimezone())

        try:
            response = self.api.post_other_feed(
                baby_id=baby_id,
                feed_type_id=feed_type_id,
                time_str=time_str,
                amount=amount,
                unit=unit,
                is_english_measure=is_english_measure,
                note=note
            )
            return {**response, "message": "Solids feeding record added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add solids feeding record: {str(e)}")
            return {"status": "error", "message": f"Failed to add solids feeding record: {str(e)}"}

    # ===== INSIGHTS =====

    # How far back feeds are read to learn the baby's rhythm
    _INSIGHT_FEED_DAYS = 7
    # A first weight within this many days of birth is taken as the birth weight
    _BIRTH_WEIGHT_DAYS = 14

    # ===== DELETE AND UNDO =====

    def get_recent_records(self, baby_id, limit=10, within_hours=None):
        """
        The newest records of one baby across the types that can be logged here, newest first.

        Each item is {"object_type", "object_id", "time", "kind", "note"}: object_type is the
        registry's name (what delete_record takes), time is ISO 8601 with the tracker's zone,
        and kind a short lowercase label such as "wet diaper", "formula 4 oz" or
        "nursing L 10 / R 8". Pump sessions belong to the account, not a baby, so they are
        not listed.

        Args:
            limit: Most records to return
            within_hours: Only records from this many hours back (default: any age)
        """
        db = self._open_db()
        if db is None:
            return []
        return db.get_recent_records(baby_id, limit=limit, within_hours=within_hours)

    def _photo_dir(self, picture_dir):
        """Where a new photo goes: the given folder, else the one the sync uses."""
        picture_dir = picture_dir or (self.db.picture_dir if self.db else None)
        if not picture_dir:
            raise ValueError("No picture folder: pass picture_dir (or sync with one) before adding photos")
        return picture_dir

    def _stage_photo(self, photo_path, picture_dir, activity_id):
        """
        Store a photo for an entry: the files go into the picture folder, are queued for
        upload, and the pictureNote entry that refers to them is returned. The upload
        happens with the record (api.upload_pending), photos first.
        """
        picture_dir = self._photo_dir(picture_dir)
        file_name, path, thumbnail = photos.import_photo(photo_path, picture_dir)
        self.db.picture_dir = picture_dir
        self.db.add_photo_upload(path)
        self.db.add_photo_upload(thumbnail)
        return records.picture_wire(file_name, file_name, activity_id, _now_string(), new=True)

    def add_joy(self, baby_id, note="", time_str=None, photo_path=None, picture_dir=None):
        """
        Log a joy, optionally with a photo (what the app's Joy entry takes).

        Args:
            note: Optional note text
            time_str: Time string (optional, defaults to now)
            photo_path: An image file to attach (any format Pillow reads; stored as a JPEG
                with a thumbnail, and uploaded with the joy)
            picture_dir: Where photos are kept (default: the folder the last sync used)

        Returns:
            dict: Result of the operation; "queued" is True while the joy or its photo
                still has to be uploaded, which the next sync does
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        object_id = str(uuid.uuid4())
        pictures = []
        try:
            if photo_path:
                pictures.append(self._stage_photo(photo_path, picture_dir, object_id))
            response = self.api.post_joy(baby_id, time_str=_time_str(time_str), note=note,
                                         pictures=pictures, object_id=object_id)
            return {**response, "message": "Joy added"}
        except Exception as e:
            _LOGGER.error(f"Failed to add joy: {e}")
            return {"status": "error", "message": f"Failed to add joy: {e}"}

    def attach_photo(self, object_type, object_id, photo_path, picture_dir=None):
        """
        Add a photo to an entry that already exists (a diaper, a joy, a bath...), the way
        the app does when you add one while editing it: the entry is sent again as an
        update that lists its pictures with the new one.

        Args:
            object_type: The entry's type as get_recent_records gives it, e.g. "Diaper"
            object_id: The entry's ID
            photo_path: An image file (see add_joy)
            picture_dir: Where photos are kept (default: the folder the last sync used)

        Returns:
            dict: {"status": "success", "objectID", "pictureID", "queued"} or
                {"status": "error", "message"}
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        record_type = records.record_type(object_type)
        if record_type is None or record_type.selection or not record_type.activity:
            return {"status": "error", "message": f"{object_type} entries can't have photos"}
        if records.canonical_type(object_type) == "DoctorVisit":
            return {"status": "error", "message": "Doctor visits are not synced, so they can't have photos"}
        try:
            wire = self.db.get_record_wire(object_type, object_id, self.api._tz_offset())
            if wire is None:
                return {"status": "error", "message": f"{object_type} {object_id} not found"}
            existing = [records.picture_wire(p["ID"], p["FileName"], object_id, records.format_date(p["Timestamp"]),
                                             p["Type"]) for p in self.db.get_activity_pictures(object_id)]
            picture = self._stage_photo(photo_path, picture_dir, object_id)
            wire["pictureNote"] = existing + [picture]
            # An update only replaces an older copy, and dates have whole-second resolution
            wire["timestamp"] = max(
                _now_string(), records.format_date(self.db.convert_timestamp(wire["timestamp"]) + 1))
            response = self.api._post_record(wire, op_code=OP_UPDATE)
            return {**response, "pictureID": picture["objectID"], "message": "Photo added"}
        except Exception as e:
            _LOGGER.error(f"Failed to attach photo to {object_type} {object_id}: {e}")
            return {"status": "error", "message": f"Failed to attach photo: {e}"}

    def get_pictures(self, baby_id, limit=10, picture_dir=None):
        """
        The newest pictures attached to one baby's entries, newest first.

        Each item is {"picture_id", "path", "thumbnail_path", "time", "object_type",
        "object_id", "kind", "note"}: path and thumbnail_path are absolute (None until the
        sync has downloaded the file), time is the entry's time as ISO 8601 with the
        tracker's zone, and object_type, object_id, kind and note are the entry's, as
        get_recent_records gives them. Videos are not listed.

        Args:
            limit: Most pictures to return
            picture_dir: Where the pictures are kept (default: the directory the last sync used)
        """
        db = self._open_db()
        if db is None:
            return []
        return db.get_pictures(baby_id, limit=limit, picture_dir=picture_dir)

    def get_latest_picture(self, baby_id, picture_dir=None):
        """The newest picture of one baby (see get_pictures for its keys), or None if there is none."""
        pictures = self.get_pictures(baby_id, limit=1, picture_dir=picture_dir)
        return pictures[0] if pictures else None

    def delete_record(self, object_type, object_id):
        """
        Delete one record and queue the delete for the other devices.

        Args:
            object_type: The record's type as get_recent_records gives it, e.g. "Diaper"
            object_id: The record's ID

        Returns:
            dict: {"status": "success", "object_type", "object_id", "queued"} or
                {"status": "error", "message"}
        """
        if not self.is_authenticated:
            return {"status": "error", "message": "Not authenticated"}
        record_type = records.record_type(object_type)
        if record_type is None or record_type.selection or not record_type.activity:
            return {"status": "error", "message": f"{object_type} records can't be deleted"}
        try:
            response = self.api.delete_record(object_type, object_id)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            _LOGGER.error(f"Failed to delete {object_type} {object_id}: {e}")
            return {"status": "error", "message": f"Failed to delete record: {e}"}
        return {"status": "success", "object_type": records.canonical_type(object_type),
                "object_id": object_id, "queued": response.get("queued", False)}

    def undo_last(self, baby_id, within_hours=24):
        """
        Delete the newest record of a baby (see get_recent_records), if it is no older
        than within_hours (None: any age).

        Returns:
            dict: {"status": "success", "deleted": <the get_recent_records item>, "queued"}
                or {"status": "error", "message": "Nothing to undo"}
        """
        latest = self.get_recent_records(baby_id, limit=1, within_hours=within_hours)
        if not latest:
            return {"status": "error", "message": "Nothing to undo"}
        result = self.delete_record(latest[0]["object_type"], latest[0]["object_id"])
        if result.get("status") != "success":
            return result
        return {"status": "success", "deleted": latest[0], "queued": result.get("queued", False)}

    def _local_tz(self):
        """The configured time zone, else the host's (read each time so DST is followed)."""
        return self.tz or datetime.now().astimezone().tzinfo

    def _open_db(self):
        """The local database, opened on first use; None while there is no database file yet."""
        if not self.db:
            if not (self.db_path and os.path.exists(self.db_path)):
                return None
            self.db = BabyTrackerLocalDatabase(self.db_path, tz=self.tz)
            self.api.local_db = self.db
        return self.db

    def get_next_breast(self, baby_id=None):
        """
        Which breast to offer next, by the app's rule: the side the latest
        nursing or pump session finished on tells which side is next.

        Args:
            baby_id: Only count this baby's nursing (default: every baby's,
                as the app does, since the mother is the same)

        Returns:
            dict: {"next_side": "left"|"right"|"unknown", "last_side", "last_type"
            ("nursing", "pump" or None), "last_time"}
        """
        db = self._open_db()
        if not db:
            return {"next_side": "unknown", "last_side": "unknown", "last_type": None, "last_time": None}
        return db.get_next_breast(baby_id)

    def get_next_medicine_dose(self, baby_id):
        """
        When the baby's next medicine dose is due: the earliest still to come of
        each recent medicine's last dose plus its interval.

        Returns:
            dict: {"medicine_name", "med_id", "amount", "unit", "last_given",
            "interval_minutes", "next_dose_at"} (next_dose_at is an ISO UTC
            time, None when the medicine has no interval), or None when no
            medicine has been given
        """
        db = self._open_db()
        return db.get_next_medicine_dose(baby_id) if db else None

    def get_upcoming_milestones(self, baby_id):
        """Milestones the baby hasn't logged yet, by ForAge (months): [{"id", "name", "description", "for_age"}]."""
        db = self._open_db()
        return db.get_upcoming_milestones(baby_id) if db else []

    def get_upcoming_vaccines(self, baby_id):
        """Vaccines the baby hasn't had yet, by ForAge (months): [{"id", "name", "description", "for_age"}]."""
        db = self._open_db()
        return db.get_upcoming_vaccines(baby_id) if db else []

    def get_pumped_milk_inventory(self):
        """
        Milk in store for the whole account: all pumped (with inventory
        adjustments) minus all pumped feeds.

        Returns:
            dict: {"ml", "pumped_ml", "fed_ml"}
        """
        db = self._open_db()
        return db.get_pumped_milk_inventory() if db else {"ml": 0.0, "pumped_ml": 0.0, "fed_ml": 0.0}

    def get_events_between(self, baby_id, start, end):
        """
        What happened for a baby between two times: feeds, sleeps, baths,
        doctor visits and medicines, for the calendar.

        Args:
            baby_id: Baby ID
            start, end: Aware datetimes (end is excluded)

        Returns:
            list: Oldest first, each {"start", "end" (aware datetimes in the
            configured zone), "summary", "kind" ("feeding", "sleep", "bath",
            "doctor" or "medicine"), "description"}. A sleep lasts as long as
            its duration; everything else is 15 minutes.
        """
        db = self._open_db()
        if not db:
            return []
        tz = self._local_tz()
        return [
            {**event,
             "start": datetime.fromtimestamp(event["start"], tz),
             "end": datetime.fromtimestamp(event["end"], tz)}
            for event in db.get_events_between(baby_id, start.timestamp(), end.timestamp())
        ]

    def get_insights(self, baby_id=None, now=None):
        """
        Derived insights for one baby: age, next feed, next sleep, 24-hour intake, diaper
        adequacy, growth percentiles and weight velocity (see insights.py).

        Args:
            baby_id: Baby ID (defaults to the first baby)
            now: Optional aware datetime to compute for (defaults to now)

        Returns:
            dict: {"baby_id", "name", "generated_at", "age", "next_feed",
            "next_sleep" (see insights.SleepPrediction), "intake", "diapers", "growth", "weight_velocity"}; each part is a
            plain dict, or None when the data it needs is missing. Empty when
            the baby isn't found.
        """
        if not self._open_db():
            return {}

        if baby_id:
            baby = next((b for b in self.db.get_all_babies() if b.object_id == baby_id), None)
        else:
            baby = self.db.get_baby_info()
        if baby is None:
            return {}
        baby_id = baby.object_id

        tz = self._local_tz()
        now = now.astimezone(tz) if now else datetime.now(tz)
        stamp = now.timestamp()

        def at(seconds):
            return datetime.fromtimestamp(seconds, tz)

        age = insights.age_info(baby.dob, baby.due_day, now)
        growth_rows = self.db.get_insight_growth(baby_id)

        def age_at(moment):
            return insights.age_info(baby.dob, baby.due_day, moment)

        # Corrected age drives feeding and growth expectations; the day of
        # life for diapers is the chronological one.
        # (None without a date of birth: the age-based answers are then "unknown", not a newborn's)
        corrected_days = max(0, age.corrected_days) if age else None
        chronological_days = age.chronological_days if age else None

        latest_weight = next((r for r in reversed(growth_rows) if r["weight_kg"]), None)
        weight_kg = latest_weight["weight_kg"] if latest_weight else None
        birth_weight_kg = None
        if age and growth_rows:
            first = next((r for r in growth_rows if r["weight_kg"]), None)
            born = insights.parse_api_date(baby.dob)
            if first and born and at(first["time"]) - born <= timedelta(days=self._BIRTH_WEIGHT_DAYS):
                birth_weight_kg = first["weight_kg"]

        feeds = [
            insights.Feed(
                start=at(row["time"]),
                # Nursing durations are minutes (Android: time + duration * 60000 ms)
                end=at(row["time"] + row["duration"] * 60) if row["duration"] else None,
                amount_ml=row["amount_ml"],
                kind=row["kind"],
            )
            for row in self.db.get_insight_feeds(baby_id, stamp - self._INSIGHT_FEED_DAYS * 86400)
        ]
        sleeps = [
            insights.Sleep(
                start=at(row["time"]),
                end=None if row["in_progress"] else at(row["time"] + row["duration"] * 60),
            )
            for row in self.db.get_insight_sleeps(baby_id, stamp - self._INSIGHT_FEED_DAYS * 86400, stamp)
        ]
        day_ago = now - timedelta(hours=24)

        next_feed = insights.predict_next_feed(
            feeds, now, corrected_days, weight_kg=weight_kg, birth_weight_kg=birth_weight_kg)
        intake = insights.intake_assessment(
            [f for f in feeds if f.start >= day_ago], weight_kg, corrected_days, None)

        diapers = None
        if age:
            counts = self.db.get_insight_diaper_counts(baby_id, day_ago.timestamp())
            diapers = insights.diaper_adequacy(counts["wet"], counts["dirty"], chronological_days)

        growth = None
        velocity = None
        if age:
            growth = {}
            for kind, column in (("weight", "weight_kg"), ("length", "length_cm"), ("head", "head_cm")):
                row = next((r for r in reversed(growth_rows) if r[column]), None)
                if row is None:
                    continue
                measured = at(row["time"])
                months = age_at(measured).corrected_months
                result = insights.growth_percentile(baby.gender, months, row[column], kind)
                if result is not None:
                    growth[kind] = {**insights.to_dict(result), "measured_at": measured.isoformat()}
            weights = [(at(r["time"]), r["weight_kg"]) for r in growth_rows if r["weight_kg"]]
            if weights:
                velocity = insights.weight_velocity(weights, max(0, age_at(weights[-1][0]).corrected_days))

        return {
            "baby_id": baby_id,
            "name": baby.name,
            "generated_at": now.isoformat(),
            "age": insights.to_dict(age) if age else None,
            "next_feed": insights.to_dict(next_feed),
            "next_sleep": insights.to_dict(insights.predict_next_sleep(sleeps, now, corrected_days)),
            "intake": insights.to_dict(intake),
            "diapers": insights.to_dict(diapers) if diapers else None,
            "growth": growth or None,
            "weight_velocity": insights.to_dict(velocity) if velocity else None,
        }

# A refresh (sync) and a service call (write) can run in different executor threads at
# once. Take the tracker's lock around everything that syncs or writes, so their
# multi-step database and queue work never interleaves. Reads need no lock (WAL).
def _serialized(method):
    @functools.wraps(method)
    def locked(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return locked


for _name, _method in list(vars(BabyTracker).items()):
    if callable(_method) and (_name.startswith(("add_", "log_", "delete_", "undo_", "attach_")) or _name in ("authenticate", "sync", "force_resync")):
        setattr(BabyTracker, _name, _serialized(_method))
