"""Baby Tracker API client."""

import requests
import json
import base64
import uuid
import os
import logging
import sqlite3
from datetime import datetime, timezone

from .transaction import TransactionHandler

_LOGGER = logging.getLogger(__name__)

# API endpoints
BASE_URL = "https://prodapp.babytrackers.com"
USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 13; sdk_gphone_x86_64 Build/TE1A.220922.034)"

class BabyTrackerAPI:
    """
    Python wrapper for the Baby Tracker API.
    Allows authentication, posting of feeding records, diapers, and group management.
    """
    
    def __init__(self, async_mode=False, db_path=None):
        """Initialize the API client"""
        self.session = requests.Session()
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
        
        # API state
        self.transaction_handler = None
        self.device_sync_info = {}  # Store sync info for each device
    
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
            json=payload
        )
        
        if response.status_code not in [200, 201]:
            raise Exception(f"Login failed with status code {response.status_code}: {response.text}")
        
        # Extract session ID from cookies
        if 'PHPSESSID' in self.session.cookies:
            self.session_id = self.session.cookies['PHPSESSID']
            # Get account ID from the response
            try:
                account_data = response.json()
                self.account_id = account_data.get("AccountID")
                _LOGGER.info(f"Logged in successfully with account ID: {self.account_id}")
                self.is_authenticated = True

                # Initialize transaction handler if we have a local database
                if self.local_db and not self.transaction_handler:
                    from .transaction import TransactionHandler
                    self.transaction_handler = TransactionHandler(self.local_db)
                    _LOGGER.info("Initialized transaction handler")

                # Get devices and use an existing device UUID if our generated one doesn't exist
                self.get_devices()
                if self.devices:
                    # Check if our device_uuid is in the list
                    device_found = any(d["DeviceUUID"] == self.device_uuid for d in self.devices)
                    if not device_found:
                        # Use the first registered device's UUID instead
                        self.device_uuid = self.devices[0]["DeviceUUID"]
                        _LOGGER.info(f"Using existing device UUID: {self.device_uuid}")
            except:
                _LOGGER.warning("Could not extract account ID from login response")

            return True
        else:
            raise Exception("No session ID found in response cookies")
    
    def get_devices(self):
        """Get information about registered devices"""
        if not self.session_id:
            raise Exception("Not logged in")
        
        response = self.session.get(f"{BASE_URL}/account/device")
        
        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to get devices: {response.status_code}")
        
        self.devices = response.json()
        
        # Update device_sync_info with latest device information
        for device in self.devices:
            device_uuid = device["DeviceUUID"]
            last_sync_id = device["LastSyncID"]
            device_name = device.get("DeviceName", "")
            device_os_info = device.get("DeviceOSInfo", "")
            
            self.device_sync_info[device_uuid] = {
                "device_uuid": device_uuid,
                "last_sync_id": last_sync_id,
                "device_name": device_name,
                "device_os_info": device_os_info
            }
            
        return self.devices
    
    def get_next_sync_id(self, device_uuid=None):
        """Get the next sync ID for the device"""
        if not self.devices:
            self.get_devices()
            
        if device_uuid:
            for device in self.devices:
                if device["DeviceUUID"] == device_uuid:
                    return device["LastSyncID"] + 1
            raise Exception(f"Device UUID {device_uuid} not found")
        else:
            # Use the highest sync ID + 1
            return max(device["LastSyncID"] for device in self.devices) + 1
    
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
        
        response = self.session.get(f"{BASE_URL}/account/seed")
        
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
                
                # Look for the database file
                db_source_path = None
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if file.endswith(".db"):
                            db_source_path = os.path.join(root, file)
                            break
                
                if not db_source_path:
                    raise Exception("Database file not found in seed data")
                
                # Copy the database file to the root directory
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
                response = self.session.get(f"{BASE_URL}/account/transaction/{device_uuid}/{start_id}")
                
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
                                    self.baby_info = transaction_json["baby"]
                                    return self.baby_info
                            except Exception as e:
                                _LOGGER.error(f"Error parsing transaction: {e}")
            except Exception as e:
                _LOGGER.error(f"Error getting transactions for device {device['DeviceUUID']}: {e}")
        
        # If we still don't have baby info, create minimal version
        if not self.baby_info:
            baby_id = str(uuid.uuid4())
            self.baby_info = {
                "name": "Baby",
                "objectID": baby_id,
                "dob": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000"),
                "dueDay": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000"),
                "gender": False,
                "newFlage": False,
                "pictureName": "",
                "timestamp": "1970-01-01 00:00:00 +0000",
                "BCObjectType": "Baby"
            }
            _LOGGER.info("Created default baby info since none could be found")
            
        return self.baby_info
    
    def update_device_sync_info(self, device_uuid, last_sync_id):
        """Update the local record of the last sync ID for a device"""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Make sure the table exists
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS DeviceSyncInfo (
                device_uuid TEXT PRIMARY KEY,
                last_sync_id INTEGER,
                device_name TEXT,
                device_os_info TEXT
            )
        ''')
        
        # Update or insert the device sync info
        cursor.execute('''
            INSERT OR REPLACE INTO DeviceSyncInfo 
            (device_uuid, last_sync_id) VALUES (?, ?)
        ''', (device_uuid, last_sync_id))
        
        conn.commit()
        conn.close()
        
        # Also update in-memory cache
        if device_uuid in self.device_sync_info:
            self.device_sync_info[device_uuid]["last_sync_id"] = last_sync_id
        else:
            self.device_sync_info[device_uuid] = {
                "device_uuid": device_uuid,
                "last_sync_id": last_sync_id,
                "device_name": "",
                "device_os_info": ""
            }

        _LOGGER.info(f"Updated last sync ID for device {device_uuid} to {last_sync_id}")

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
                
            # Step 2: Initialize the database
            _LOGGER.info(f"Initializing database at {self.db_path}")
            self.initialize_database(self.db_path)
                
            # Step 3: Download the seed database
            _LOGGER.info("Downloading seed database")
            seed_result = self.download_seed_data()
            db_file_path = seed_result.get("db_file_path")
            
            # Create a new database at the specified path if needed
            if db_file_path and os.path.exists(db_file_path):
                _LOGGER.info(f"Database already exists at {db_file_path}")
            else:
                _LOGGER.info(f"Creating new database at {self.db_path}")
                # Create empty database file
                conn = sqlite3.connect(self.db_path)
                conn.close()
                db_file_path = self.db_path
                
            # Always initialize the database
            if not self.local_db:
                from .database import BabyTrackerLocalDatabase
                self.local_db = BabyTrackerLocalDatabase(db_file_path or self.db_path)
                _LOGGER.info(f"Initialized database: {self.local_db}")
                
            baby_info = seed_result.get("baby_info")
            if not baby_info:
                _LOGGER.warning("No baby information found, creating default")
                baby_info = {
                    "name": "Baby",
                    "objectID": str(uuid.uuid4()),
                    "dob": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000"),
                    "gender": False,
                    "BCObjectType": "Baby"
                }
                
            self.baby_info = baby_info
            
            # Initialize transaction handler
            if self.local_db and not self.transaction_handler:
                self.transaction_handler = TransactionHandler(self.local_db)
                _LOGGER.info("Initialized transaction handler")
            
            # Step 4: Sync transactions
            _LOGGER.info("Syncing transactions")
            try:
                transactions = self.sync_transactions()
                transaction_count = len(transactions) if transactions else 0
                _LOGGER.info(f"Synced {transaction_count} transactions")
            except Exception as sync_error:
                _LOGGER.warning(f"Sync error (non-fatal): {sync_error}")
                transaction_count = 0
            
            return {
                "status": "success",
                "message": f"Successfully joined group and synced {transaction_count} transactions",
                "baby_info": baby_info
            }
            
        except Exception as e:
            _LOGGER.error(f"Error joining group: {e}")
            return {"status": "error", "message": f"Failed to join group: {str(e)}"}
    
    def sync_transactions(self):
        """
        Synchronize transactions with the server
        
        Returns:
            List of downloaded transactions
        """
        if not self.session_id:
            raise Exception("Not logged in")
        
        # Get all devices
        devices = self.get_devices()
        _LOGGER.info(f"Found {len(devices)} devices")
        
        # Get local device sync info
        local_sync_info = self.get_local_device_sync_info()
        
        all_transactions = []
        
        # For each device, get new transactions
        for device in devices:
            device_uuid = device["DeviceUUID"]
            server_last_sync_id = device.get("LastSyncID", 0)
            
            # Determine the last sync ID we have locally
            local_last_sync_id = 0
            if device_uuid in local_sync_info:
                local_last_sync_id = local_sync_info[device_uuid]["last_sync_id"]
            
            # If we're already up to date with this device, skip it
            if local_last_sync_id >= server_last_sync_id:
                _LOGGER.info(f"Device {device_uuid} is already up to date (Last Sync ID: {local_last_sync_id})")
                continue
                
            try:
                # Get transactions since the last known sync ID for this device
                response = self.session.get(f"{BASE_URL}/account/transaction/{device_uuid}/{local_last_sync_id}")
                
                if response.status_code in [200, 201]:
                    device_transactions = response.json()
                    num_transactions = len(device_transactions)
                    
                    if num_transactions > 0:
                        # Process the transactions
                        processed_until = local_last_sync_id
                        
                        for transaction in device_transactions:
                            # Keep track of the highest sync ID we've successfully processed
                            if "SyncID" in transaction:
                                current_sync_id = int(transaction["SyncID"])
                                
                                if self.transaction_handler and self.transaction_handler.process_transaction(transaction):
                                    all_transactions.append(transaction)
                                    processed_until = current_sync_id
                                else:
                                    # Log but continue processing
                                    _LOGGER.warning(f"Failed to process transaction {current_sync_id} for device {device_uuid}")
                        
                        # Update the local sync info with the highest successfully processed sync ID
                        if processed_until > local_last_sync_id:
                            self.update_device_sync_info(device_uuid, processed_until)
                else:
                    _LOGGER.error(f"Failed to get transactions from {device_uuid}: {response.status_code}")
            except Exception as e:
                _LOGGER.error(f"Error getting transactions from device {device_uuid}: {e}")
        
        if all_transactions:
            _LOGGER.info(f"Synchronized {len(all_transactions)} transactions successfully")
            self.last_sync_time = datetime.now()
        else:
            _LOGGER.info("No new transactions synchronized")
        
        return all_transactions
    
    def post_transaction(self, transaction_data, op_code=0):  # 0 = INSERT
        """
        Post a transaction to the server
        
        Args:
            transaction_data: JSON data for the transaction
            op_code: Operation code (default is INSERT = 0)
            
        Returns:
            Response from the server
        """
        if not self.session_id:
            raise Exception("Not logged in")
            
        # Get the next sync ID
        next_sync_id = self.get_next_sync_id(self.device_uuid)
        
        # Ensure the transaction data is a string
        if isinstance(transaction_data, dict):
            transaction_data = json.dumps(transaction_data)
            
        # Encode the transaction data as base64
        transaction_b64 = base64.b64encode(transaction_data.encode('utf-8')).decode('utf-8')
        
        # Prepare the payload
        payload = {
            "SyncID": next_sync_id,
            "OPCode": op_code,
            "Transaction": transaction_b64
        }
        
        # Post the transaction
        response = self.session.post(
            f"{BASE_URL}/account/transaction",
            headers={'Content-Type': 'application/json'},
            json=payload
        )
        
        if response.status_code not in [200, 201]:
            raise Exception(f"Failed to post transaction: {response.status_code} - {response.text}")
            
        _LOGGER.info(f"Successfully posted transaction with sync ID {next_sync_id}")
        
        # Update local sync ID
        self.update_device_sync_info(self.device_uuid, next_sync_id)
        
        return response
    
    
    def post_diaper(self, time_str=None, pee_color=0, poo_color=0, texture=0, amount=2, status=0, note=""):
        """
        Post a diaper change record
        
        Args:
            time_str: Time of the diaper change in format 'YYYY-MM-DD HH:MM:SS +0000'
            pee_color: Color code for pee (0-5)
            poo_color: Color code for poo (0-5)
            texture: Texture code (0-5)
            amount: Amount (usually 2)
            status: Status code (0=wet, 1=poopy, 2=mixed, 3=dry)
            note: Optional note text
            
        Returns:
            dict: API response
        """
        if not self.is_authenticated:
            raise Exception("Not authenticated")
            
        if not self.baby_info:
            raise Exception("Baby information not available")
            
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
            
        # Create the diaper transaction
        diaper_data = {
            "BCObjectType": "Diaper",
            "pooColor": poo_color,
            "peeColor": pee_color,
            "note": note,
            "time": time_str,
            "texture": texture,
            "amount": amount,
            "baby": self.baby_info,
            "flag": 0,
            "timezone": -21600,  # This should be dynamic based on user's timezone
            "pictureNote": [],
            "status": status,
            "pictureLoaded": "true",
            "newFlage": "true",
            "objectID": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        }
        
        try:
            response = self.post_transaction(diaper_data)
            return {"status": "success"}
        except Exception as e:
            _LOGGER.error(f"Failed to post diaper: {e}")
            return {"status": "error", "message": str(e)}
    
    def post_temperature(self, time_str=None, temperature=98.6, is_fahrenheit=True, note=""):
        """
        Post a temperature record
        
        Args:
            time_str: Time of temperature reading in format 'YYYY-MM-DD HH:MM:SS +0000'
            temperature: Temperature value
            is_fahrenheit: Whether temperature is in Fahrenheit (True) or Celsius (False)
            note: Optional note text
            
        Returns:
            dict: API response
        """
        if not self.is_authenticated:
            raise Exception("Not authenticated")
            
        if not self.baby_info:
            raise Exception("Baby information not available")
            
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
            
        # Create the temperature transaction
        temperature_data = {
            "BCObjectType": "Temperature",
            "note": note,
            "time": time_str,
            "temperature": {
                "value": temperature,
                "englishMeasure": "true" if is_fahrenheit else "false",
                "BCObjectType": "TemperatureMeasure"
            },
            "timezone": -21600,  # This should be dynamic based on user's timezone
            "pictureNote": [],
            "pictureLoaded": "true",
            "newFlage": "true",
            "objectID": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000"),
            "baby": self.baby_info
        }
        
        try:
            response = self.post_transaction(temperature_data)
            return {"status": "success"}
        except Exception as e:
            _LOGGER.error(f"Failed to post temperature: {e}")
            return {"status": "error", "message": str(e)}
    
    def post_medicine(self, time_str=None, med_id=None, amount=0, note=""):
        """
        Post a medicine administration record
        
        Args:
            time_str: Time of medicine administration in format 'YYYY-MM-DD HH:MM:SS +0000'
            med_id: ID of the medicine to administer
            amount: Amount of medicine administered
            note: Optional note text
            
        Returns:
            dict: API response
        """
        if not self.is_authenticated:
            raise Exception("Not authenticated")
            
        if not self.baby_info:
            raise Exception("Baby information not available")
            
        if not med_id:
            raise ValueError("Medicine ID is required")
        
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        
        # Prepare medicine parameters
        medicine_data = {
            "BCObjectType": "Medicine",
            "time": time_str,
            "note": note,
            "amount": amount,
            "medID": med_id,
            "baby": self.baby_info,
            "timezone": -21600,  # This should be dynamic based on user's timezone
            "pictureNote": [],
            "pictureLoaded": "true",
            "newFlage": "true",
            "objectID": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        }
        
        try:
            response = self.post_transaction(medicine_data)
            return {"status": "success"}
        except Exception as e:
            _LOGGER.error(f"Failed to post medicine: {e}")
            return {"status": "error", "message": str(e)}
            
    def post_other_activity(self, time_str=None, activity_name="Tummy Time", duration=0, location_id=None, note=""):
        """
        Post an other activity record
        
        Args:
            time_str: Time of activity in format 'YYYY-MM-DD HH:MM:SS +0000'
            activity_name: Name of the activity
            duration: Duration in minutes
            location_id: Optional location ID
            note: Optional note text
            
        Returns:
            dict: API response
        """
        if not self.is_authenticated:
            raise Exception("Not authenticated")
            
        if not self.baby_info:
            raise Exception("Baby information not available")
            
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        
        # Create a description for the activity
        activity_desc = {
            "desc": "",
            "newFlage": "false",
            "objectID": f"EasyLogSeed{uuid.uuid4().hex[:24]}",
            "timestamp": "1970-01-01 00:00:00 +0000",
            "BCObjectType": "OtherActivityDescription",
            "name": activity_name
        }
        
        # Create the other activity transaction
        activity_data = {
            "BCObjectType": "OtherActivity",
            "note": note,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000"),
            "newFlage": "true",
            "pictureLoaded": "true",
            "time": time_str,
            "objectID": str(uuid.uuid4()),
            "desc": activity_desc,
            "baby": self.baby_info,
            "duration": duration,
            "timezone": -21600,  # This should be dynamic based on user's timezone
            "pictureNote": []
        }
        
        # Add location ID if provided
        if location_id:
            activity_data["locationID"] = location_id
            
        try:
            response = self.post_transaction(activity_data)
            return {"status": "success"}
        except Exception as e:
            _LOGGER.error(f"Failed to post activity: {e}")
            return {"status": "error", "message": str(e)}

    def post_bath(self, time_str=None, note=""):
        """
        Post a bath record

        Args:
            time_str: Time of bath in format 'YYYY-MM-DD HH:MM:SS +0000'
            note: Optional note text

        Returns:
            dict: API response
        """
        if not self.is_authenticated:
            raise Exception("Not authenticated")

        if not self.baby_info:
            raise Exception("Baby information not available")

        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")

        # Create the bath transaction
        bath_data = {
            "BCObjectType": "Bath",
            "note": note,
            "time": time_str,
            "timezone": -21600,  # This should be dynamic based on user's timezone
            "pictureNote": [],
            "pictureLoaded": "true",
            "newFlage": "true",
            "objectID": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000"),
            "baby": self.baby_info
        }

        try:
            response = self.post_transaction(bath_data)
            return {"status": "success"}
        except Exception as e:
            _LOGGER.error(f"Failed to post bath: {e}")
            return {"status": "error", "message": str(e)}

    def post_sleep(self, time_str=None, duration=0, note=""):
        """
        Post a sleep record

        Args:
            time_str: Time of sleep start in format 'YYYY-MM-DD HH:MM:SS +0000'
            duration: Duration in seconds (0 for sleep start, >0 for completed sleep)
            note: Optional note text

        Returns:
            dict: API response
        """
        if not self.is_authenticated:
            raise Exception("Not authenticated")

        if not self.baby_info:
            raise Exception("Baby information not available")

        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")

        # Create the sleep transaction
        sleep_data = {
            "BCObjectType": "Sleep",
            "note": note,
            "time": time_str,
            "duration": duration,
            "timezone": -21600,  # This should be dynamic based on user's timezone
            "pictureNote": [],
            "pictureLoaded": "true",
            "newFlage": "true",
            "objectID": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000"),
            "baby": self.baby_info
        }

        try:
            response = self.post_transaction(sleep_data)
            return {"status": "success"}
        except Exception as e:
            _LOGGER.error(f"Failed to post sleep: {e}")
            return {"status": "error", "message": str(e)}

    def post_nursing(self, time_str=None, left_duration=0, right_duration=0, both_duration=0, finish_side=1, note=""):
        """
        Post a nursing session record
        
        Args:
            time_str: Time of the nursing in format 'YYYY-MM-DD HH:MM:SS +0000'
            left_duration: Duration of left side nursing in minutes
            right_duration: Duration of right side nursing in minutes
            both_duration: Duration of both sides nursing simultaneously in minutes
            finish_side: Which side finished on (0=right, 1=left, 2=both)
            note: Optional note text
            
        Returns:
            dict: API response
        """
        if not self.is_authenticated:
            raise Exception("Not authenticated")
            
        if not self.baby_info:
            raise Exception("Baby information not available")
            
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
            
        # Create the nursing transaction
        nursing_data = {
            "BCObjectType": "Nursing",
            "note": note,
            "time": time_str,
            "rightDuration": right_duration,
            "baby": self.baby_info,
            "finishSide": finish_side,
            "bothDuration": both_duration,
            "leftDuration": left_duration,
            "timezone": -21600,  # This should be dynamic based on user's timezone
            "pictureNote": [],
            "pictureLoaded": "true",
            "newFlage": "true",
            "objectID": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
        }
        
        try:
            response = self.post_transaction(nursing_data)
            return {"status": "success"}
        except Exception as e:
            _LOGGER.error(f"Failed to post nursing: {e}")
            return {"status": "error", "message": str(e)}
    
    def post_formula(self, time_str=None, amount=0, note=""):
        """
        Post a formula feeding record
        
        Args:
            time_str: Time of feeding in format 'YYYY-MM-DD HH:MM:SS +0000'
            amount: Amount in ml
            note: Optional note text
            
        Returns:
            dict: API response
        """
        if not self.is_authenticated:
            raise Exception("Not authenticated")
            
        if not self.baby_info:
            raise Exception("Baby information not available")
            
        # Use current time if not provided
        if not time_str:
            time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
            
        # Create the formula transaction
        formula_data = {
            "amount": {
                "value": amount,
                "englishMeasure": "false",
                "BCObjectType": "VolumeMeasure"
            },
            "BCObjectType": "Formula",
            "note": note,
            "time": time_str,
            "timezone": -21600,  # This should be dynamic based on user's timezone
            "newFlage": "true",
            "pictureLoaded": "true",
            "pictureNote": [],
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000"),
            "baby": self.baby_info,
            "objectID": str(uuid.uuid4())
        }
        
        try:
            response = self.post_transaction(formula_data)
            return {"status": "success"}
        except Exception as e:
            _LOGGER.error(f"Failed to post formula: {e}")
            return {"status": "error", "message": str(e)}
    
    