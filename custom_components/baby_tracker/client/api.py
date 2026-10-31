"""Baby Tracker API client."""

import requests
import json
import base64
import uuid
import os
import logging
import time as _time
from urllib.parse import quote
from datetime import datetime, timezone, tzinfo

from . import dbconn as sqlite3  # sqlite3 with a busy timeout and WAL
from .dbconn import remove_sidecar_files
from .transaction import TransactionHandler

_LOGGER = logging.getLogger(__name__)


def _get_local_timezone_offset_seconds(tz_name=None):
    """
    Get the standard (non-DST) UTC offset in seconds.
    Matches the Android app's TimeZone.getDefault().getRawOffset() / 1000.

    Args:
        tz_name: IANA zone name (e.g. Home Assistant's configured time zone) or
            a tzinfo. Falls back to the host's zone when not given.

    Returns:
        int: Timezone offset in seconds (e.g., -21600 for CST, -18000 for EST)
    """
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            zone = tz_name if isinstance(tz_name, tzinfo) else ZoneInfo(tz_name)
            now = datetime.now(zone)
            return int((now.utcoffset() - now.dst()).total_seconds())
        except Exception as e:
            _LOGGER.warning(f"Unknown time zone {tz_name!r}, using host zone: {e}")
    # time.timezone is the standard offset in seconds WEST of UTC; Java's
    # getRawOffset is east-positive and never includes DST
    return -_time.timezone


def _now_str():
    """Current UTC time in the API's date format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")

# API endpoints
BASE_URL = "https://prodapp.babytrackers.com"
REQUEST_TIMEOUT = 30  # seconds
PAGE_SIZE = 500  # the server returns at most this many transactions per request
MAX_MERGE_ATTEMPTS = 3  # syncs to retry a transaction that fails to apply before skipping it
SEED_DATABASE_NAME = "EasyLog.db"  # the database inside the group seed zip
MAX_PICTURE_ATTEMPTS = 10  # failed downloads of one picture file before it is dropped
PICTURE_BOUNDARY = "__BABY_TRACKER_BOUNDARY____Photo__"
USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 13; sdk_gphone_x86_64 Build/TE1A.220922.034)"

class AuthenticationError(Exception):
    """The server rejected the email/password (or the password was changed)."""


class AccountResetError(Exception):
    """
    Login succeeded but for a different account than this database was synced
    with: the group was reset or recreated (SyncImple.checkAccountIDFromResponse).
    Not an AuthenticationError: the password is fine, but the local data belongs
    to the old group, so syncing stops until the database is force-resynced.
    """


class BabyTrackerAPI:
    """
    Python wrapper for the Baby Tracker API.
    Allows authentication, posting of feeding records, diapers, and group management.
    """
    
    def __init__(self, async_mode=False, db_path=None, time_zone=None):
        """Initialize the API client"""
        self.session = requests.Session()
        self.time_zone = time_zone
        self._in_login = False
        self.session_id = None
        self.baby_info = None
        self.devices = None
        self.async_mode = async_mode
        self.db_path = db_path
        self.local_db = None
        self.USER_AGENT=USER_AGENT
        
        # Authentication data
        self.username = None
        self.password = None
        self.account_id = None
        self.device_uuid = None
        self.is_authenticated = False
        self.last_sync_time = None
        self.last_picture_status = None  # see get_picture

        # API state
        self.transaction_handler = None
        self._merge_failures = {}  # (device, SyncID) -> failed apply attempts
    
    def login(self, email, password, device_uuid=None):
        """Authenticate with the API and get a session cookie"""
        self.username = email
        self.password = password

        if not device_uuid:
            device_uuid = str(uuid.uuid4())
        self.device_uuid = device_uuid    
        
        headers = {
            'Connection': 'close',
            'Content-Type': 'application/json',
            'charset': 'utf-8',
            'User-Agent': self.USER_AGENT
        }
        
        payload = {
            "AppInfo": {"AccountType": 0, "AppType": 0},
            "Device": {
                "DeviceName": "Google sdk_gphone_x86_64",
                "DeviceOSInfo": "sdk_gphone_x86_64 OS 33",
                "DeviceUUID": device_uuid
            },
            "EmailAddress": email,
            "Password": password
        }
        
        response = self.session.post(
            f"{BASE_URL}/session",
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        # As SyncImple.login: 400/401 are bad credentials, 307 means the
        # password was changed on another device
        if response.status_code in (400, 401, 307):
            raise AuthenticationError(f"Login rejected ({response.status_code})")
        if response.status_code not in [200, 201]:
            raise Exception(f"Login failed with status code {response.status_code}: {response.text}")
        
        # Extract session ID from cookies
        if 'PHPSESSID' in self.session.cookies:
            self.session_id = self.session.cookies['PHPSESSID']
            # Get account ID from the response
            try:
                account_data = response.json()
            except ValueError:
                account_data = None
            account_id = account_data.get("AccountID") if isinstance(account_data, dict) else None
            if account_id is None:
                # The session is good, so carry on; we just can't tell whether the group was reset
                _LOGGER.warning("Could not extract account ID from login response")
            self._check_account(account_id)
            self.account_id = account_id
            _LOGGER.info(f"Logged in successfully with account ID: {self.account_id}")
            self.is_authenticated = True

            # Initialize transaction handler if we have a local database
            if self.local_db and not self.transaction_handler:
                self.transaction_handler = self._new_handler()
                _LOGGER.info("Initialized transaction handler")

            # Never adopt another device's UUID: posting under it would advance
            # that device's SyncID and make every client skip its records.
            self._in_login = True
            try:
                self.get_devices()
            finally:
                self._in_login = False
            if not any(d["DeviceUUID"] == self.device_uuid for d in self.devices or []):
                _LOGGER.debug(f"Device {self.device_uuid} not yet listed by server")

            return True
        else:
            raise Exception("No session ID found in response cookies")

    def _check_account(self, account_id):
        """
        Every login must return the account this database was synced with
        (SyncImple.checkAccountIDFromResponse). A different one means the group
        was reset, and our local data and sync progress belong to the old group.
        The first login on a database records the account.
        """
        if not account_id or not self.local_db:
            return
        stored = self.local_db.get_account_id()
        if stored is None:
            if os.path.exists(self.local_db.db_path):
                self.local_db.set_account_id(account_id)
        elif stored != str(account_id):
            raise AccountResetError(
                f"This account was reset or recreated (account {stored} is now {account_id}); "
                "the local data belongs to the old group. Force a resync to join the new one.")

    def _new_handler(self):
        handler = TransactionHandler(self.local_db, enqueue=self._enqueue)
        return handler

    def _enqueue(self, op_code, record):
        """Queue a record for upload under the next SyncID (never below the server's count for us)."""
        transaction_b64 = base64.b64encode(json.dumps(record).encode('utf-8')).decode('utf-8')
        server_last = next((d.get("LastSyncID", 0) for d in self.devices or []
                            if d["DeviceUUID"] == self.device_uuid), 0)
        return self.local_db.enqueue_transaction(op_code, transaction_b64, min_sync_id=server_last)

    def _request(self, method, path, **kwargs):
        """Send a request, logging in again once if the session has expired."""
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        response = self.session.request(method, f"{BASE_URL}{path}", **kwargs)
        if response.status_code == 401 and self.username and self.password and not self._in_login:
            _LOGGER.info("Session expired, logging in again")
            self.session.cookies.clear()
            self.login(self.username, self.password, self.device_uuid)
            response = self.session.request(method, f"{BASE_URL}{path}", **kwargs)
        return response

    def get_devices(self):
        """Get the server's device list: [{DeviceUUID, LastSyncID, ...}]"""
        if not self.session_id:
            raise Exception("Not logged in")

        response = self._request("GET", "/account/device")

        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to get devices: {response.status_code}")

        self.devices = response.json()
        return self.devices
    
    
    def download_seed_data(self):
        """
        Download and extract the database seed file directly to the app's root directory,
        but only if the database file does not already exist.
        
        Returns:
            dict: A dictionary containing baby information and database file path
        """
        import tempfile
        import zipfile
        import shutil
        import sqlite3
        
        # First, check if the database file already exists
        if os.path.exists(self.db_path):
            _LOGGER.info(f"Existing database found at {self.db_path}. Skipping seed download.")
            
            # Try to read baby info from the existing database
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                
                # Get the baby record - using query based on the table structure
                cursor.execute("SELECT ID, Name, DOB, DueDay, Gender, Picture FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                
                if baby_row:
                    # Create a properly structured baby_info dict
                    self.baby_info = {
                        "objectID": baby_row[0],
                        "name": baby_row[1],
                        "dob": self._format_timestamp(baby_row[2]) if baby_row[2] else "",
                        "dueDay": self._format_timestamp(baby_row[3]) if baby_row[3] else "",
                        "gender": bool(baby_row[4]) if baby_row[4] is not None else False,
                        "pictureName": baby_row[5] if baby_row[5] else "",
                        "newFlage": False,
                        "timestamp": "1970-01-01 00:00:00 +0000",
                        "BCObjectType": "Baby"
                    }
                    _LOGGER.info(f"Found baby info from existing database: {self.baby_info['name']}")
                else:
                    _LOGGER.warning("No baby found in existing database")
                
                conn.close()
                
                return {
                    "baby_info": self.baby_info,
                    "db_file_path": self.db_path
                }
            except Exception as e:
                _LOGGER.error(f"Error reading existing database: {e}")
                # Fallback to getting baby info from devices if database read fails
                return {
                    "baby_info": self.get_baby_info_from_devices(),
                    "db_file_path": self.db_path
                }
        
        # If database doesn't exist, proceed with downloading seed data
        if not self.session_id:
            raise Exception("Not logged in")
        
        response = self._request("GET", "/account/seed")
        
        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to get seed data: {response.status_code}")
        
        # If we get an empty response, try an alternative approach to get baby info
        if not response.content:
            # Try to get baby info from devices if seed doesn't work
            return {
                "baby_info": self.get_baby_info_from_devices(),
                "db_file_path": None
            }
        
        # Path for the extracted database in the root directory
        db_file_path = self.db_path
        
        try:
            # Write the zip content to a temporary file
            with tempfile.NamedTemporaryFile(delete=False) as temp_zip:
                temp_zip.write(response.content)
                temp_zip_path = temp_zip.name
            
            # Extract to a temporary directory to locate the DB file
            with tempfile.TemporaryDirectory() as temp_dir:
                with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # The app looks for EasyLog.db (URLUtility.iOSDatabaseName); any other
                # .db is only a fallback
                db_source_path = None
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if file == SEED_DATABASE_NAME:
                            db_source_path = os.path.join(root, file)
                            break
                        if file.endswith(".db") and db_source_path is None:
                            db_source_path = os.path.join(root, file)
                    if db_source_path and os.path.basename(db_source_path) == SEED_DATABASE_NAME:
                        break

                if not db_source_path:
                    raise Exception("Database file not found in seed data")
                
                # Copy the database file to the root directory
                remove_sidecar_files(db_file_path)
                shutil.copy2(db_source_path, db_file_path)
                _LOGGER.info(f"Extracted database to: {db_file_path}")
                
                # Read the database to extract baby information
                conn = sqlite3.connect(db_file_path)
                cursor = conn.cursor()
                
                # Get the baby record - using query based on the table structure
                cursor.execute("SELECT ID, Name, DOB, DueDay, Gender, Picture FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                
                if baby_row:
                    # Create a properly structured baby_info dict
                    self.baby_info = {
                        "objectID": baby_row[0],
                        "name": baby_row[1],
                        "dob": self._format_timestamp(baby_row[2]) if baby_row[2] else "",
                        "dueDay": self._format_timestamp(baby_row[3]) if baby_row[3] else "",
                        "gender": bool(baby_row[4]) if baby_row[4] is not None else False,
                        "pictureName": baby_row[5] if baby_row[5] else "",
                        "newFlage": False,
                        "timestamp": "1970-01-01 00:00:00 +0000",
                        "BCObjectType": "Baby"
                    }
                    _LOGGER.info(f"Found baby info: {self.baby_info['name']}")
                else:
                    _LOGGER.warning("No baby found in database")
                
                conn.close()
            
            # Clean up temporary zip file
            os.unlink(temp_zip_path)
            
        except Exception as e:
            _LOGGER.error(f"Error processing seed data: {e}")
            # If there's an error, return baby info from devices as a fallback
            return {
                "baby_info": self.get_baby_info_from_devices(),
                "db_file_path": None
            }
        
        # Return the database file path along with baby info
        return {
            "baby_info": self.baby_info,
            "db_file_path": db_file_path
        }
    
    def _format_timestamp(self, timestamp):
        """Format a timestamp to the API's expected format"""
        if not timestamp:
            return ""
        try:
            # Convert timestamp to datetime and format
            dt = datetime.fromtimestamp(float(timestamp), timezone.utc)
            return dt.strftime("%Y-%m-%d %H:%M:%S +0000")
        except Exception as e:
            _LOGGER.error(f"Error formatting timestamp: {e}")
            return ""
        
    def _normalize_baby_info(self, baby_info):
        """Normalize baby info to ensure correct timezone format"""
        if not baby_info:
            return baby_info

        # Fix timezone format: "UTC" -> "+0000"
        if "dob" in baby_info and baby_info["dob"]:
            baby_info["dob"] = baby_info["dob"].replace(" UTC", " +0000")
        if "dueDay" in baby_info and baby_info["dueDay"]:
            baby_info["dueDay"] = baby_info["dueDay"].replace(" UTC", " +0000")

        # Ensure BCObjectType is present
        if "BCObjectType" not in baby_info:
            baby_info["BCObjectType"] = "Baby"

        return baby_info

    def get_baby_info_from_devices(self):
        """Alternate method to get baby info if seed download fails"""
        # If we can't get the baby info from the seed, let's try from transactions
        devices = self.get_devices()

        # Try to get a transaction to extract baby info
        for device in devices:
            try:
                # Try to get the last transaction from this device
                device_uuid = device["DeviceUUID"]
                last_sync_id = device["LastSyncID"]
                # Start with the most recent transaction and work backward if needed
                start_id = max(0, last_sync_id - 1)
                response = self._request("GET", f"/account/transaction/{device_uuid}/{start_id}")

                if response.status_code in [200, 201] and response.content:
                    transactions = response.json()

                    # Look through transactions to find baby info
                    for transaction in transactions:
                        if "Transaction" in transaction:
                            # Decode the base64 transaction
                            try:
                                transaction_data = base64.b64decode(transaction["Transaction"])
                                transaction_json = json.loads(transaction_data.decode('utf-8'))

                                # If this transaction has baby info, use it
                                if "baby" in transaction_json:
                                    self.baby_info = self._normalize_baby_info(transaction_json["baby"])
                                    _LOGGER.info(f"Loaded baby info from transaction: {self.baby_info.get('name')}")
                                    return self.baby_info
                            except Exception as e:
                                _LOGGER.error(f"Error parsing transaction: {e}")
            except Exception as e:
                _LOGGER.error(f"Error getting transactions for device {device['DeviceUUID']}: {e}")
        
        # Never invent a baby: records posted against a made-up ID would be
        # orphaned on every other client.
        if not self.baby_info:
            _LOGGER.warning("No baby found on the server")

        return self.baby_info
    
    def update_device_sync_info(self, device_uuid, last_sync_id):
        """Record how far we have merged another device's transactions"""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS DeviceSyncInfo (
                    device_uuid TEXT PRIMARY KEY,
                    last_sync_id INTEGER,
                    device_name TEXT,
                    device_os_info TEXT
                )
            ''')
            cursor.execute('''
                INSERT OR REPLACE INTO DeviceSyncInfo
                (device_uuid, last_sync_id) VALUES (?, ?)
            ''', (device_uuid, last_sync_id))
            conn.commit()
        finally:
            conn.close()
        _LOGGER.debug(f"Merged device {device_uuid} up to sync ID {last_sync_id}")

    def initialize_database(self, db_path=None):
        """Initialize or open the local database for transaction storage"""
        db_path = db_path or self.db_path
        if not db_path:
            _LOGGER.error("No database path provided")
            return False
            
        _LOGGER.info(f"Initializing database at {db_path}")
            
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            
            # Create database connection
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Create tables for tracking sync state
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS DeviceSyncInfo (
                    device_uuid TEXT PRIMARY KEY,
                    last_sync_id INTEGER,
                    device_name TEXT,
                    device_os_info TEXT
                )
            ''')
            
            # Create basic tables if they don't exist yet
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS Baby (
                    ID TEXT PRIMARY KEY,
                    Name TEXT,
                    DOB REAL,
                    DueDay REAL,
                    Gender INTEGER,
                    Picture TEXT,
                    Timestamp REAL
                )
            ''')
            
            conn.commit()
            conn.close()
            
            _LOGGER.info(f"Database initialized at {db_path}")
            return True
        except Exception as e:
            _LOGGER.error(f"Error initializing database: {e}")
            return False
            
    def get_local_device_sync_info(self):
        """Get the locally stored device sync information"""
        import sqlite3
        
        if not os.path.exists(self.db_path):
            return {}
            
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Check if table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='DeviceSyncInfo'")
        if not cursor.fetchone():
            conn.close()
            return {}
        
        # Get sync info for all devices
        cursor.execute("SELECT device_uuid, last_sync_id, device_name, device_os_info FROM DeviceSyncInfo")
        
        device_sync_info = {}
        for row in cursor.fetchall():
            device_uuid, last_sync_id, device_name, device_os_info = row
            device_sync_info[device_uuid] = {
                "device_uuid": device_uuid,
                "last_sync_id": last_sync_id,
                "device_name": device_name,
                "device_os_info": device_os_info
            }
        
        conn.close()
        return device_sync_info
    
    def join_group(self, email, password, device_uuid=None):
        """
        Join an existing Baby Tracker group

        Args:
            email: Email address for the group
            password: Password for the group
            device_uuid: Optional device UUID to use

        Returns:
            dict: Result of the operation with status and message
        """
        _LOGGER.info("Starting join group process")

        try:
            # Step 1: Login to the account
            _LOGGER.info(f"Logging in as {email}")
            if device_uuid is None:
                device_uuid = str(uuid.uuid4())

            login_success = self.login(email, password, device_uuid)
            if not login_success:
                return {"status": "error", "message": "Login failed"}

            # Step 2: Download the seed database FIRST (before initialize_database)
            # This ensures we get the full database with Baby data from the server
            _LOGGER.info("Downloading seed database")
            seed_result = self.download_seed_data()
            db_file_path = seed_result.get("db_file_path")

            # Step 3: Initialize the database tables only if seed download didn't create the file
            # or if we need to ensure required tables exist
            if db_file_path and os.path.exists(db_file_path):
                _LOGGER.info(f"Seed database downloaded to {db_file_path}")
                # Initialize database to ensure all required tables exist (DeviceSyncInfo, etc.)
                self.initialize_database(db_file_path)
            else:
                _LOGGER.info(f"No seed database, initializing new database at {self.db_path}")
                self.initialize_database(self.db_path)
                db_file_path = self.db_path

            # Initialize the database wrapper
            if not self.local_db:
                from .database import BabyTrackerLocalDatabase
                self.local_db = BabyTrackerLocalDatabase(db_file_path or self.db_path)
                _LOGGER.info(f"Initialized database: {self.local_db}")

            # The seed is another device's database: drop its upload queue so
            # its pending work is never sent as ours
            self.local_db.clear_sync_state()
            # This database now belongs to the account we just logged in to
            if self.account_id:
                self.local_db.set_account_id(self.account_id)

            baby_info = seed_result.get("baby_info")
            if not baby_info:
                _LOGGER.warning("No baby information found in seed data")

            self.baby_info = baby_info

            # Initialize transaction handler
            if self.local_db and not self.transaction_handler:
                self.transaction_handler = self._new_handler()
                _LOGGER.info("Initialized transaction handler")

            # Step 4: Sync transactions. While joining, merges don't queue
            # conflict/relive/delete echoes for the other devices (isInJoinGroupProcess).
            _LOGGER.info("Syncing transactions")
            self.transaction_handler.joining = True
            try:
                transactions = self.sync_transactions()
                transaction_count = len(transactions) if transactions else 0
                _LOGGER.info(f"Synced {transaction_count} transactions")
            except Exception as sync_error:
                _LOGGER.warning(f"Sync error (non-fatal): {sync_error}")
                transaction_count = 0
            finally:
                self.transaction_handler.joining = False
            
            return {
                "status": "success",
                "message": f"Successfully joined group and synced {transaction_count} transactions",
                "baby_info": baby_info
            }
            
        except (AuthenticationError, AccountResetError):
            raise
        except Exception as e:
            _LOGGER.error(f"Error joining group: {e}")
            return {"status": "error", "message": f"Failed to join group: {str(e)}"}
    
    def sync_transactions(self):
        """
        Download and merge other devices' transactions, as the Android app's
        checkNewTransaction does:

        - unlike the app, our own device is included: the app gets a new device
          ID whenever its database is rebuilt, but ours outlives the database
          (force resync, upgrades), so our own records may need re-downloading.
          Ones already present merge as IGNORED (same timestamp);
        - each device is fetched from the last merged SyncID, page by page,
          while a page holds PAGE_SIZE or more items;
        - items at or below the last merged SyncID are skipped;
        - progress only advances past items that were applied (or deliberately
          ignored/rejected). A failing item stops that device so it is retried
          next sync; after MAX_MERGE_ATTEMPTS it is skipped and logged.

        Returns:
            List of applied transactions
        """
        if not self.session_id:
            raise Exception("Not logged in")

        devices = self.get_devices()
        local_sync_info = self.get_local_device_sync_info()
        applied = []

        for device in devices:
            device_uuid = device["DeviceUUID"]
            server_last = device.get("LastSyncID", 0)
            merged = local_sync_info.get(device_uuid, {}).get("last_sync_id", 0) or 0
            if merged >= server_last:
                continue

            page_size = PAGE_SIZE
            while page_size >= PAGE_SIZE:
                response = self._request("GET", f"/account/transaction/{device_uuid}/{merged}")
                if response.status_code not in [200, 201]:
                    raise Exception(f"Failed to get transactions from {device_uuid}: {response.status_code}")

                page = response.json() or []
                page_size = len(page)
                start = merged
                blocked = False
                for item in page:
                    sync_id = int(item.get("SyncID", 0))
                    if sync_id <= merged:
                        continue
                    if self.transaction_handler.process_transaction(
                            item, own_device=device_uuid == self.device_uuid):
                        applied.append(item)
                        merged = sync_id
                        self._merge_failures.pop((device_uuid, sync_id), None)
                        continue

                    key = (device_uuid, sync_id)
                    self._merge_failures[key] = self._merge_failures.get(key, 0) + 1
                    detail = self._describe(item)
                    if self._merge_failures[key] < MAX_MERGE_ATTEMPTS:
                        _LOGGER.warning(
                            f"Could not apply transaction {sync_id} ({detail}) from device {device_uuid}; "
                            f"will retry (attempt {self._merge_failures[key]}/{MAX_MERGE_ATTEMPTS})"
                        )
                        blocked = True
                        break
                    _LOGGER.error(
                        f"Skipping transaction {sync_id} ({detail}) from device {device_uuid} "
                        f"after {MAX_MERGE_ATTEMPTS} failed attempts"
                    )
                    self._merge_failures.pop(key, None)
                    merged = sync_id

                if merged > start:
                    self.update_device_sync_info(device_uuid, merged)
                if blocked:
                    break

        if applied:
            _LOGGER.info(f"Synchronized {len(applied)} transactions")
            self.last_sync_time = datetime.now()
        return applied
    

    def _post_record(self, record, op_code=0):
        """
        Save a record locally, queue it for upload, then try to upload.

        As in the Android app, the local save is what makes the record "logged":
        if the server can't be reached it stays queued and is sent on the next sync.

        Returns:
            dict: {"status": "success", "objectID": <id>, "queued": <still waiting to upload>}
        """
        if not self.is_authenticated:
            raise Exception("Not authenticated")
        if not self.local_db or not self.transaction_handler:
            raise Exception("Local database not available")

        transaction_b64 = base64.b64encode(json.dumps(record).encode('utf-8')).decode('utf-8')
        if not self.transaction_handler.process_transaction(
                {"SyncID": 0, "OPCode": op_code, "Transaction": transaction_b64}, echo=False):
            raise Exception(f"Could not save {record.get('BCObjectType')} locally")

        self._enqueue(op_code, record)

        queued = False
        try:
            self.upload_pending()
        except Exception as e:
            queued = True
            _LOGGER.warning(f"Saved {record.get('BCObjectType')} locally; upload will be retried: {e}")

        return {"status": "success", "objectID": record["objectID"], "queued": queued}

    def _baby_ref(self, baby_id):
        """
        Build the nested baby object for a record from the local database.

        Raises ValueError if the baby is unknown, rather than inventing one.
        """
        if not baby_id:
            raise ValueError("A baby must be specified")
        if not self.local_db:
            raise ValueError("Local database not available")
        for baby in self.local_db.get_all_babies():
            if baby.object_id == baby_id:
                return self._normalize_baby_info({
                    "objectID": baby.object_id,
                    "name": baby.name,
                    "dob": baby.dob or "",
                    "dueDay": baby.due_day or "",
                    "gender": baby.gender,
                    "pictureName": baby.picture_name or "",
                    "timestamp": baby.timestamp,
                    "BCObjectType": "Baby"
                })
        raise ValueError(f"Baby {baby_id} not found in local database")

    def _tz_offset(self):
        return _get_local_timezone_offset_seconds(self.time_zone)

    def post_diaper(self, baby_id, time_str=None, status=0, amount=2, pee_color=5, poo_color=5, texture=5, note=""):
        """
        Post a diaper change record

        Args:
            baby_id: ID of the baby the record belongs to
            time_str: Time of the diaper change in format 'YYYY-MM-DD HH:MM:SS +0000'
            status: DiaperStatus (0=wet, 1=poopy, 2=mixed). Dry is wet with amount 0.
            amount: DiaperAmount (0=none, 1=light, 2=normal, 3=heavy, 4=overflow, 5=not set)
            pee_color: Color code for pee (5=not set)
            poo_color: Color code for poo (5=not set)
            texture: Texture code (5=not set)
            note: Optional note text
        """
        diaper_data = {
            "BCObjectType": "Diaper",
            "pooColor": poo_color,
            "peeColor": pee_color,
            "note": note,
            "time": time_str or _now_str(),
            "texture": texture,
            "amount": amount,
            "baby": self._baby_ref(baby_id),
            "flag": 0,
            "timezone": self._tz_offset(),
            "pictureNote": [],
            "status": status,
            "pictureLoaded": "true",
            "newFlage": "true",
            "objectID": str(uuid.uuid4()),
            "timestamp": _now_str()
        }
        return self._post_record(diaper_data)

    def _describe(self, item):
        """Short description of a raw transaction for logs."""
        try:
            decoded = json.loads(base64.b64decode(item.get("Transaction", "")).decode("utf-8"))
            return f"op={item.get('OPCode')} type={decoded.get('BCObjectType', '?')} id={decoded.get('objectID', '?')}"
        except Exception:
            return f"op={item.get('OPCode')} undecodable"

    def _note_own_upload(self, sync_id):
        """
        Step our own device's merge progress past a transaction the server just accepted.

        Our own device is downloaded like any other (see sync_transactions), and its
        progress only moves when it downloads. So without this, every upload is fetched
        back on the next sync and merged a second time - which would put back a record
        another device has deleted since (the insert is older than the delete, but the
        delete left nothing to compare it with). The SyncID is ours to choose and the POST
        answers with just a status, so we know exactly what the server now holds for us:
        if we had already merged everything it held before, we have merged this too.
        """
        own = next((d for d in self.devices or [] if d.get("DeviceUUID") == self.device_uuid), None)
        server_last = (own or {}).get("LastSyncID", 0) or 0
        try:
            merged = self.get_local_device_sync_info().get(self.device_uuid, {}).get("last_sync_id") or 0
            if merged >= server_last and sync_id > merged:
                self.update_device_sync_info(self.device_uuid, sync_id)
        except Exception as e:
            # Worst case the upload is merged again by the next sync, as before
            _LOGGER.debug(f"Could not record own upload {sync_id} as merged: {e}")
        if own is not None:
            own["LastSyncID"] = max(server_last, sync_id)

    def upload_pending(self):
        """
        Upload queued transactions in order (Android startUploadTransactionImpl).
        A row is removed only once the server accepts it; the first failure
        stops the run so later rows keep their order.

        Returns:
            int: number of transactions uploaded
        """
        if not self.local_db:
            return 0
        uploaded = 0
        for sync_id, op_code, transaction_b64 in self.local_db.get_pending_transactions():
            payload = {
                # The server has always been sent OPCode as a string here
                "OPCode": str(op_code),
                "SyncID": sync_id,
                "Transaction": transaction_b64
            }
            response = self._request(
                "POST",
                "/account/transaction",
                headers={'Content-Type': 'application/json'},
                json=payload
            )
            if response.status_code not in [200, 201]:
                raise Exception(f"Upload of sync ID {sync_id} failed: {response.status_code} - {response.text[:200]}")
            self.local_db.delete_pending_transaction(sync_id)
            self._note_own_upload(sync_id)
            uploaded += 1
        if uploaded:
            _LOGGER.info(f"Uploaded {uploaded} transaction(s)")
        return uploaded

    def download_pending_pictures(self, dest_dir):
        """
        Download the picture files merged activities are waiting for (the
        PhotoDownloadList; Android downloadPhotoImpl) into dest_dir.

        Each queued file gets one attempt per call. A file the server doesn't
        give us counts a failed attempt, and is dropped from the queue after
        MAX_PICTURE_ATTEMPTS of them. Being unable to reach the server counts
        against nothing: the error is raised and the queue left as it is.

        Returns:
            int: number of files saved
        """
        if not self.local_db:
            return 0
        if not self.session_id:
            raise Exception("Not logged in")
        os.makedirs(dest_dir, exist_ok=True)
        self.local_db.picture_dir = dest_dir

        saved = 0
        for name, _attempts in self.local_db.get_pending_downloads(MAX_PICTURE_ATTEMPTS):
            # Names come from other devices' records and become paths here
            if not name or name != os.path.basename(name.replace("\\", "/")) or name in (".", ".."):
                _LOGGER.warning(f"Ignoring picture file with an unsafe name: {name!r}")
                self.local_db.finish_download(name)
                continue
            path = os.path.join(dest_dir, name)
            if os.path.exists(path):
                self.local_db.finish_download(name)
                continue

            response = self._request("GET", f"/account/picture/{quote(name)}")
            if response.status_code == 200:
                if response.content:
                    temp_path = path + ".part"
                    with open(temp_path, "wb") as f:
                        f.write(response.content)
                    os.replace(temp_path, path)
                    saved += 1
                self.local_db.finish_download(name)
                continue

            attempts = self.local_db.fail_download(name)
            if attempts >= MAX_PICTURE_ATTEMPTS:
                _LOGGER.error(f"Giving up on picture {name} after {attempts} failed downloads "
                              f"(last status {response.status_code})")
                self.local_db.finish_download(name)
            else:
                _LOGGER.warning(f"Could not download picture {name}: {response.status_code} "
                                f"(attempt {attempts}/{MAX_PICTURE_ATTEMPTS})")
        if saved:
            _LOGGER.info(f"Downloaded {saved} picture file(s)")
        return saved

    def upload_picture(self, path):
        """
        Upload a JPEG to the account (Android sendUploadPicture): a multipart
        POST to /account/picture with the file in the `picture` field. Records
        refer to it by file name. Returns True once the server answers 201.
        """
        if not self.session_id:
            raise Exception("Not logged in")
        with open(path, "rb") as f:
            data = f.read()
        file_name = os.path.basename(path).replace('"', "_").replace("\r", "_").replace("\n", "_")
        head = (f'\r\n--{PICTURE_BOUNDARY}\r\n'
                f'Content-Disposition: form-data; name="picture"; filename="{file_name}"\r\n'
                'Content-Type: image/jpeg\r\n\r\n').encode("utf-8")
        tail = f'\r\n--{PICTURE_BOUNDARY}--\r\n'.encode("utf-8")
        response = self._request(
            "POST", "/account/picture",
            headers={"Content-Type": f"multipart/form-data; boundary={PICTURE_BOUNDARY}"},
            data=head + data + tail,
        )
        if response.status_code != 201:
            raise Exception(f"Upload of picture {file_name} failed: {response.status_code}")
        return True

    def logout(self):
        """
        End the server session (SyncImple.sendDisconnect: DELETE /session; the
        server answers 200, or 401 if the session had already expired).
        """
        # Not _request: a logout must never log in again because the session was gone
        response = self.session.request(
            "DELETE", f"{BASE_URL}/session",
            headers={'Connection': 'close', 'User-Agent': self.USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code not in (200, 401):
            raise Exception(f"Logout failed with status code {response.status_code}")
        self.session.cookies.clear()
        self.session_id = None
        self.is_authenticated = False
        return True

    def post_pump(self, time_str=None, left_duration=0, right_duration=0, left_amount=0.0, right_amount=0.0,
                  is_english_scale=False, finish_side=0, note=""):
        """
        Post a pumping session (Android Pump: account-level, no baby).

        Args:
            left_duration / right_duration: minutes per side
            left_amount / right_amount: amount per side (oz if is_english_scale, else ml)
            finish_side: PumpFinishSide (0=none, 1=left, 2=right)
        """
        def measure(value):
            return {"englishMeasure": bool(is_english_scale), "value": float(value)}

        pump_data = {
            "BCObjectType": "Pump",
            "amount": measure(left_amount + right_amount),
            "leftAmount": measure(left_amount),
            "rightAmount": measure(right_amount),
            "leftDuration": int(left_duration),
            "rightDuration": int(right_duration),
            "finishSide": finish_side,
            "sides": 0,  # PumpSidesBoth; the app never changes it
            "note": note,
            "pictureLoaded": True,
            "pictureNote": [],
            "time": time_str or _now_str(),
            "timezone": self._tz_offset(),
            "newFlage": True,
            "objectID": str(uuid.uuid4()),
            "timestamp": _now_str()
        }
        return self._post_record(pump_data)

    def post_growth(self, baby_id, time_str=None, weight=0, length=0, head=0,
                    is_english_weight_scale=True, is_english_length_scale=True, note=""):
        """Post a growth measurement. Zero values are left out, as the app treats 0 as unset."""
        growth_data = {
            "BCObjectType": "Growth",
            "deleted": False,
            "queryIndex": 0,
            "baby": self._baby_ref(baby_id),
            "note": note,
            "pictureLoaded": True,
            "pictureNote": [],
            "time": time_str or _now_str(),
            "timezone": self._tz_offset(),
            "newFlage": True,
            "objectID": str(uuid.uuid4()),
            "timestamp": _now_str()
        }
        for key, value, english in (("weight", weight, is_english_weight_scale),
                                    ("length", length, is_english_length_scale),
                                    ("head", head, is_english_length_scale)):
            if value:
                growth_data[key] = {"englishMeasure": bool(english), "value": float(value)}
        return self._post_record(growth_data)

    def _selection(self, rows, selection_id, kind):
        for row in rows:
            if row.get("id") == selection_id:
                return {
                    "objectID": row["id"],
                    "name": row.get("name", ""),
                    "desc": row.get("description", ""),
                    "forAge": row.get("for_age", 0),
                    "newFlage": False,
                    "timestamp": "1970-01-01 00:00:00 +0000"
                }
        raise ValueError(f"{kind} {selection_id} not found in local database")

    def post_milestone(self, baby_id, milestone_selection_id, time_str=None, note=""):
        """Post a milestone for an existing MilestoneSelection."""
        milestone_type = self._selection(self.local_db.get_milestone_selections(), milestone_selection_id, "Milestone")
        milestone_type["used"] = False
        milestone_data = {
            "BCObjectType": "Milestone",
            "hasNewType": False,
            "milestoneType": milestone_type,
            "baby": self._baby_ref(baby_id),
            "note": note,
            "pictureLoaded": True,
            "pictureNote": [],
            "time": time_str or _now_str(),
            "timezone": self._tz_offset(),
            "newFlage": True,
            "objectID": str(uuid.uuid4()),
            "timestamp": _now_str()
        }
        return self._post_record(milestone_data)

    def post_vaccine(self, baby_id, vacc_id, time_str=None, note=""):
        """Post a vaccine for an existing VaccineSelection (no doctor-visit link, as in the app)."""
        vaccine_data = {
            "BCObjectType": "Vaccine",
            "vaccineType": self._selection(self.local_db.get_vaccine_selections(), vacc_id, "Vaccine"),
            "baby": self._baby_ref(baby_id),
            "note": note,
            "pictureLoaded": True,
            "pictureNote": [],
            "time": time_str or _now_str(),
            "timezone": self._tz_offset(),
            "newFlage": True,
            "objectID": str(uuid.uuid4()),
            "timestamp": _now_str()
        }
        return self._post_record(vaccine_data)

    def post_temperature(self, baby_id, time_str=None, temperature=98.6, is_fahrenheit=True, note=""):
        """
        Post a temperature record

        Args:
            baby_id: ID of the baby the record belongs to
            time_str: Time of temperature reading in format 'YYYY-MM-DD HH:MM:SS +0000'
            temperature: Temperature value
            is_fahrenheit: Whether temperature is in Fahrenheit (True) or Celsius (False)
            note: Optional note text
        """
        temperature_data = {
            "BCObjectType": "Temperature",
            "note": note,
            "time": time_str or _now_str(),
            "temperature": {
                "value": temperature,
                "englishMeasure": "true" if is_fahrenheit else "false",
                "BCObjectType": "TemperatureMeasure"
            },
            "timezone": self._tz_offset(),
            "pictureNote": [],
            "pictureLoaded": "true",
            "newFlage": "true",
            "objectID": str(uuid.uuid4()),
            "timestamp": _now_str(),
            "baby": self._baby_ref(baby_id)
        }
        return self._post_record(temperature_data)

    def post_medicine(self, baby_id, time_str=None, med_id=None, amount=0, note=""):
        """
        Post a medicine administration record

        Args:
            baby_id: ID of the baby the record belongs to
            time_str: Time of medicine administration in format 'YYYY-MM-DD HH:MM:SS +0000'
            med_id: ID of the medicine to administer
            amount: Amount of medicine administered
            note: Optional note text
        """
        if not med_id:
            raise ValueError("Medicine ID is required")

        # Get the medicine selection details for the full transaction
        med_selection = None
        if self.local_db:
            for sel in self.local_db.get_medicine_selections():
                if sel.get("id") == med_id:
                    med_selection = {
                        "objectID": med_id,
                        "name": sel.get("name", ""),
                        "amountPerTime": sel.get("amount_per_time", amount),
                        "interval": sel.get("interval", 0),
                        "unit": sel.get("unit", "ml"),
                        "prescription": bool(sel.get("is_prescription", False)),
                        "newFlage": False,
                        "timestamp": "1970-01-01 00:00:00 +0000"
                    }
                    break
        # Android's Medication only reads medicationSelection, so a record
        # without one would arrive on other clients with no medicine.
        if not med_selection:
            raise ValueError(f"Medicine {med_id} not found in local database")

        # Use "Medication" to match app format
        medicine_data = {
            "BCObjectType": "Medication",
            "time": time_str or _now_str(),
            "note": note,
            "amount": amount,
            "baby": self._baby_ref(baby_id),
            "timezone": self._tz_offset(),
            "pictureNote": [],
            "pictureLoaded": True,
            "newFlage": True,
            "objectID": str(uuid.uuid4()),
            "timestamp": _now_str(),
            "medicationSelection": med_selection
        }
        return self._post_record(medicine_data)

    def post_other_activity(self, baby_id, time_str=None, activity_name="Tummy Time", duration=0, location_id=None, note=""):
        """
        Post an other activity record

        Args:
            baby_id: ID of the baby the record belongs to
            time_str: Time of activity in format 'YYYY-MM-DD HH:MM:SS +0000'
            activity_name: Name of the activity
            duration: Duration in minutes
            location_id: Optional location ID
            note: Optional note text
        """
        # The activity's description: the account's own of that name, else a new one
        known = next((row for row in (self.local_db.get_activity_types() if self.local_db else [])
                      if (row["name"] or "").lower() == activity_name.lower()), None)
        activity_desc = {
            "desc": known["description"] or "" if known else "",
            "newFlage": "false",
            "objectID": known["id"] if known else f"EasyLogSeed{uuid.uuid4().hex[:24]}",
            "timestamp": "1970-01-01 00:00:00 +0000",
            "BCObjectType": "OtherActivityDescription",
            "name": known["name"] if known else activity_name
        }

        activity_data = {
            "BCObjectType": "OtherActivity",
            "note": note,
            "timestamp": _now_str(),
            "newFlage": "true",
            "pictureLoaded": "true",
            "time": time_str or _now_str(),
            "objectID": str(uuid.uuid4()),
            "desc": activity_desc,
            "baby": self._baby_ref(baby_id),
            "duration": duration,
            "timezone": self._tz_offset(),
            "pictureNote": []
        }

        if location_id:
            activity_data["locationID"] = location_id

        return self._post_record(activity_data)

    def post_bath(self, baby_id, time_str=None, bath_type=None, note=""):
        """
        Post a bath record

        Args:
            baby_id: ID of the baby the record belongs to
            time_str: Time of bath in format 'YYYY-MM-DD HH:MM:SS +0000'
            bath_type: Type of bath (optional) - "Bubble Bath", "Sponge Bath", "Shower", "Washed Hair"
            note: Optional note text
        """
        # Map bath type to known IDs (use Sponge Bath as default since it's a known type)
        bath_type_ids = {
            "Sponge Bath": "EasyLogSeeda1b71e20-86a3-11e2-9e96-0800200c9a66",
            "Bubble Bath": "EasyLogSeedb0bec620-86a3-11e2-9e96-0800200c9a66",
            "Shower": "EasyLogSeed1d710590-bc09-11e2-9e96-0800200c9a66",
            "Washed Hair": "EasyLogSeedc0395430-86a3-11e2-9e96-0800200c9a66",
        }

        effective_bath_type = bath_type if bath_type else "Sponge Bath"
        desc_id = bath_type_ids.get(effective_bath_type, bath_type_ids["Sponge Bath"])

        # Always create bath description (required for server sync)
        bath_desc = {
            "objectID": desc_id,
            "name": effective_bath_type,
            "desc": "",
            "newFlage": "false",
            "timestamp": "1970-01-01 00:00:00 +0000",
            "BCObjectType": "BathDesc"
        }

        # Bath objects don't have a duration field
        bath_data = {
            "BCObjectType": "Bath",
            "note": note,
            "time": time_str or _now_str(),
            "timezone": self._tz_offset(),
            "pictureNote": [],
            "pictureLoaded": "true",
            "newFlage": "true",
            "objectID": str(uuid.uuid4()),
            "timestamp": _now_str(),
            "baby": self._baby_ref(baby_id),
            "bathType": bath_desc  # Use bathType field as expected by server
        }
        return self._post_record(bath_data)

    def post_sleep(self, baby_id, time_str=None, duration=0, note=""):
        """
        Post a sleep record

        Args:
            baby_id: ID of the baby the record belongs to
            time_str: Time of sleep start in format 'YYYY-MM-DD HH:MM:SS +0000'
            duration: Duration in minutes (0 for sleep start)
            note: Optional note text
        """
        # Note: pictureLoaded and newFlage must be booleans (not strings) for the API to accept
        sleep_data = {
            "BCObjectType": "Sleep",
            "duration": duration,
            "baby": self._baby_ref(baby_id),
            "note": note,
            "pictureLoaded": True,
            "pictureNote": [],
            "time": time_str or _now_str(),
            "timezone": self._tz_offset(),
            "newFlage": True,
            "objectID": str(uuid.uuid4()),
            "timestamp": _now_str()
        }
        return self._post_record(sleep_data)

    def update_sleep(self, baby_id, object_id, time_str, duration_minutes, note=""):
        """
        Update an existing sleep record (for wake-up/end sleep).
        Uses OPCode 1 (UPDATE) to modify the existing record.

        Args:
            baby_id: ID of the baby the sleep record belongs to
            object_id: The objectID of the sleep record to update
            time_str: Original sleep start time in format 'YYYY-MM-DD HH:MM:SS +0000'
            duration_minutes: Duration in minutes
            note: Optional note text
        """
        baby = self._baby_ref(baby_id)
        # For updates, use minimal baby object (just gender, newFlage, objectID)
        minimal_baby = {
            "gender": baby.get("gender", False),
            "newFlage": False,
            "objectID": baby["objectID"]
        }

        sleep_data = {
            "BCObjectType": "Sleep",
            "duration": duration_minutes,
            "baby": minimal_baby,
            "note": note,
            "pictureLoaded": True,
            "pictureNote": [],
            "time": time_str,
            "timezone": self._tz_offset(),
            "newFlage": False,
            "objectID": object_id,
            "timestamp": _now_str()
        }
        return self._post_record(sleep_data, op_code=1)

    def post_nursing(self, baby_id, time_str=None, left_duration=0, right_duration=0, both_duration=0, finish_side=1, note=""):
        """
        Post a nursing session record

        Args:
            baby_id: ID of the baby the record belongs to
            time_str: Time of the nursing in format 'YYYY-MM-DD HH:MM:SS +0000'
            left_duration: Duration of left side nursing in minutes
            right_duration: Duration of right side nursing in minutes
            both_duration: Duration of both sides nursing simultaneously in minutes
            finish_side: Which side finished on (0=not set, 1=left, 2=right)
            note: Optional note text
        """
        nursing_data = {
            "BCObjectType": "Nursing",
            "note": note,
            "time": time_str or _now_str(),
            "rightDuration": right_duration,
            "baby": self._baby_ref(baby_id),
            "finishSide": finish_side,
            "bothDuration": both_duration,
            "leftDuration": left_duration,
            "timezone": self._tz_offset(),
            "pictureNote": [],
            "pictureLoaded": "true",
            "newFlage": "true",
            "objectID": str(uuid.uuid4()),
            "timestamp": _now_str()
        }
        return self._post_record(nursing_data)

    def _post_volume_feed(self, object_type, baby_id, time_str, amount, is_english_measure, note):
        """Post a Formula or Pumped (bottle of expressed milk) record."""
        data = {
            "amount": {
                "value": amount,
                "englishMeasure": "true" if is_english_measure else "false",
                "BCObjectType": "VolumeMeasure"
            },
            "BCObjectType": object_type,
            "note": note,
            "time": time_str or _now_str(),
            "timezone": self._tz_offset(),
            "newFlage": "true",
            "pictureLoaded": "true",
            "pictureNote": [],
            "timestamp": _now_str(),
            "baby": self._baby_ref(baby_id),
            "objectID": str(uuid.uuid4())
        }
        return self._post_record(data)

    def post_formula(self, baby_id, time_str=None, amount=0, is_english_measure=False, note=""):
        """Post a formula feeding record (amount in oz if is_english_measure, else ml)."""
        return self._post_volume_feed("Formula", baby_id, time_str, amount, is_english_measure, note)

    def post_pumped(self, baby_id, time_str=None, amount=0, is_english_measure=False, note=""):
        """Post a pumped milk feeding record (amount in oz if is_english_measure, else ml)."""
        return self._post_volume_feed("Pumped", baby_id, time_str, amount, is_english_measure, note)

    def post_other_feed(self, baby_id, feed_type_id, time_str=None, amount=0, unit="", is_english_measure=True,
                        note=""):
        """
        Post a solids/supplement feed of an existing OtherFeedSelection (a food).

        Args:
            feed_type_id: ID of the OtherFeedSelection
            amount: How much, in the given unit
            unit: The unit's name as the app shows it, e.g. "tbsp"
            is_english_measure: Whether the amount is in English units
        """
        food = next((row for row in self.local_db.get_other_feed_selections() if row["id"] == feed_type_id), None)
        if not food:
            raise ValueError(f"Food {feed_type_id} not found in local database")
        data = {
            "BCObjectType": "OtherFeed",
            "feedType": {
                "objectID": food["id"],
                "name": food["name"],
                "desc": food["description"],
                "bottle": food["is_bottle"],
                "newFlage": False,
                "timestamp": "1970-01-01 00:00:00 +0000",
            },
            "amount": {
                "value": amount,
                "englishMeasure": "true" if is_english_measure else "false",
                "BCObjectType": "VolumeMeasure"
            },
            "unit": unit or "",
            "note": note,
            "time": time_str or _now_str(),
            "timezone": self._tz_offset(),
            "newFlage": "true",
            "pictureLoaded": "true",
            "pictureNote": [],
            "timestamp": _now_str(),
            "baby": self._baby_ref(baby_id),
            "objectID": str(uuid.uuid4())
        }
        return self._post_record(data)

    def get_picture(self, picture_name):
        """
        Download a picture from the Baby Tracker server.

        Args:
            picture_name: The filename of the picture (e.g., '91B377F6-A50D-4576-B4ED-98028B5B1ABE')

        Returns:
            bytes: The raw image data, or None if the request fails
        """
        if not self.session_id:
            raise Exception("Not logged in")

        if not picture_name:
            _LOGGER.debug("No picture name provided")
            return None

        # The HTTP status of the last request (None when it never got an answer), so a caller
        # can tell "the server doesn't have it" (404) from a failure worth trying again
        self.last_picture_status = None
        try:
            url = f"{BASE_URL}/account/picture/{picture_name}"
            _LOGGER.debug(f"Fetching picture from: {url}")

            response = self._request(
                "GET",
                f"/account/picture/{picture_name}",
                headers={'User-Agent': self.USER_AGENT}
            )
            self.last_picture_status = response.status_code

            _LOGGER.debug(f"Picture response: status={response.status_code}, content-type={response.headers.get('Content-Type', 'unknown')}, content-length={len(response.content) if response.content else 0}")

            if response.status_code not in [200, 201]:
                _LOGGER.error(f"Failed to get picture: {response.status_code}, response: {response.text[:200] if response.text else 'empty'}")
                return None

            # Check content type
            content_type = response.headers.get('Content-Type', '')

            # If it's JSON, the picture might be base64 encoded
            if 'json' in content_type.lower():
                try:
                    data = response.json()
                    _LOGGER.debug(f"Picture response is JSON: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    # Check if there's a base64 image field
                    if isinstance(data, dict):
                        for key in ['image', 'picture', 'data', 'content', 'base64']:
                            if key in data:
                                import base64
                                return base64.b64decode(data[key])
                except Exception as e:
                    _LOGGER.warning(f"Failed to parse picture JSON: {e}")

            # If it's an image, return directly
            if 'image' in content_type.lower():
                _LOGGER.info(f"Successfully downloaded picture: {picture_name}")
                return response.content

            # Try treating the response as raw image data anyway
            if response.content and len(response.content) > 100:
                _LOGGER.info(f"Treating response as raw image data for: {picture_name}")
                return response.content

            _LOGGER.warning(f"Picture request returned unexpected content type: {content_type}")
            return None

        except Exception as e:
            _LOGGER.error(f"Error downloading picture {picture_name}: {e}")
            return None
