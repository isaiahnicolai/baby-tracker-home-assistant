#database.py
import tempfile
import zipfile
import shutil
from .models import Baby
import sqlite3
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
from dateutil import parser

_LOGGER = logging.getLogger(__name__)

class BabyTrackerLocalDatabase:
    """
    Local SQLite database for Baby Tracker, focusing on baby info, diapers, and feedings
    """
    def __init__(self, db_path=None, db_filename='babytracker.db'):
        """
        Initialize the local database
        
        :param db_path: Path to the database file
        :param db_filename: Name of the database file (defaults to 'babytracker.db')
        """
        # Determine the database path
        if db_path:
            self.db_path = db_path
        else:
            # Default to current directory as fallback only
            self.db_path = os.path.join(os.path.dirname(__file__), db_filename)
        
        # Create database directory if it doesn't exist
        parent_dir = os.path.dirname(os.path.abspath(self.db_path))
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        _LOGGER.info(f"Initialized database at {self.db_path}")

   
    def load_seed_database(self, db_file_path):
        """
        Load a seed database file into the application
        
        :param db_file_path: Path to the database file to load
        :return: Path to the loaded database file
        """
        if not os.path.exists(db_file_path):
            raise Exception(f"Database file not found at: {db_file_path}")
        return self.db_path
    def get_baby_info(self) -> Optional[Baby]:
        """
        Retrieve baby information from the database as a Baby model
        
        :return: Baby model with details or None if no baby found
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            # Query the Baby table
            cursor.execute("SELECT ID, Name, DOB, DueDay, Gender, Picture FROM Baby LIMIT 1")
            baby_row = cursor.fetchone()
            
            if baby_row:
                # Convert timestamp to proper format
                dob = self._format_timestamp(baby_row[2]) if baby_row[2] else None
                due_day = self._format_timestamp(baby_row[3]) if baby_row[3] else None
                
                # Create a dictionary with the Baby model expected keys
                baby_data = {
                    "objectID": baby_row[0],
                    "name": baby_row[1],
                    "dob": dob,
                    "dueDay": due_day,
                    "gender": bool(baby_row[4]) if baby_row[4] is not None else False,
                    "pictureName": baby_row[5] if baby_row[5] else "",
                    "timestamp": "1970-01-01 00:00:00 +0000",  # Default timestamp
                    "BCObjectType": "Baby"
                }
                
                # Create and return a Baby model
                return Baby(baby_data)
            
            return None
        finally:
            conn.close()

    def get_all_babies(self) -> List[Baby]:
        """
        Retrieve all babies from the database.

        :return: List of Baby objects
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT ID, Name, DOB, DueDay, Gender, Picture FROM Baby ORDER BY Name")

            babies = []
            for baby_row in cursor.fetchall():
                dob = self._format_timestamp(baby_row[2]) if baby_row[2] else None
                due_day = self._format_timestamp(baby_row[3]) if baby_row[3] else None

                baby_data = {
                    "objectID": baby_row[0],
                    "name": baby_row[1],
                    "dob": dob,
                    "dueDay": due_day,
                    "gender": bool(baby_row[4]) if baby_row[4] is not None else False,
                    "pictureName": baby_row[5] if baby_row[5] else "",
                    "timestamp": "1970-01-01 00:00:00 +0000",
                    "BCObjectType": "Baby"
                }

                babies.append(Baby(baby_data))

            return babies
        finally:
            conn.close()

    def get_baby_by_name(self, name: str) -> Optional[Baby]:
        """
        Retrieve baby by name from the database.

        :param name: Baby's name
        :return: Baby object or None if not found
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT ID, Name, DOB, DueDay, Gender, Picture FROM Baby WHERE Name = ? COLLATE NOCASE", (name,))

            baby_row = cursor.fetchone()
            if baby_row:
                dob = self._format_timestamp(baby_row[2]) if baby_row[2] else None
                due_day = self._format_timestamp(baby_row[3]) if baby_row[3] else None

                baby_data = {
                    "objectID": baby_row[0],
                    "name": baby_row[1],
                    "dob": dob,
                    "dueDay": due_day,
                    "gender": bool(baby_row[4]) if baby_row[4] is not None else False,
                    "pictureName": baby_row[5] if baby_row[5] else "",
                    "timestamp": "1970-01-01 00:00:00 +0000",
                    "BCObjectType": "Baby"
                }

                return Baby(baby_data)

            return None
        finally:
            conn.close()

    def get_feedings(self, limit=50) -> List[Dict]:
        """
        Retrieve all feeding records (nursing, formula, pumped milk, supplements)
        
        :param limit: Maximum number of records to return
        :return: List of dictionaries with feeding details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Get baby ID for reference
            cursor.execute("SELECT ID FROM Baby LIMIT 1")
            baby_id_row = cursor.fetchone()
            baby_id = baby_id_row[0] if baby_id_row else None
            
            feedings = []
            
            # Nursing feedings query (based on BTDatabaseImple.getNursingForBabyImple)
            cursor.execute(f"""
                SELECT 
                    ID, 
                    BabyID,
                    Time,
                    LeftDuration, 
                    RightDuration,
                    BothDuration,
                    FinishSide,
                    HasPicture,
                    Note
                FROM Nursing 
                WHERE BabyID = ? 
                ORDER BY Time DESC
                LIMIT {limit}
            """, (baby_id,))
            
            for row in cursor.fetchall():
                # Calculate total duration based on the logic in getNursingSumDurationWithSideForBabyImpleOP
                total_duration = 0
                
                # Logic from app's code for calculating total duration
                if (row[3] == 0 or row[3] is None) and (row[4] == 0 or row[4] is None):
                    total_duration = row[5]  # BothDuration
                elif (row[3] == 0 or row[3] is None) and row[4] > 0:
                    total_duration = row[4]  # RightDuration
                elif row[3] > 0 and (row[4] == 0 or row[4] is None):
                    total_duration = row[3]  # LeftDuration
                elif row[3] > 0 and row[4] > 0:
                    total_duration = row[3] + row[4]  # LeftDuration + RightDuration
                
                feedings.append({
                    "id": row[0],
                    "baby_id": row[1],
                    "time": self._format_timestamp(row[2]),
                    "type": "Nursing",
                    "left_duration": row[3],
                    "right_duration": row[4],
                    "both_duration": row[5],
                    "total_duration": total_duration,
                    "finish_side": row[6],
                    "has_picture": bool(row[7]),
                    "note": row[8]
                })
            
            # Formula feedings query (based on BTDatabaseImple.getFormulaForBabyImple)
            cursor.execute(f"""
                SELECT 
                    ID,
                    BabyID,
                    Time,
                    Amount,
                    IsEnglishScale,
                    HasPicture,
                    Note
                FROM Formula 
                WHERE BabyID = ?
                ORDER BY Time DESC
                LIMIT {limit}
            """, (baby_id,))
            
            for row in cursor.fetchall():
                # Calculate amount in both units based on IsEnglishScale flag
                amount_oz = row[3] if row[4] == 1 else row[3] / 29.5735
                amount_ml = row[3] if row[4] == 0 else row[3] * 29.5735
                
                feedings.append({
                    "id": row[0],
                    "baby_id": row[1],
                    "time": self._format_timestamp(row[2]),
                    "type": "Formula",
                    "amount": row[3],
                    "is_english_scale": bool(row[4]),
                    "amount_oz": amount_oz,
                    "amount_ml": amount_ml,
                    "has_picture": bool(row[5]),
                    "note": row[6]
                })
            
            # Pumped milk feedings query (based on BTDatabaseImple.getPumpedForBabyImple)
            cursor.execute(f"""
                SELECT 
                    ID,
                    BabyID,
                    Time,
                    Amount,
                    IsEnglishScale,
                    HasPicture,
                    Note
                FROM Pumped 
                WHERE BabyID = ?
                ORDER BY Time DESC
                LIMIT {limit}
            """, (baby_id,))
            
            for row in cursor.fetchall():
                # Calculate amount in both units based on IsEnglishScale flag
                amount_oz = row[3] if row[4] == 1 else row[3] / 29.5735
                amount_ml = row[3] if row[4] == 0 else row[3] * 29.5735
                
                feedings.append({
                    "id": row[0],
                    "baby_id": row[1],
                    "time": self._format_timestamp(row[2]),
                    "type": "Pumped",
                    "amount": row[3],
                    "is_english_scale": bool(row[4]),
                    "amount_oz": amount_oz,
                    "amount_ml": amount_ml,
                    "has_picture": bool(row[5]),
                    "note": row[6]
                })
            
            # Other feeds/supplements (based on BTDatabaseImple.getOtherFeedForBabyImple)
            cursor.execute(f"""
                SELECT 
                    o.ID,
                    o.BabyID,
                    o.Time,
                    o.TypeID,
                    ofs.Name as FeedType,
                    o.Amount,
                    o.Unit,
                    o.IsEnglishScale,
                    o.DescID,
                    o.HasPicture,
                    o.Note
                FROM OtherFeed o
                LEFT JOIN OtherFeedSelection ofs ON o.TypeID = ofs.ID
                WHERE o.BabyID = ?
                ORDER BY o.Time DESC
                LIMIT {limit}
            """, (baby_id,))
            
            for row in cursor.fetchall():
                feedings.append({
                    "id": row[0],
                    "baby_id": row[1],
                    "time": self._format_timestamp(row[2]),
                    "type": "Supplement",
                    "type_id": row[3],
                    "feed_type": row[4],
                    "amount": row[5],
                    "unit": row[6],
                    "is_english_scale": bool(row[7]),
                    "desc_id": row[8],
                    "has_picture": bool(row[9]),
                    "note": row[10]
                })
            
            # Sort all feedings by time (descending)
            feedings.sort(key=lambda x: x["time"] if x["time"] else "", reverse=True)
            
            return feedings[:limit]
        finally:
            conn.close()

    def get_last_feeding(self) -> Optional[Dict]:
        """
        Retrieve the most recent feeding from any feeding type
        
        :return: Dictionary with feeding details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        feedings = self.get_feedings(limit=1)
        return feedings[0] if feedings else None

    def get_feeding_summary(self, days=7, baby_id: Optional[str] = None) -> Dict:
        """
        Generate feeding summary statistics for the specified number of days

        :param days: Number of days to include in summary
        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :return: Dictionary with feeding statistics
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Get timestamp values for the date range
        start_timestamp = float(start_date.timestamp())
        end_timestamp = float(end_date.timestamp())

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if not baby_id:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_id_row = cursor.fetchone()
                baby_id = baby_id_row[0] if baby_id_row else None
            if not baby_id:
                return {}
                
            # Based on getFeedSumImpleOp from the Android code
            summary = {
                "nursing_count": 0,
                "nursing_total_minutes": 0,
                "nursing_left_minutes": 0,
                "nursing_right_minutes": 0,
                "formula_count": 0,
                "formula_amount_oz": 0,
                "formula_amount_ml": 0,
                "pumped_count": 0,
                "pumped_amount_oz": 0,
                "pumped_amount_ml": 0,
                "supplement_count": 0,
                "total_feedings": 0,
                "bottle_feedings": 0,
                "bottle_amount_oz": 0,
                "bottle_amount_ml": 0
            }
            
            # Nursing summary
            cursor.execute("""
                SELECT 
                    COUNT(ID),
                    SUM(CASE 
                        WHEN (LeftDuration=0 OR LeftDuration IS NULL) AND (RightDuration=0 OR RightDuration IS NULL) THEN BothDuration
                        WHEN (LeftDuration=0 OR LeftDuration IS NULL) AND (RightDuration IS NOT NULL AND RightDuration>0) THEN RightDuration
                        WHEN (LeftDuration IS NOT NULL AND LeftDuration>0) AND (RightDuration=0 OR RightDuration IS NULL) THEN LeftDuration
                        WHEN (LeftDuration IS NOT NULL AND LeftDuration>0) AND (RightDuration IS NOT NULL AND RightDuration>0) THEN LeftDuration+RightDuration
                    END),
                    SUM(LeftDuration),
                    SUM(RightDuration)
                FROM Nursing
                WHERE BabyID = ? AND Time >= ? AND Time <= ?
            """, (baby_id, start_timestamp, end_timestamp))
            
            nursing_row = cursor.fetchone()
            if nursing_row:
                summary["nursing_count"] = nursing_row[0] or 0
                summary["nursing_total_minutes"] = nursing_row[1] or 0
                summary["nursing_left_minutes"] = nursing_row[2] or 0
                summary["nursing_right_minutes"] = nursing_row[3] or 0
                summary["total_feedings"] += summary["nursing_count"]
                
            # Formula summary
            cursor.execute("""
                SELECT 
                    COUNT(ID),
                    SUM(CASE WHEN IsEnglishScale=1 THEN Amount ELSE Amount/29.5735 END),
                    SUM(CASE WHEN IsEnglishScale=0 THEN Amount ELSE Amount*29.5735 END)
                FROM Formula
                WHERE BabyID = ? AND Time >= ? AND Time <= ?
            """, (baby_id, start_timestamp, end_timestamp))
            
            formula_row = cursor.fetchone()
            if formula_row:
                summary["formula_count"] = formula_row[0] or 0
                summary["formula_amount_oz"] = formula_row[1] or 0
                summary["formula_amount_ml"] = formula_row[2] or 0
                summary["total_feedings"] += summary["formula_count"]
                summary["bottle_feedings"] += summary["formula_count"]
                summary["bottle_amount_oz"] += summary["formula_amount_oz"]
                summary["bottle_amount_ml"] += summary["formula_amount_ml"]
            
            # Pumped milk summary
            cursor.execute("""
                SELECT 
                    COUNT(ID),
                    SUM(CASE WHEN IsEnglishScale=1 THEN Amount ELSE Amount/29.5735 END),
                    SUM(CASE WHEN IsEnglishScale=0 THEN Amount ELSE Amount*29.5735 END)
                FROM Pumped
                WHERE BabyID = ? AND Time >= ? AND Time <= ?
            """, (baby_id, start_timestamp, end_timestamp))
            
            pumped_row = cursor.fetchone()
            if pumped_row:
                summary["pumped_count"] = pumped_row[0] or 0
                summary["pumped_amount_oz"] = pumped_row[1] or 0
                summary["pumped_amount_ml"] = pumped_row[2] or 0
                summary["total_feedings"] += summary["pumped_count"]
                summary["bottle_feedings"] += summary["pumped_count"]
                summary["bottle_amount_oz"] += summary["pumped_amount_oz"]
                summary["bottle_amount_ml"] += summary["pumped_amount_ml"]
            
            # Supplements count
            cursor.execute("""
                SELECT COUNT(ID)
                FROM OtherFeed
                WHERE BabyID = ? AND Time >= ? AND Time <= ?
            """, (baby_id, start_timestamp, end_timestamp))
            
            supplement_row = cursor.fetchone()
            if supplement_row:
                summary["supplement_count"] = supplement_row[0] or 0
                summary["total_feedings"] += summary["supplement_count"]
            
            # Add daily averages
            if days > 0:
                summary["avg_feedings_per_day"] = round(summary["total_feedings"] / days, 1)
                summary["avg_nursing_minutes_per_day"] = round(summary["nursing_total_minutes"] / days, 1)
                summary["avg_bottle_feedings_per_day"] = round(summary["bottle_feedings"] / days, 1)
                summary["avg_bottle_oz_per_day"] = round(summary["bottle_amount_oz"] / days, 1)
                summary["avg_bottle_ml_per_day"] = round(summary["bottle_amount_ml"] / days, 1)
            
            return summary
        finally:
            conn.close()
    def get_diaper_summary(self, days=7, baby_id: Optional[str] = None) -> Dict:
        """
        Generate diaper summary statistics for the specified number of days

        :param days: Number of days to include in summary
        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :return: Dictionary with diaper statistics
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        # Calculate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        # Get timestamp values for the date range
        start_timestamp = int(start_date.timestamp())
        end_timestamp = int(end_date.timestamp())

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if not baby_id:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_id_row = cursor.fetchone()
                baby_id = baby_id_row[0] if baby_id_row else None
            if not baby_id:
                return {}
            
            # Initialize summary stats
            summary = {
                "total_diapers": 0,
                "wet_count": 0,
                "poopy_count": 0,
                "mixed_count": 0,
                "dry_count": 0,
                "pee_by_color": {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                "poo_by_color": {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                "texture_distribution": {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0},
                "diapers_by_day": {},
                "streak": 0,
                "last_poopy_time": None
            }
            
            # Get total count of diapers
            cursor.execute("""
                SELECT COUNT(ID) FROM Diaper 
                WHERE BabyID = ? AND Time >= ? AND Time <= ?
            """, (baby_id, start_timestamp, end_timestamp))
            count_row = cursor.fetchone()
            summary["total_diapers"] = count_row[0] if count_row else 0
            
            # Get counts by status
            cursor.execute("""
                SELECT Status, COUNT(ID) FROM Diaper 
                WHERE BabyID = ? AND Time >= ? AND Time <= ? 
                GROUP BY Status
            """, (baby_id, start_timestamp, end_timestamp))
            status_rows = cursor.fetchall()
            
            for row in status_rows:
                status, count = row
                if status == 0:
                    summary["wet_count"] = count
                elif status == 1:
                    summary["poopy_count"] = count
                elif status == 2:
                    summary["mixed_count"] = count
                elif status == 3:
                    summary["dry_count"] = count
            
            # Get pee color distribution
            cursor.execute("""
                SELECT PeeColor, COUNT(ID) FROM Diaper 
                WHERE BabyID = ? AND Time >= ? AND Time <= ? AND (Status = 0 OR Status = 2)
                GROUP BY PeeColor
            """, (baby_id, start_timestamp, end_timestamp))
            pee_rows = cursor.fetchall()
            
            for row in pee_rows:
                color, count = row
                if 0 <= color <= 5:
                    summary["pee_by_color"][color] = count
            
            # Get poo color distribution
            cursor.execute("""
                SELECT PooColor, COUNT(ID) FROM Diaper 
                WHERE BabyID = ? AND Time >= ? AND Time <= ? AND (Status = 1 OR Status = 2)
                GROUP BY PooColor
            """, (baby_id, start_timestamp, end_timestamp))
            poo_rows = cursor.fetchall()
            
            for row in poo_rows:
                color, count = row
                if 0 <= color <= 5:
                    summary["poo_by_color"][color] = count
            
            # Get texture distribution
            cursor.execute("""
                SELECT Texture, COUNT(ID) FROM Diaper 
                WHERE BabyID = ? AND Time >= ? AND Time <= ? AND (Status = 1 OR Status = 2)
                GROUP BY Texture
            """, (baby_id, start_timestamp, end_timestamp))
            texture_rows = cursor.fetchall()
            
            for row in texture_rows:
                texture, count = row
                if 0 <= texture <= 5:
                    summary["texture_distribution"][texture] = count
            
            # Get diapers by day
            for i in range(days):
                day_date = start_date + timedelta(days=i)
                day_start = int(day_date.replace(hour=0, minute=0, second=0).timestamp())
                day_end = int(day_date.replace(hour=23, minute=59, second=59).timestamp())
                
                cursor.execute("""
                    SELECT COUNT(ID) FROM Diaper 
                    WHERE BabyID = ? AND Time >= ? AND Time <= ?
                """, (baby_id, day_start, day_end))
                day_count_row = cursor.fetchone()
                day_count = day_count_row[0] if day_count_row else 0
                
                day_key = day_date.strftime("%Y-%m-%d")
                summary["diapers_by_day"][day_key] = day_count
            
            # Find when the last poopy diaper was
            cursor.execute("""
                SELECT Time FROM Diaper 
                WHERE BabyID = ? AND (Status = 1 OR Status = 2) 
                ORDER BY Time DESC LIMIT 1
            """, (baby_id,))
            last_poopy_row = cursor.fetchone()
            
            if last_poopy_row:
                last_poopy_timestamp = last_poopy_row[0]
                summary["last_poopy_time"] = self._format_timestamp(last_poopy_timestamp)
                
                # Calculate how many hours since last poopy diaper
                now_timestamp = datetime.now().timestamp()
                hours_since = (now_timestamp - last_poopy_timestamp) / 3600
                summary["hours_since_last_poopy"] = round(hours_since, 1)
            
            # Calculate the poopy diaper streak (consecutive days with poopy diapers)
            streak = 0
            for i in range(days):
                day_date = end_date - timedelta(days=i)
                day_start = int(day_date.replace(hour=0, minute=0, second=0).timestamp())
                day_end = int(day_date.replace(hour=23, minute=59, second=59).timestamp())
                
                cursor.execute("""
                    SELECT COUNT(ID) FROM Diaper 
                    WHERE BabyID = ? AND Time >= ? AND Time <= ? AND (Status = 1 OR Status = 2)
                """, (baby_id, day_start, day_end))
                day_poopy_row = cursor.fetchone()
                day_poopy_count = day_poopy_row[0] if day_poopy_row else 0
                
                if day_poopy_count > 0:
                    streak += 1
                else:
                    break
                    
            summary["poopy_streak"] = streak
            
            # Add daily averages
            if days > 0:
                summary["avg_diapers_per_day"] = round(summary["total_diapers"] / days, 1)
                summary["avg_wet_per_day"] = round(summary["wet_count"] / days, 1)
                summary["avg_poopy_per_day"] = round(summary["poopy_count"] / days, 1)
            
            return summary
        finally:
            conn.close()
            
    def get_last_temperature(self, baby_id=None) -> Optional[Dict]:
        """
        Retrieve the most recent temperature reading
        
        :param baby_id: Optional ID of the baby. If None, will use the first baby found in the database
        :return: Dictionary with temperature details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # If baby_id is not provided, get the first baby ID from the database
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_id_row = cursor.fetchone()
                baby_id = baby_id_row[0] if baby_id_row else None
                
                if baby_id is None:
                    return None  # No baby found in database
            
            # Correct SQL syntax: WHERE comes before ORDER BY
            query = "SELECT Temp, Time FROM Temperature WHERE BabyID = ? ORDER BY Time DESC LIMIT 1"
            params = [baby_id]
            cursor.execute(query, params)
            
            temp_reading = cursor.fetchone()
            
            if temp_reading:
                return {
                    "temp": temp_reading[0],
                    "time": self._format_timestamp(temp_reading[1]) if temp_reading[1] else None
                }
            return None
        except Exception as e:
            print(f"Error getting last temperature: {e}")
            return None
        finally:
            conn.close()

    def get_baby_diapers(self, baby_id: str, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> List[Dict]:
        """
        Retrieve diaper records for a specific baby
        
        :param baby_id: ID of the baby
        :param start_date: Optional start date to filter diapers
        :param end_date: Optional end date to filter diapers
        :return: List of dictionaries with diaper details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            query = "SELECT ID, Time, Status, Amount, Note FROM Diaper WHERE BabyID = ?"
            params = [baby_id]
            
            # Add date filtering if dates are provided
            if start_date:
                query += " AND Time >= ?"
                params.append(int(start_date.timestamp()))
            
            if end_date:
                query += " AND Time <= ?"
                params.append(int(end_date.timestamp()))
            
            query += " ORDER BY Time"
            
            cursor.execute(query, params)
            diaper_rows = cursor.fetchall()
            
            diapers = []
            for row in diaper_rows:
                diapers.append({
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "status": self._get_diaper_status(row[2]),
                    "amount": row[3],
                    "note": row[4]
                })
            
            return diapers
        finally:
            conn.close()
    def get_all_pumped_sessions(self) -> List[Dict]:
        """
        Retrieve all pumped milk records with no limit
        
        :return: List of dictionaries with pumped milk details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Get baby ID for reference
            cursor.execute("SELECT ID FROM Baby LIMIT 1")
            baby_id_row = cursor.fetchone()
            baby_id = baby_id_row[0] if baby_id_row else None
            
            pumped_sessions = []
            
            # Add debug logging to see the raw data
            print(f"Querying pumped milk records for baby ID: {baby_id}")
            
            # Query for all pumped milk records
            cursor.execute("""
                SELECT 
                    ID,
                    BabyID,
                    Time,
                    Amount,
                    IsEnglishScale,
                    HasPicture,
                    Note,
                    Timestamp
                FROM Pumped 
                WHERE BabyID = ?
                ORDER BY CAST(Time AS REAL) DESC
            """, (baby_id,))
            
            rows = cursor.fetchall()
            print(f"Found {len(rows)} pumped milk records")
            
            # Print raw data for debugging
            for i, row in enumerate(rows):
                print(f"Record {i}: {row}")
            
            for row in rows:
                # Calculate amount in both units based on IsEnglishScale flag
                try:
                    amount = float(row[3]) if row[3] is not None else 0.0
                    is_english = bool(row[4]) if row[4] is not None else False
                    
                    amount_oz = amount if is_english else amount / 29.5735
                    amount_ml = amount if not is_english else amount * 29.5735
                    
                    time_value = float(row[2]) if row[2] is not None else 0.0
                    timestamp_value = float(row[7]) if row[7] is not None else 0.0
                    
                    pumped_sessions.append({
                        "id": row[0],
                        "baby_id": row[1],
                        "raw_time": time_value,
                        "formatted_time": self._format_timestamp(time_value),
                        "raw_timestamp": timestamp_value,
                        "formatted_timestamp": self._format_timestamp(timestamp_value),
                        "amount": amount,
                        "is_english_scale": is_english,
                        "amount_oz": amount_oz,
                        "amount_ml": amount_ml,
                        "has_picture": bool(row[5]) if row[5] is not None else False,
                        "note": row[6]
                    })
                    
                except Exception as e:
                    print(f"Error processing row {row}: {e}")
                    # Add partial data for debugging
                    pumped_sessions.append({
                        "id": row[0],
                        "error": str(e),
                        "raw_data": str(row)
                    })
            
            return pumped_sessions
        finally:
            conn.close()
    def _get_diaper_status(self, status_code: int) -> str:
        """
        Convert diaper status code to human-readable string
        
        :param status_code: Status code from the database
        :return: Diaper status description
        """
        status_map = {
            0: "Wet",    # DiaperStatusWet
            1: "Poopy",  # DiaperStatusPoopy
            2: "Mixed",  # DiaperStatusMixed
            3: "Dry"     # DiaperStatusDry
        }
        return status_map.get(status_code, "Unknown")
    def convert_timestamp(self, timestamp_str: str) -> float:
        """Convert timestamp string to Unix timestamp with decimal places"""
        try:
            # Correct the format if it's in UTC format
            dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S +0000")
            # Return Unix timestamp as float
            return float(dt.replace(tzinfo=timezone.utc).timestamp())
        except Exception as e:
            print(f"Error converting timestamp {timestamp_str}: {e}")
            return 0.0  # Return 0.0 in case of error
    def _format_timestamp(self, timestamp):
        """
        Format a timestamp to a readable format

        :param timestamp: Timestamp to format (can be integer or float)
        :return: Formatted timestamp string
        """
        if not timestamp:
            return None
        try:
            # Ensure timestamp is treated as a float
            timestamp_float = float(timestamp)
            # Convert timestamp to datetime
            dt = datetime.fromtimestamp(timestamp_float, timezone.utc)
            # Use %z (lowercase) to get "+0000" format, not %Z which gives "UTC"
            return dt.strftime("%Y-%m-%d %H:%M:%S %z")
        except Exception as e:
            print(f"Error formatting timestamp {timestamp}: {e}")
            return None
    def delete_sleep_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a Sleep transaction from the Sleep table
        
        :param transaction_data: Decoded Sleep transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM Sleep
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting Sleep transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_sleep_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert a sleep transaction into the Sleep table
        
        :param transaction_data: Decoded sleep transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO Sleep (
                    ID, Timestamp, Time, Note, HasPicture, 
                    BabyID, Duration
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000')),  # Timestamp
                self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000')),  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureLoaded', False) else 0,
                transaction_data.get('baby', {}).get('objectID', ''),  # BabyID
                int(transaction_data.get('duration', 0))  # Duration (in minutes)
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting sleep transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_pump_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert a pump transaction into the Pump table
        
        :param transaction_data: Decoded pump transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Extract and convert data
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Handle amount and other measurements
            amount = 0
            is_english_scale = 0
            left_amount = 0
            right_amount = 0
            
            # Get total amount
            amount_data = transaction_data.get('amount', {})
            if isinstance(amount_data, dict):
                amount = float(amount_data.get('value', 0))
                english_measure = str(amount_data.get('englishMeasure', 'false')).lower()
                is_english_scale = 1 if english_measure == 'true' else 0
            
            # Get left amount
            left_amount_data = transaction_data.get('leftAmount', {})
            if isinstance(left_amount_data, dict):
                left_amount = float(left_amount_data.get('value', 0))
            else:
                left_amount = float(transaction_data.get('leftAmount', 0))
            
            # Get right amount
            right_amount_data = transaction_data.get('rightAmount', {})
            if isinstance(right_amount_data, dict):
                right_amount = float(right_amount_data.get('value', 0))
            else:
                right_amount = float(transaction_data.get('rightAmount', 0))

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO Pump (
                    ID, Timestamp, Time, Note, HasPicture, 
                    FinishSide, Sides, Amount, IsEnglishScale, Label, 
                    PumpedID, LeftAmount, RightAmount, LeftDuration, RightDuration
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                timestamp,  # Timestamp
                time,  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureLoaded', False) else 0,  # HasPicture
                transaction_data.get('finishSide', 0),  # FinishSide
                transaction_data.get('sides', 0),  # Sides
                amount,  # Amount
                is_english_scale,  # IsEnglishScale
                transaction_data.get('label', ''),  # Label
                transaction_data.get('pumpedID', ''),  # PumpedID
                left_amount,  # LeftAmount
                right_amount,  # RightAmount
                transaction_data.get('leftDuration', 0),  # LeftDuration
                transaction_data.get('rightDuration', 0)  # RightDuration
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting pump transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_pump_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a Pump transaction from the Pump table
        
        :param transaction_data: Decoded Pump transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM Pump
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting Pump transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def delete_temperature_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a temperature transaction from the Temperature table
        
        :param transaction_data: Decoded temperature transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM Temperature
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting temperature transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_temperature_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert a temperature transaction into the Temperature table
        
        :param transaction_data: Decoded temperature transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO Temperature (
                    ID, Timestamp, Time, Note, HasPicture, 
                    BabyID, Temperature, IsEnglishTemperatureMeasure
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000')),  # Timestamp
                self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000')),  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureLoaded', False) else 0,
                transaction_data.get('baby', {}).get('objectID', ''),  # BabyID
                float(transaction_data.get('temperature', {}).get('value', 0.0)),  # Temperature value
                1 if transaction_data.get('temperature', {}).get('englishMeasure', 'false').lower() == 'true' else 0  # IsEnglishTemperatureMeasure
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting temperature transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def delete_formula_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a formula transaction from the formula table
        
        :param transaction_data: Decoded formula transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM Formula
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting formula transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_formula_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert a formula transaction into the Formula table
        
        :param transaction_data: Decoded formula transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Handle amount and scale
            amount = 0
            is_english_scale = 0
            amount_data = transaction_data.get('amount', {})
            if isinstance(amount_data, dict):
                amount = float(amount_data.get('value', 0))
                # Check for string boolean for englishMeasure
                english_measure = str(amount_data.get('englishMeasure', 'false')).lower()
                is_english_scale = 1 if english_measure == 'true' else 0

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO Formula (
                    ID, Timestamp, Time, Note, HasPicture, 
                    BabyID, Amount, IsEnglishScale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000')),  # Timestamp
                self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000')),  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureLoaded', 'false').lower() == 'true' else 0,  # HasPicture
                transaction_data.get('baby', {}).get('objectID', ''),  # BabyID
                amount,  # Amount 
                is_english_scale  # IsEnglishScale
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting formula transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def delete_other_feed_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a Other Feed transaction from the Diaper table
        
        :param transaction_data: Other Feed Diaper transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM OtherFeed
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting Other Feed transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_other_feed_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert an other feed transaction into the OtherFeed table
        
        :param transaction_data: Decoded other feed transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Handle amount and scale
            amount = 0
            unit = ''
            is_english_scale = 0
            amount_data = transaction_data.get('amount', {})
            if isinstance(amount_data, dict):
                amount = float(amount_data.get('value', 0))
                # Check for string boolean for englishMeasure
                english_measure = str(amount_data.get('englishMeasure', 'false')).lower()
                is_english_scale = 1 if english_measure == 'true' else 0

            # Get feed type and other details
            feed_type = transaction_data.get('feedType', {})
            feed_type_id = feed_type.get('objectID', '')
            is_bottle = 1 if str(feed_type.get('isBottle', 'false')).lower() == 'true' else 0
            unit = transaction_data.get('unit', '')

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO OtherFeed (
                    ID, Timestamp, Time, Note, HasPicture, 
                    BabyID, DescID, TypeID, Amount, IsEnglishScale,
                    Unit, IsBottle
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000')),  # Timestamp
                self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000')),  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureLoaded', False) else 0,  # HasPicture
                transaction_data.get('baby', {}).get('objectID', ''),  # BabyID
                feed_type.get('descID', ''),  # DescID
                feed_type_id,  # TypeID
                amount,  # Amount 
                is_english_scale,  # IsEnglishScale
                unit,  # Unit
                is_bottle  # IsBottle
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting other feed transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def delete_diaper_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a Diaper transaction from the Diaper table
        
        :param transaction_data: Decoded Diaper transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM Diaper
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting diaper transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_diaper_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert a diaper transaction into the Diaper table
        
        :param transaction_data: Decoded diaper transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

         
            # Extract and convert data
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO Diaper (
                    ID, Timestamp, Time, Note, HasPicture, 
                    BabyID, Status, PeeColor, PooColor, 
                    Amount, Texture, Flag
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                timestamp,  # Timestamp
                time,  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureNote') else 0,  # HasPicture
                transaction_data.get('baby', {}).get('objectID', ''),  # BabyID
                transaction_data.get('status', 0),  # Status
                transaction_data.get('peeColor', 0),  # PeeColor
                transaction_data.get('pooColor', 0),  # PooColor
                transaction_data.get('amount', 2),  # Amount
                transaction_data.get('texture', 0),  # Texture
                0  # Flag (default)
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting diaper transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def delete_pumped_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a pumped transaction from the Pumped table
        
        :param transaction_data: Decoded pumped transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM Pumped
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting pumped transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_pumped_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert a pumped transaction into the Pumped table
        
        :param transaction_data: Decoded pumped transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
           
            # Extract and convert data
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            # Handle amount and scale
            amount = 0
            is_english_scale = 0
            amount_data = transaction_data.get('amount', {})
            if isinstance(amount_data, dict):
                amount = float(amount_data.get('value', 0))
                # Check for string boolean for englishMeasure
                english_measure = str(amount_data.get('englishMeasure', 'false')).lower()
                is_english_scale = 1 if english_measure == 'true' else 0

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO Pumped (
                    ID, Timestamp, Time, Note, HasPicture, 
                    BabyID, Amount, IsEnglishScale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                timestamp,  # Timestamp
                time,  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureLoaded', False) else 0,
                transaction_data.get('baby', {}).get('objectID', ''),  # BabyID
                amount,  # Amount 
                is_english_scale  # IsEnglishScale
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting pumped transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def delete_nursing_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a Nursing transaction from the Nursing table
        
        :param transaction_data: Decoded Nursing transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM Nursing
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting Nursing transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_nursing_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert a nursing transaction into the Nursing table
        
        :param transaction_data: Decoded nursing transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

          

            # Extract and convert data
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO Nursing (
                    ID, Timestamp, Time, Note, HasPicture, 
                    BabyID, LeftDuration, RightDuration, BothDuration
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                timestamp,  # Timestamp
                time,  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureNote') else 0,  # HasPicture
                transaction_data.get('baby', {}).get('objectID', ''),  # BabyID
                transaction_data.get('leftDuration', 0),  # LeftDuration
                transaction_data.get('rightDuration', 0),  # RightDuration
                transaction_data.get('bothDuration', 0)  # BothDuration
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting nursing transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_diaper_transactions(self, transactions: List[Dict]) -> int:
        """
        Insert multiple diaper transactions
        
        :param transactions: List of decoded diaper transaction data
        :return: Number of successfully inserted transactions
        """
        successful_inserts = 0

        for transaction in transactions:
            if transaction.get('BCObjectType') == 'Diaper':
                if self.insert_diaper_transaction(transaction):
                    successful_inserts += 1

        return successful_inserts
   
    def delete_medicine_selection_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a medicine selection from the MedicineSelection table
        
        :param transaction_data: Decoded medicine selection transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM MedicineSelection
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting medicine selection transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

   
    def delete_medicine_transaction(self, transaction_data: Dict) -> bool:
    
        """
        Delete a medicine administration record from the Medicine table
        
        :param transaction_data: Decoded medicine transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM Medicine
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting medicine transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_other_activity_desc_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert an activity description into the OtherActivityDesc table
        
        :param transaction_data: Decoded activity description transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Extract data
            object_id = transaction_data.get('objectID', '')
            name = transaction_data.get('name', '')
            desc = transaction_data.get('desc', '')
            
            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO OtherActivityDesc (
                    ID, Timestamp, Name, Description
                ) VALUES (?, ?, ?, ?)
            ''', (
                object_id,  # ID
                0.0,  # Timestamp (default to 0)
                name,  # Name
                desc   # Description
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting activity description transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_other_activity_desc_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete an activity description from the OtherActivityDesc table
        
        :param transaction_data: Decoded activity description transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM OtherActivityDesc
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting activity description transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

    def insert_other_activity_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert an activity record into the OtherActivity table
        
        :param transaction_data: Decoded activity transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Extract and convert data
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Get description ID
            desc_id = transaction_data.get('descID', '')
            if not desc_id and 'desc' in transaction_data:
                desc_id = transaction_data['desc'].get('objectID', '')
            
            # Get baby ID
            baby_id = transaction_data.get('baby_id', '')
            if not baby_id and 'baby' in transaction_data:
                baby_id = transaction_data['baby'].get('objectID', '')

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO OtherActivity (
                    ID, Timestamp, Time, Note, HasPicture,
                    BabyID, DescID, LocationID, Duration
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                timestamp,  # Timestamp
                time,  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureLoaded', False) else 0,  # HasPicture
                baby_id,  # BabyID
                desc_id,  # DescID
                transaction_data.get('locationID', ''),  # LocationID
                int(transaction_data.get('duration', 0))  # Duration
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting activity transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_other_activity_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete an activity record from the OtherActivity table
        
        :param transaction_data: Decoded activity transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM OtherActivity
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting activity transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def insert_medicine_selection_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert a medicine selection into the MedicineSelection table
        
        :param transaction_data: Decoded medicine selection transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Extract and convert data
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            
            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO MedicineSelection (
                    ID, Timestamp, Name, Description, 
                    IsPrescription, AmountPerTime, Unit, Interval
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                timestamp,  # Timestamp
                transaction_data.get('name', ''),  # Name
                transaction_data.get('description', ''),  # Description
                1 if str(transaction_data.get('isPrescription', 'false')).lower() == 'true' else 0,  # IsPrescription
                float(transaction_data.get('amountPerTime', 0.0)),  # AmountPerTime
                transaction_data.get('unit', ''),  # Unit
                int(transaction_data.get('interval', 0))  # Interval
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting medicine selection transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_medicine_selection_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a medicine selection from the MedicineSelection table
        
        :param transaction_data: Decoded medicine selection transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM MedicineSelection
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting medicine selection transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

    def insert_medicine_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert a medicine administration record into the Medicine table
        
        :param transaction_data: Decoded medicine transaction data (either Medication or Medicine)
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Extract and convert data
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Get medicine ID - handle both naming conventions
            med_id = transaction_data.get('medID', '')
            if not med_id:
                # Try medication field naming
                if 'medication' in transaction_data:
                    med_id = transaction_data['medication'].get('objectID', '')
                # Try medicine field naming
                elif 'medicine' in transaction_data:
                    med_id = transaction_data['medicine'].get('objectID', '')
            
            # Get baby ID
            baby_id = transaction_data.get('baby_id', '')
            if not baby_id and 'baby' in transaction_data:
                baby_id = transaction_data['baby'].get('objectID', '')

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO Medicine (
                    ID, Timestamp, Time, Note, HasPicture,
                    BabyID, MedID, Amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                timestamp,  # Timestamp
                time,  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureLoaded', False) else 0,  # HasPicture
                baby_id,  # BabyID
                med_id,  # MedID
                float(transaction_data.get('amount', 0.0))  # Amount
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting medicine transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_medicine_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete a medicine administration record from the Medicine table
        
        :param transaction_data: Decoded medicine transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM Medicine
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting medicine transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def get_medicine_selections(self) -> List[Dict]:
        """
        Retrieve all medicine selections
        
        :return: List of dictionaries with medicine selection details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Query for medicine selections
            cursor.execute("""
                SELECT 
                    ID, 
                    Timestamp,
                    Name, 
                    Description, 
                    IsPrescription,
                    AmountPerTime,
                    Unit,
                    Interval
                FROM MedicineSelection 
                ORDER BY Name
            """)
            
            selections = []
            for row in cursor.fetchall():
                selections.append({
                    "id": row[0],
                    "timestamp": self._format_timestamp(row[1]) if row[1] else None,
                    "name": row[2],
                    "description": row[3],
                    "is_prescription": bool(row[4]),
                    "amount_per_time": row[5],
                    "unit": row[6],
                    "interval": row[7]
                })
            
            return selections
        finally:
            conn.close()
    def get_activity_types(self) -> List[Dict]:
        """
        Retrieve all activity types
        
        :return: List of dictionaries with activity type details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Query for activity types
            cursor.execute("""
                SELECT 
                    ID, 
                    Name, 
                    Description
                FROM OtherActivityDesc 
                ORDER BY Name
            """)
            
            activity_types = []
            for row in cursor.fetchall():
                activity_types.append({
                    "id": row[0],
                    "name": row[1],
                    "description": row[2]
                })
            
            return activity_types
        finally:
            conn.close()

    def get_activity_records(self, limit=50) -> List[Dict]:
        """
        Retrieve other activity records
        
        :param limit: Maximum number of records to return
        :return: List of dictionaries with activity details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Get baby ID for reference
            cursor.execute("SELECT ID FROM Baby LIMIT 1")
            baby_id_row = cursor.fetchone()
            baby_id = baby_id_row[0] if baby_id_row else None
            
            # Query for activity records
            cursor.execute(f"""
                SELECT 
                    a.ID, 
                    a.Timestamp,
                    a.Time, 
                    a.Note, 
                    a.HasPicture,
                    a.BabyID,
                    a.DescID,
                    a.LocationID,
                    a.Duration,
                    d.Name
                FROM OtherActivity a
                LEFT JOIN OtherActivityDesc d ON a.DescID = d.ID
                WHERE a.BabyID = ? 
                ORDER BY a.Time DESC
                LIMIT {limit}
            """, (baby_id,))
            
            records = []
            for row in cursor.fetchall():
                records.append({
                    "id": row[0],
                    "timestamp": self._format_timestamp(row[1]) if row[1] else None,
                    "time": self._format_timestamp(row[2]) if row[2] else None,
                    "note": row[3],
                    "has_picture": bool(row[4]),
                    "baby_id": row[5],
                    "desc_id": row[6],
                    "location_id": row[7],
                    "duration": row[8],
                    "activity_name": row[9]
                })
            
            return records
        finally:
            conn.close()

    def get_last_activity(self) -> Optional[Dict]:
        """
        Retrieve the most recent other activity
        
        :return: Dictionary with activity details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        records = self.get_activity_records(limit=1)
        return records[0] if records else None

    def get_medicine_records(self, limit=50) -> List[Dict]:
        """
        Retrieve medicine administration records
        
        :param limit: Maximum number of records to return
        :return: List of dictionaries with medicine details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Get baby ID for reference
            cursor.execute("SELECT ID FROM Baby LIMIT 1")
            baby_id_row = cursor.fetchone()
            baby_id = baby_id_row[0] if baby_id_row else None
            
            # Query for medicine records
            cursor.execute(f"""
                SELECT 
                    m.ID, 
                    m.Timestamp,
                    m.Time, 
                    m.Note, 
                    m.HasPicture,
                    m.BabyID,
                    m.MedID,
                    m.Amount,
                    ms.Name,
                    ms.Unit
                FROM Medicine m
                LEFT JOIN MedicineSelection ms ON m.MedID = ms.ID
                WHERE m.BabyID = ? 
                ORDER BY m.Time DESC
                LIMIT {limit}
            """, (baby_id,))
            
            records = []
            for row in cursor.fetchall():
                records.append({
                    "id": row[0],
                    "timestamp": self._format_timestamp(row[1]) if row[1] else None,
                    "time": self._format_timestamp(row[2]) if row[2] else None,
                    "note": row[3],
                    "has_picture": bool(row[4]),
                    "baby_id": row[5],
                    "med_id": row[6],
                    "amount": row[7],
                    "medicine_name": row[8],
                    "unit": row[9]
                })
            
            return records
        finally:
            conn.close()

    def get_last_medicine(self) -> Optional[Dict]:
        """
        Retrieve the most recent medicine administration
        
        :return: Dictionary with medicine details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        records = self.get_medicine_records(limit=1)
        return records[0] if records else None
    def insert_other_activity_desc_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert an activity description into the OtherActivityDesc table
        
        :param transaction_data: Decoded activity description transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Extract data
            object_id = transaction_data.get('objectID', '')
            name = transaction_data.get('name', '')
            desc = transaction_data.get('desc', '')
            
            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO OtherActivityDesc (
                    ID, Timestamp, Name, Description
                ) VALUES (?, ?, ?, ?)
            ''', (
                object_id,  # ID
                0.0,  # Timestamp (default to 0)
                name,  # Name
                desc   # Description
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting activity description transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_other_activity_desc_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete an activity description from the OtherActivityDesc table
        
        :param transaction_data: Decoded activity description transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM OtherActivityDesc
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting activity description transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

    def insert_other_activity_transaction(self, transaction_data: Dict) -> bool:
        """
        Insert an activity record into the OtherActivity table
        
        :param transaction_data: Decoded activity transaction data
        :return: True if insertion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Extract and convert data
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Get description ID
            desc_id = transaction_data.get('descID', '')
            if not desc_id and 'desc' in transaction_data:
                desc_id = transaction_data['desc'].get('objectID', '')
            
            # Get baby ID
            baby_id = transaction_data.get('baby_id', '')
            if not baby_id and 'baby' in transaction_data:
                baby_id = transaction_data['baby'].get('objectID', '')

            # Prepare insertion query
            cursor.execute('''
                INSERT OR REPLACE INTO OtherActivity (
                    ID, Timestamp, Time, Note, HasPicture,
                    BabyID, DescID, LocationID, Duration
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),  # ID
                timestamp,  # Timestamp
                time,  # Time
                transaction_data.get('note', ''),  # Note
                1 if transaction_data.get('pictureLoaded', False) else 0,  # HasPicture
                baby_id,  # BabyID
                desc_id,  # DescID
                transaction_data.get('locationID', ''),  # LocationID
                int(transaction_data.get('duration', 0))  # Duration
            ))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error inserting activity transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_other_activity_transaction(self, transaction_data: Dict) -> bool:
        """
        Delete an activity record from the OtherActivity table
        
        :param transaction_data: Decoded activity transaction data
        :return: True if deletion was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Prepare deletion query
            cursor.execute('''
                DELETE FROM OtherActivity
                WHERE ID = ?
            ''', (transaction_data.get('objectID', ''),))

            # Commit the transaction
            conn.commit()
            return True

        except Exception as e:
            # Log the error or handle it as needed
            print(f"Error deleting activity transaction: {e}")
            # Rollback in case of error
            conn.rollback()
            return False
        finally:
            conn.close()
    def update_diaper_transaction(self, transaction_data):
        """
        Update a diaper transaction in the Diaper table
        
        :param transaction_data: Updated diaper transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Prepare update query
            cursor.execute('''
                UPDATE Diaper SET
                    Timestamp = ?,
                    Time = ?,
                    Note = ?,
                    HasPicture = ?,
                    Status = ?,
                    PeeColor = ?,
                    PooColor = ?,
                    Amount = ?,
                    Texture = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                transaction_data.get('status', 0),
                transaction_data.get('peeColor', 0),
                transaction_data.get('pooColor', 0),
                transaction_data.get('amount', 2),
                transaction_data.get('texture', 0),
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating diaper transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_nursing_transaction(self, transaction_data):
        """
        Update a nursing transaction in the Nursing table
        
        :param transaction_data: Updated nursing transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Prepare update query
            cursor.execute('''
                UPDATE Nursing SET
                    Timestamp = ?,
                    Time = ?,
                    Note = ?,
                    HasPicture = ?,
                    LeftDuration = ?,
                    RightDuration = ?,
                    BothDuration = ?,
                    FinishSide = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureLoaded', False) else 0,
                transaction_data.get('leftDuration', 0),
                transaction_data.get('rightDuration', 0),
                transaction_data.get('bothDuration', 0),
                transaction_data.get('finishSide', 0),
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating nursing transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_pumped_transaction(self, transaction_data):
        """
        Update a pumped transaction in the Pumped table
        
        :param transaction_data: Updated pumped transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Handle amount and scale
            amount = 0
            is_english_scale = 0
            amount_data = transaction_data.get('amount', {})
            if isinstance(amount_data, dict):
                amount = float(amount_data.get('value', 0))
                english_measure = str(amount_data.get('englishMeasure', 'false')).lower()
                is_english_scale = 1 if english_measure == 'true' else 0
                
            # Prepare update query
            cursor.execute('''
                UPDATE Pumped SET
                    Timestamp = ?,
                    Time = ?,
                    Note = ?,
                    HasPicture = ?,
                    Amount = ?,
                    IsEnglishScale = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureLoaded', False) else 0,
                amount,
                is_english_scale,
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating pumped transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_formula_transaction(self, transaction_data):
        """
        Update a formula transaction in the Formula table
        
        :param transaction_data: Updated formula transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Handle amount and scale
            amount = 0
            is_english_scale = 0
            amount_data = transaction_data.get('amount', {})
            if isinstance(amount_data, dict):
                amount = float(amount_data.get('value', 0))
                english_measure = str(amount_data.get('englishMeasure', 'false')).lower()
                is_english_scale = 1 if english_measure == 'true' else 0
                
            # Prepare update query
            cursor.execute('''
                UPDATE Formula SET
                    Timestamp = ?,
                    Time = ?,
                    Note = ?,
                    HasPicture = ?,
                    Amount = ?,
                    IsEnglishScale = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureLoaded', 'false').lower() == 'true' else 0,
                amount,
                is_english_scale,
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating formula transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_temperature_transaction(self, transaction_data):
        """
        Update a temperature transaction in the Temperature table
        
        :param transaction_data: Updated temperature transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Prepare update query
            cursor.execute('''
                UPDATE Temperature SET
                    Timestamp = ?,
                    Time = ?,
                    Note = ?,
                    HasPicture = ?,
                    Temperature = ?,
                    IsEnglishTemperatureMeasure = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureLoaded', False) else 0,
                float(transaction_data.get('temperature', {}).get('value', 0.0)),
                1 if transaction_data.get('temperature', {}).get('englishMeasure', 'false').lower() == 'true' else 0,
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating temperature transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_sleep_transaction(self, transaction_data):
        """
        Update a sleep transaction in the Sleep table
        
        :param transaction_data: Updated sleep transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Prepare update query
            cursor.execute('''
                UPDATE Sleep SET
                    Timestamp = ?,
                    Time = ?,
                    Note = ?,
                    HasPicture = ?,
                    Duration = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureLoaded', False) else 0,
                int(transaction_data.get('duration', 0)),
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating sleep transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_other_feed_transaction(self, transaction_data):
        """
        Update an other feed transaction in the OtherFeed table
        
        :param transaction_data: Updated other feed transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Handle amount and scale
            amount = 0
            is_english_scale = 0
            amount_data = transaction_data.get('amount', {})
            if isinstance(amount_data, dict):
                amount = float(amount_data.get('value', 0))
                english_measure = str(amount_data.get('englishMeasure', 'false')).lower()
                is_english_scale = 1 if english_measure == 'true' else 0
                
            # Get feed type and other details
            feed_type = transaction_data.get('feedType', {})
            feed_type_id = feed_type.get('objectID', '')
            is_bottle = 1 if str(feed_type.get('isBottle', 'false')).lower() == 'true' else 0
            unit = transaction_data.get('unit', '')
            
            # Prepare update query
            cursor.execute('''
                UPDATE OtherFeed SET
                    Timestamp = ?,
                    Time = ?,
                    Note = ?,
                    HasPicture = ?,
                    DescID = ?,
                    TypeID = ?,
                    Amount = ?,
                    IsEnglishScale = ?,
                    Unit = ?,
                    IsBottle = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureLoaded', False) else 0,
                feed_type.get('descID', ''),
                feed_type_id,
                amount,
                is_english_scale,
                unit,
                is_bottle,
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating other feed transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_pump_transaction(self, transaction_data):
        """
        Update a pump transaction in the Pump table
        
        :param transaction_data: Updated pump transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Handle amount and other measurements
            amount = 0
            is_english_scale = 0
            left_amount = 0
            right_amount = 0
            
            # Get total amount
            amount_data = transaction_data.get('amount', {})
            if isinstance(amount_data, dict):
                amount = float(amount_data.get('value', 0))
                english_measure = str(amount_data.get('englishMeasure', 'false')).lower()
                is_english_scale = 1 if english_measure == 'true' else 0
            
            # Get left amount
            left_amount_data = transaction_data.get('leftAmount', {})
            if isinstance(left_amount_data, dict):
                left_amount = float(left_amount_data.get('value', 0))
            else:
                left_amount = float(transaction_data.get('leftAmount', 0))
            
            # Get right amount
            right_amount_data = transaction_data.get('rightAmount', {})
            if isinstance(right_amount_data, dict):
                right_amount = float(right_amount_data.get('value', 0))
            else:
                right_amount = float(transaction_data.get('rightAmount', 0))
            
            # Prepare update query
            cursor.execute('''
                UPDATE Pump SET
                    Timestamp = ?,
                    Time = ?,
                    Note = ?,
                    HasPicture = ?,
                    FinishSide = ?,
                    Sides = ?,
                    Amount = ?,
                    IsEnglishScale = ?,
                    Label = ?,
                    PumpedID = ?,
                    LeftAmount = ?,
                    RightAmount = ?,
                    LeftDuration = ?,
                    RightDuration = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureLoaded', False) else 0,
                transaction_data.get('finishSide', 0),
                transaction_data.get('sides', 0),
                amount,
                is_english_scale,
                transaction_data.get('label', ''),
                transaction_data.get('pumpedID', ''),
                left_amount,
                right_amount,
                transaction_data.get('leftDuration', 0),
                transaction_data.get('rightDuration', 0),
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating pump transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_medicine_transaction(self, transaction_data):
        """
        Update a medicine transaction in the Medicine table
        
        :param transaction_data: Updated medicine transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Get medicine ID - handle both naming conventions
            med_id = transaction_data.get('medID', '')
            if not med_id:
                # Try medication field naming
                if 'medication' in transaction_data:
                    med_id = transaction_data['medication'].get('objectID', '')
                # Try medicine field naming
                elif 'medicine' in transaction_data:
                    med_id = transaction_data['medicine'].get('objectID', '')
            
            # Prepare update query
            cursor.execute('''
                UPDATE Medicine SET
                    Timestamp = ?,
                    Time = ?,
                    Note = ?,
                    HasPicture = ?,
                    MedID = ?,
                    Amount = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureLoaded', False) else 0,
                med_id,
                float(transaction_data.get('amount', 0.0)),
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating medicine transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_medicine_selection_transaction(self, transaction_data):
        """
        Update a medicine selection in the MedicineSelection table
        
        :param transaction_data: Updated medicine selection transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            
            # Prepare update query
            cursor.execute('''
                UPDATE MedicineSelection SET
                    Timestamp = ?,
                    Name = ?,
                    Description = ?,
                    IsPrescription = ?,
                    AmountPerTime = ?,
                    Unit = ?,
                    Interval = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                transaction_data.get('name', ''),
                transaction_data.get('description', ''),
                1 if str(transaction_data.get('isPrescription', 'false')).lower() == 'true' else 0,
                float(transaction_data.get('amountPerTime', 0.0)),
                transaction_data.get('unit', ''),
                int(transaction_data.get('interval', 0)),
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating medicine selection transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_other_activity_transaction(self, transaction_data):
        """
        Update an activity record in the OtherActivity table
        
        :param transaction_data: Updated activity transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract and convert data
            object_id = transaction_data.get('objectID', '')
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))
            
            # Get description ID
            desc_id = transaction_data.get('descID', '')
            if not desc_id and 'desc' in transaction_data:
                desc_id = transaction_data['desc'].get('objectID', '')
            
            # Prepare update query
            cursor.execute('''
                UPDATE OtherActivity SET
                    Timestamp = ?,
                    Time = ?,
                    Note = ?,
                    HasPicture = ?,
                    DescID = ?,
                    LocationID = ?,
                    Duration = ?
                WHERE ID = ? AND Timestamp < ?
            ''', (
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureLoaded', False) else 0,
                desc_id,
                transaction_data.get('locationID', ''),
                int(transaction_data.get('duration', 0)),
                object_id,
                timestamp
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating activity transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_other_activity_desc_transaction(self, transaction_data):
        """
        Update an activity description in the OtherActivityDesc table
        
        :param transaction_data: Updated activity description transaction data
        :return: True if update was successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            
            # Extract data
            object_id = transaction_data.get('objectID', '')
            name = transaction_data.get('name', '')
            desc = transaction_data.get('desc', '')
            
            # Prepare update query
            cursor.execute('''
                UPDATE OtherActivityDesc SET
                    Name = ?,
                    Description = ?
                WHERE ID = ?
            ''', (
                name,
                desc,
                object_id,
            ))
            
            conn.commit()
            return cursor.rowcount > 0
        
        except Exception as e:
            print(f"Error updating activity description transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # ===== MILESTONE TRANSACTION METHODS =====

    def insert_milestone_transaction(self, transaction_data: Dict) -> bool:
        """Insert a milestone transaction into the Milestone table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            cursor.execute('''
                INSERT OR REPLACE INTO Milestone (
                    ID, Timestamp, Time, Note, HasPicture, BabyID, MilestoneSelectionID
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                transaction_data.get('baby', {}).get('objectID', ''),
                transaction_data.get('milestoneSelectionID', '')
            ))

            conn.commit()
            return True
        except Exception as e:
            print(f"Error inserting milestone transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_milestone_transaction(self, transaction_data: Dict) -> bool:
        """Update a milestone in the Milestone table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            cursor.execute('''
                UPDATE Milestone SET
                    Time = ?, Note = ?, HasPicture = ?, MilestoneSelectionID = ?
                WHERE ID = ?
            ''', (
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                transaction_data.get('milestoneSelectionID', ''),
                transaction_data.get('objectID', '')
            ))

            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error updating milestone transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_milestone_transaction(self, transaction_data: Dict) -> bool:
        """Delete a milestone from the Milestone table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM Milestone WHERE ID = ?', (transaction_data.get('objectID', ''),))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting milestone transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # ===== DOCTOR VISIT TRANSACTION METHODS =====

    def insert_doctor_visit_transaction(self, transaction_data: Dict) -> bool:
        """Insert a doctor visit transaction into the DoctorVisit table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            cursor.execute('''
                INSERT OR REPLACE INTO DoctorVisit (
                    ID, Timestamp, Time, Note, HasPicture, BabyID,
                    IsAppointment, VisitType, DoctorID, DoctorNote,
                    Symptom, GrowthID, SickID
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                transaction_data.get('baby', {}).get('objectID', ''),
                1 if transaction_data.get('isAppointment', True) else 0,
                transaction_data.get('visitType', 0),
                transaction_data.get('doctorID', ''),
                transaction_data.get('doctorNote', ''),
                transaction_data.get('symptom', ''),
                transaction_data.get('growthID', ''),
                transaction_data.get('sickID', '')
            ))

            conn.commit()
            return True
        except Exception as e:
            print(f"Error inserting doctor visit transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_doctor_visit_transaction(self, transaction_data: Dict) -> bool:
        """Update a doctor visit in the DoctorVisit table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            cursor.execute('''
                UPDATE DoctorVisit SET
                    Time = ?, Note = ?, HasPicture = ?, IsAppointment = ?,
                    VisitType = ?, DoctorID = ?, DoctorNote = ?, Symptom = ?,
                    GrowthID = ?, SickID = ?
                WHERE ID = ?
            ''', (
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                1 if transaction_data.get('isAppointment', True) else 0,
                transaction_data.get('visitType', 0),
                transaction_data.get('doctorID', ''),
                transaction_data.get('doctorNote', ''),
                transaction_data.get('symptom', ''),
                transaction_data.get('growthID', ''),
                transaction_data.get('sickID', ''),
                transaction_data.get('objectID', '')
            ))

            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error updating doctor visit transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_doctor_visit_transaction(self, transaction_data: Dict) -> bool:
        """Delete a doctor visit from the DoctorVisit table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM DoctorVisit WHERE ID = ?', (transaction_data.get('objectID', ''),))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting doctor visit transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # ===== VACCINE TRANSACTION METHODS =====

    def insert_vaccine_transaction(self, transaction_data: Dict) -> bool:
        """Insert a vaccine transaction into the Vaccine table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            cursor.execute('''
                INSERT OR REPLACE INTO Vaccine (
                    ID, Timestamp, Time, Note, HasPicture, BabyID, VaccID, DocVisitID
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                transaction_data.get('baby', {}).get('objectID', ''),
                transaction_data.get('vaccID', ''),
                transaction_data.get('docVisitID', '')
            ))

            conn.commit()
            return True
        except Exception as e:
            print(f"Error inserting vaccine transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_vaccine_transaction(self, transaction_data: Dict) -> bool:
        """Update a vaccine in the Vaccine table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            cursor.execute('''
                UPDATE Vaccine SET
                    Time = ?, Note = ?, HasPicture = ?, VaccID = ?, DocVisitID = ?
                WHERE ID = ?
            ''', (
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                transaction_data.get('vaccID', ''),
                transaction_data.get('docVisitID', ''),
                transaction_data.get('objectID', '')
            ))

            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error updating vaccine transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_vaccine_transaction(self, transaction_data: Dict) -> bool:
        """Delete a vaccine from the Vaccine table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM Vaccine WHERE ID = ?', (transaction_data.get('objectID', ''),))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting vaccine transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # ===== GROWTH TRANSACTION METHODS =====

    def insert_growth_transaction(self, transaction_data: Dict) -> bool:
        """Insert a growth transaction into the Growth table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            cursor.execute('''
                INSERT OR REPLACE INTO Growth (
                    ID, Timestamp, Time, Note, HasPicture, BabyID,
                    Weight, Length, Head, IsEnglishWeightScale, IsEnglishLengthScale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                transaction_data.get('baby', {}).get('objectID', ''),
                transaction_data.get('weight', 0.0),
                transaction_data.get('length', 0.0),
                transaction_data.get('head', 0.0),
                1 if transaction_data.get('isEnglishWeightScale', True) else 0,
                1 if transaction_data.get('isEnglishLengthScale', True) else 0
            ))

            conn.commit()
            return True
        except Exception as e:
            print(f"Error inserting growth transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_growth_transaction(self, transaction_data: Dict) -> bool:
        """Update a growth record in the Growth table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            cursor.execute('''
                UPDATE Growth SET
                    Time = ?, Note = ?, HasPicture = ?, Weight = ?, Length = ?,
                    Head = ?, IsEnglishWeightScale = ?, IsEnglishLengthScale = ?
                WHERE ID = ?
            ''', (
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                transaction_data.get('weight', 0.0),
                transaction_data.get('length', 0.0),
                transaction_data.get('head', 0.0),
                1 if transaction_data.get('isEnglishWeightScale', True) else 0,
                1 if transaction_data.get('isEnglishLengthScale', True) else 0,
                transaction_data.get('objectID', '')
            ))

            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error updating growth transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_growth_transaction(self, transaction_data: Dict) -> bool:
        """Delete a growth record from the Growth table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM Growth WHERE ID = ?', (transaction_data.get('objectID', ''),))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting growth transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # ===== BATH TRANSACTION METHODS =====

    def insert_bath_transaction(self, transaction_data: Dict) -> bool:
        """Insert a bath transaction into the Bath table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            timestamp = self.convert_timestamp(transaction_data.get('timestamp', '1970-01-01 00:00:00 +0000'))
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            cursor.execute('''
                INSERT OR REPLACE INTO Bath (
                    ID, Timestamp, Time, Note, HasPicture, BabyID, DescID
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                transaction_data.get('objectID', ''),
                timestamp,
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                transaction_data.get('baby', {}).get('objectID', ''),
                transaction_data.get('descID', '')
            ))

            conn.commit()
            return True
        except Exception as e:
            print(f"Error inserting bath transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def update_bath_transaction(self, transaction_data: Dict) -> bool:
        """Update a bath in the Bath table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            time = self.convert_timestamp(transaction_data.get('time', '1970-01-01 00:00:00 +0000'))

            cursor.execute('''
                UPDATE Bath SET
                    Time = ?, Note = ?, HasPicture = ?, DescID = ?
                WHERE ID = ?
            ''', (
                time,
                transaction_data.get('note', ''),
                1 if transaction_data.get('pictureNote') else 0,
                transaction_data.get('descID', ''),
                transaction_data.get('objectID', '')
            ))

            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error updating bath transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def delete_bath_transaction(self, transaction_data: Dict) -> bool:
        """Delete a bath from the Bath table"""
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM Bath WHERE ID = ?', (transaction_data.get('objectID', ''),))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting bath transaction: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def time_since_last_feeding(self) -> Optional[Dict]:
        """
        Retrieve the time since the last feeding with precision for infant care
        
        :return: Dictionary with detailed feeding details
        """
        # Check if database exists
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        
        # Get current time in UTC
        now = datetime.now(timezone.utc)
        
        # Get the most recent feeding record
        feeding = self.get_feedings(limit=1)[0]
        
        # Parse the feeding time correctly with timezone handling
        try:
            datetime_obj = parser.parse(feeding["time"])
        except Exception as e:
            raise ValueError(f"Error parsing feeding time: {e}")
        
        # Calculate the time difference
        time_diff = now - datetime_obj
        
        # Calculate hours and minutes for precision
        total_minutes = time_diff.total_seconds() / 60
        hours = int(total_minutes // 60)
        minutes = int(total_minutes % 60)
        
        # Create human-friendly string with more precision
        if hours == 0:
            if minutes == 1:
                friendly_time = "1 minute ago"
            else:
                friendly_time = f"{minutes} minutes ago"
        elif hours == 1:
            friendly_time = f"1 hour and {minutes} minutes ago"
        else:
            friendly_time = f"{hours} hours and {minutes} minutes ago"
        
        # Create a status label for feeding urgency
        if total_minutes < 30:
            status = "Recently fed"
        elif total_minutes < 120:
            status = "Fed recently"
        elif total_minutes < 180:
            status = "Due for feeding soon"
        elif total_minutes < 210:
            status = "Feeding due very soon"
        elif total_minutes < 240:
            status = "Feeding overdue"
        else:
            status = "Feeding critically overdue"
        
        return {
            "hours_since_last_feeding": hours,
            "minutes_since_last_feeding": minutes,
            "total_minutes": int(total_minutes),
            "time_difference": str(time_diff),
            "last_feeding_time": datetime_obj.isoformat(),
            "friendly_time": friendly_time,
            "status": status
        }
    def get_progress_data(self, progress_type: int, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Retrieve progress data from the Progress table for a specific progress type.

        The Progress table is used by the Android app to cache "last activity" information.

        ProgressType values (from Android app):
        - 0: FeedCount (last feed count)
        - 1: NursingCount (last nursing count)
        - 2: NursingMinute (last nursing duration)
        - 3: ExpressedCount (last pumped milk count)
        - 4: ExpressedAmount (last pumped milk amount)
        - 5: FormulaCount (last formula count)
        - 6: FormulaAmount (last formula amount)
        - 7: DiaperCount (last diaper count)
        - 8: SleepMaxMinute (last max sleep duration)
        - 9: PumpCount (last pump count)
        - 10: PumpMinute (last pump duration)
        - 11: PumpAmount (last pump amount)

        :param progress_type: Integer 0-11 identifying the progress type
        :param baby_id: Optional baby ID. If None, uses first baby in database
        :return: Dictionary with progress data or None if not found
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None

                if baby_id is None:
                    return None

            # Query the Progress table
            cursor.execute("""
                SELECT ProgressID, ProgressTime, ProgressValue
                FROM Progress
                WHERE BabyID = ? AND ProgressType = ?
            """, (baby_id, progress_type))

            row = cursor.fetchone()

            if row:
                return {
                    "progress_id": row[0],
                    "progress_time": row[1],
                    "progress_time_formatted": self._format_timestamp(row[1]) if row[1] else None,
                    "progress_value": row[2]
                }
            return None
        finally:
            conn.close()

    def get_last_diaper_from_progress(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the last diaper change info from the Progress table.

        :param baby_id: Optional baby ID
        :return: Dictionary with last diaper info or None
        """
        progress_data = self.get_progress_data(7, baby_id)  # ProgressType 7 = DiaperCount
        if not progress_data:
            return None

        # Get additional details from the Diaper table if needed
        if not os.path.exists(self.db_path):
            return None

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get the diaper record details
            cursor.execute("""
                SELECT Status, Note, PeeColor, PooColor, Amount, Texture
                FROM Diaper
                WHERE ID = ?
            """, (progress_data["progress_id"],))

            diaper_row = cursor.fetchone()

            if diaper_row:
                return {
                    "id": progress_data["progress_id"],
                    "time": progress_data["progress_time_formatted"],
                    "raw_time": progress_data["progress_time"],
                    "status": self._get_diaper_status(diaper_row[0]),
                    "status_code": diaper_row[0],
                    "note": diaper_row[1] if diaper_row[1] else "",
                    "pee_color": diaper_row[2],
                    "poo_color": diaper_row[3],
                    "amount": diaper_row[4],
                    "texture": diaper_row[5],
                    "count": progress_data["progress_value"]
                }

            # If diaper record not found, return basic progress data
            return {
                "time": progress_data["progress_time_formatted"],
                "raw_time": progress_data["progress_time"],
                "count": progress_data["progress_value"]
            }
        finally:
            conn.close()

    def get_last_sleep_from_progress(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the last sleep info from the Progress table.

        :param baby_id: Optional baby ID
        :return: Dictionary with last sleep info or None
        """
        progress_data = self.get_progress_data(8, baby_id)  # ProgressType 8 = SleepMaxMinute
        if not progress_data:
            return None

        # Get additional details from the Sleep table if needed
        if not os.path.exists(self.db_path):
            return None

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get the sleep record details
            cursor.execute("""
                SELECT Duration, Note, LocationID, DescID
                FROM Sleep
                WHERE ID = ?
            """, (progress_data["progress_id"],))

            sleep_row = cursor.fetchone()

            if sleep_row:
                return {
                    "id": progress_data["progress_id"],
                    "time": progress_data["progress_time_formatted"],
                    "raw_time": progress_data["progress_time"],
                    "duration": sleep_row[0],
                    "max_duration_minutes": progress_data["progress_value"],
                    "note": sleep_row[1] if sleep_row[1] else "",
                    "location_id": sleep_row[2],
                    "desc_id": sleep_row[3]
                }

            # If sleep record not found, return basic progress data
            return {
                "time": progress_data["progress_time_formatted"],
                "raw_time": progress_data["progress_time"],
                "duration": progress_data["progress_value"]
            }
        finally:
            conn.close()

    def get_last_nursing_from_progress(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the last nursing info from the Progress table.

        :param baby_id: Optional baby ID
        :return: Dictionary with last nursing info or None
        """
        # Get both nursing count and nursing minutes from Progress table
        count_data = self.get_progress_data(1, baby_id)  # ProgressType 1 = NursingCount
        minute_data = self.get_progress_data(2, baby_id)  # ProgressType 2 = NursingMinute

        if not count_data and not minute_data:
            return None

        # Use whichever has data, preferring count_data
        progress_data = count_data if count_data else minute_data

        # Get additional details from the Nursing table
        if not os.path.exists(self.db_path):
            return None

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get the nursing record details
            cursor.execute("""
                SELECT LeftDuration, RightDuration, BothDuration, FinishSide, Note
                FROM Nursing
                WHERE ID = ?
            """, (progress_data["progress_id"],))

            nursing_row = cursor.fetchone()

            if nursing_row:
                # Calculate total duration using same logic as get_feedings()
                left_duration = nursing_row[0] or 0
                right_duration = nursing_row[1] or 0
                both_duration = nursing_row[2] or 0

                if left_duration == 0 and right_duration == 0:
                    total_duration = both_duration
                elif left_duration == 0 and right_duration > 0:
                    total_duration = right_duration
                elif left_duration > 0 and right_duration == 0:
                    total_duration = left_duration
                else:
                    total_duration = left_duration + right_duration

                return {
                    "id": progress_data["progress_id"],
                    "time": progress_data["progress_time_formatted"],
                    "raw_time": progress_data["progress_time"],
                    "type": "Nursing",
                    "left_duration": left_duration,
                    "right_duration": right_duration,
                    "both_duration": both_duration,
                    "total_duration": total_duration,
                    "finish_side": nursing_row[3],
                    "note": nursing_row[4] if nursing_row[4] else "",
                    "count": count_data["progress_value"] if count_data else None
                }

            # If nursing record not found, return basic progress data
            return {
                "time": progress_data["progress_time_formatted"],
                "raw_time": progress_data["progress_time"],
                "type": "Nursing",
                "total_duration": minute_data["progress_value"] if minute_data else 0,
                "count": count_data["progress_value"] if count_data else None
            }
        finally:
            conn.close()

    def get_last_feed_time_from_progress(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the last feeding time from the Progress table.
        This looks across all feed types to find the most recent.

        :param baby_id: Optional baby ID
        :return: Dictionary with last feed time or None
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        # Get all feed-related progress types and find the most recent
        feed_types = [
            (0, "Feed"),  # FeedCount
            (1, "Nursing"),  # NursingCount
            (5, "Formula"),  # FormulaCount
            (3, "Pumped"),  # ExpressedCount (Pumped milk)
        ]

        most_recent = None
        most_recent_time = 0

        for progress_type, feed_name in feed_types:
            progress_data = self.get_progress_data(progress_type, baby_id)
            if progress_data and progress_data["progress_time"] > most_recent_time:
                most_recent_time = progress_data["progress_time"]
                most_recent = {
                    "time": progress_data["progress_time_formatted"],
                    "raw_time": progress_data["progress_time"],
                    "type": feed_name,
                    "count": progress_data["progress_value"]
                }

        return most_recent

    # ===== DIRECT QUERY METHODS (Don't rely on Progress table) =====
    # These methods query activity tables directly and will work even if
    # the Progress table is not being maintained by sync logic

    def get_last_diaper_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the last diaper change by querying the Diaper table directly.
        This method does NOT rely on the Progress table.

        :param baby_id: Optional baby ID
        :return: Dictionary with last diaper info or None
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None

                if baby_id is None:
                    return None

            # Query Diaper table directly - same logic as Android app's getLastActivityForBabyBefore
            cursor.execute("""
                SELECT ID, Time, Status, Note, PeeColor, PooColor, Amount, Texture
                FROM Diaper
                WHERE BabyID = ?
                ORDER BY Time DESC
                LIMIT 1
            """, (baby_id,))

            row = cursor.fetchone()

            if row:
                return {
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "status": self._get_diaper_status(row[2]),
                    "status_code": row[2],
                    "note": row[3] if row[3] else "",
                    "pee_color": row[4],
                    "poo_color": row[5],
                    "amount": row[6],
                    "texture": row[7]
                }
            return None
        finally:
            conn.close()

    def get_last_sleep_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the last sleep by querying the Sleep table directly.
        This method does NOT rely on the Progress table.

        :param baby_id: Optional baby ID
        :return: Dictionary with last sleep info or None
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None

                if baby_id is None:
                    return None

            # Query Sleep table directly
            cursor.execute("""
                SELECT ID, Time, Duration, Note, LocationID, DescID
                FROM Sleep
                WHERE BabyID = ?
                ORDER BY Time DESC
                LIMIT 1
            """, (baby_id,))

            row = cursor.fetchone()

            if row:
                duration = row[2] or 0
                start_time = row[1]

                # CRITICAL: duration == 0 means sleep is IN PROGRESS (currently sleeping)
                # duration > 0 means sleep is COMPLETED
                is_sleeping = (duration == 0)

                # If sleep is in progress, calculate current duration
                current_duration = duration
                if is_sleeping and start_time:
                    # Calculate how long they've been sleeping
                    current_time = datetime.now(timezone.utc).timestamp()
                    current_duration = int((current_time - start_time) / 60)  # minutes

                return {
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "duration": duration,  # Original duration from database
                    "current_duration": current_duration,  # Real-time duration if sleeping
                    "is_sleeping": is_sleeping,  # True if currently sleeping
                    "status": "sleeping" if is_sleeping else "awake",
                    "note": row[3] if row[3] else "",
                    "location_id": row[4],
                    "desc_id": row[5]
                }
            return None
        finally:
            conn.close()

    def is_currently_sleeping(self, baby_id: Optional[str] = None) -> bool:
        """
        Check if the baby is currently sleeping (has an in-progress sleep).

        In Baby Tracker, a sleep with duration=0 indicates "in progress" sleep.

        :param baby_id: Optional baby ID
        :return: True if baby is currently sleeping, False otherwise
        """
        last_sleep = self.get_last_sleep_direct(baby_id)
        if not last_sleep:
            return False

        # duration == 0 means sleep is in progress
        return last_sleep.get("is_sleeping", False)

    def get_last_nursing_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the last nursing session by querying the Nursing table directly.
        This method does NOT rely on the Progress table.

        :param baby_id: Optional baby ID
        :return: Dictionary with last nursing info or None
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None

                if baby_id is None:
                    return None

            # Query Nursing table directly
            cursor.execute("""
                SELECT ID, Time, LeftDuration, RightDuration, BothDuration, FinishSide, Note
                FROM Nursing
                WHERE BabyID = ?
                ORDER BY Time DESC
                LIMIT 1
            """, (baby_id,))

            row = cursor.fetchone()

            if row:
                # Calculate total duration using same logic as get_feedings()
                left_duration = row[2] or 0
                right_duration = row[3] or 0
                both_duration = row[4] or 0

                if left_duration == 0 and right_duration == 0:
                    total_duration = both_duration
                elif left_duration == 0 and right_duration > 0:
                    total_duration = right_duration
                elif left_duration > 0 and right_duration == 0:
                    total_duration = left_duration
                else:
                    total_duration = left_duration + right_duration

                return {
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "type": "Nursing",
                    "left_duration": left_duration,
                    "right_duration": right_duration,
                    "both_duration": both_duration,
                    "total_duration": total_duration,
                    "finish_side": row[5],
                    "note": row[6] if row[6] else ""
                }
            return None
        finally:
            conn.close()

    def get_last_feed_time_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the time of the most recent feeding (any type) by querying tables directly.
        This method does NOT rely on the Progress table.

        :param baby_id: Optional baby ID
        :return: Dictionary with last feed time or None
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None

                if baby_id is None:
                    return None

            # Query all feed types and find the most recent
            most_recent = None
            most_recent_time = 0

            # Check Nursing
            cursor.execute("SELECT Time FROM Nursing WHERE BabyID = ? ORDER BY Time DESC LIMIT 1", (baby_id,))
            nursing_row = cursor.fetchone()
            if nursing_row and nursing_row[0] > most_recent_time:
                most_recent_time = nursing_row[0]
                most_recent = {"time": self._format_timestamp(nursing_row[0]), "raw_time": nursing_row[0], "type": "Nursing"}

            # Check Formula
            cursor.execute("SELECT Time FROM Formula WHERE BabyID = ? ORDER BY Time DESC LIMIT 1", (baby_id,))
            formula_row = cursor.fetchone()
            if formula_row and formula_row[0] > most_recent_time:
                most_recent_time = formula_row[0]
                most_recent = {"time": self._format_timestamp(formula_row[0]), "raw_time": formula_row[0], "type": "Formula"}

            # Check Pumped
            cursor.execute("SELECT Time FROM Pumped WHERE BabyID = ? ORDER BY Time DESC LIMIT 1", (baby_id,))
            pumped_row = cursor.fetchone()
            if pumped_row and pumped_row[0] > most_recent_time:
                most_recent_time = pumped_row[0]
                most_recent = {"time": self._format_timestamp(pumped_row[0]), "raw_time": pumped_row[0], "type": "Pumped"}

            # Check OtherFeed
            cursor.execute("SELECT Time FROM OtherFeed WHERE BabyID = ? ORDER BY Time DESC LIMIT 1", (baby_id,))
            other_row = cursor.fetchone()
            if other_row and other_row[0] > most_recent_time:
                most_recent_time = other_row[0]
                most_recent = {"time": self._format_timestamp(other_row[0]), "raw_time": other_row[0], "type": "Supplement"}

            return most_recent
        finally:
            conn.close()

    def get_last_bath_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the last bath by querying the Bath table directly.
        This method does NOT rely on the Progress table.

        :param baby_id: Optional baby ID
        :return: Dictionary with last bath info or None
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None

                if baby_id is None:
                    return None

            # Query Bath table directly with optional bath description
            cursor.execute("""
                SELECT b.ID, b.Time, b.Note, b.DescID, bd.Name as DescName
                FROM Bath b
                LEFT JOIN BathDesc bd ON b.DescID = bd.ID
                WHERE b.BabyID = ?
                ORDER BY b.Time DESC
                LIMIT 1
            """, (baby_id,))

            row = cursor.fetchone()

            if row:
                return {
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "note": row[2] if row[2] else "",
                    "desc_id": row[3],
                    "bath_type": row[4] if row[4] else "Bath"  # Default to "Bath" if no description
                }
            return None
        finally:
            conn.close()

    def get_bath_records(self, limit=50, baby_id: Optional[str] = None) -> List[Dict]:
        """
        Get bath records for a baby.

        :param limit: Maximum number of records to return
        :param baby_id: Optional baby ID
        :return: List of dictionaries with bath details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None

                if baby_id is None:
                    return []

            # Query Bath table with bath descriptions
            cursor.execute(f"""
                SELECT b.ID, b.Time, b.Note, b.HasPicture, b.DescID, bd.Name as DescName
                FROM Bath b
                LEFT JOIN BathDesc bd ON b.DescID = bd.ID
                WHERE b.BabyID = ?
                ORDER BY b.Time DESC
                LIMIT {limit}
            """, (baby_id,))

            records = []
            for row in cursor.fetchall():
                records.append({
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "note": row[2] if row[2] else "",
                    "has_picture": bool(row[3]),
                    "desc_id": row[4],
                    "bath_type": row[5] if row[5] else "Bath"
                })

            return records
        finally:
            conn.close()

    def log_bath(self, baby_id: Optional[str] = None, bath_type: Optional[str] = None,
                 note: str = "", time: Optional[datetime] = None) -> bool:
        """
        Log a new bath record.

        :param baby_id: Optional baby ID (uses first baby if not provided)
        :param bath_type: Optional bath type name (e.g., "Bubble Bath", "Sponge Bath")
        :param note: Optional note
        :param time: Optional time (defaults to now)
        :return: True if successful, False otherwise
        """
        import uuid

        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None

                if baby_id is None:
                    _LOGGER.error("No baby found in database")
                    return False

            # Get bath description ID if bath_type is provided
            desc_id = None
            if bath_type:
                cursor.execute("SELECT ID FROM BathDesc WHERE Name = ?", (bath_type,))
                desc_row = cursor.fetchone()
                if desc_row:
                    desc_id = desc_row[0]

            # Use provided time or current time
            if time is None:
                time = datetime.now(timezone.utc)

            bath_time = time.timestamp()
            timestamp = datetime.now(timezone.utc).timestamp()

            # Insert bath record
            cursor.execute("""
                INSERT INTO Bath (
                    ID, Timestamp, Time, Note, HasPicture, BabyID, DescID
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),  # Generate new ID
                timestamp,
                bath_time,
                note,
                0,  # HasPicture
                baby_id,
                desc_id
            ))

            conn.commit()
            _LOGGER.info(f"Logged bath: type={bath_type}, time={time}, note={note}")
            return True

        except Exception as e:
            _LOGGER.error(f"Error logging bath: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_bath_types(self) -> List[str]:
        """
        Get list of available bath types/descriptions.

        :return: List of bath type names
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT Name FROM BathDesc ORDER BY Name")
            return [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

    # ===== PUMP SESSION TRACKING =====

    def get_last_pump_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the last pump session by querying the Pump table directly.

        :param baby_id: Optional baby ID
        :return: Dictionary with last pump session info or None
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None
                if baby_id is None:
                    return None

            # Query Pump table - note: no BabyID column in Pump table!
            # The app links pumping to baby through the Pumped table via PumpedID
            cursor.execute("""
                SELECT ID, Time, LeftDuration, RightDuration, LeftAmount, RightAmount,
                       Amount, IsEnglishScale, Note, FinishSide, Sides
                FROM Pump
                ORDER BY Time DESC
                LIMIT 1
            """)

            row = cursor.fetchone()
            if row:
                left_duration = row[2] or 0
                right_duration = row[3] or 0
                total_duration = left_duration + right_duration

                return {
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "left_duration": left_duration,
                    "right_duration": right_duration,
                    "total_duration": total_duration,
                    "left_amount": row[4] or 0,
                    "right_amount": row[5] or 0,
                    "total_amount": row[6] or 0,
                    "is_english_scale": bool(row[7]),
                    "unit": "oz" if row[7] else "ml",
                    "note": row[8] if row[8] else "",
                    "finish_side": row[9],  # 0=Right, 1=Left, 2=Both
                    "sides": row[10]  # Which sides were pumped
                }
            return None
        finally:
            conn.close()

    def get_pump_records(self, limit=50, baby_id: Optional[str] = None) -> List[Dict]:
        """
        Get pump session records.

        :param limit: Maximum number of records to return
        :param baby_id: Optional baby ID (currently not used as Pump table has no BabyID)
        :return: List of dictionaries with pump session details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute(f"""
                SELECT ID, Time, LeftDuration, RightDuration, LeftAmount, RightAmount,
                       Amount, IsEnglishScale, Note, FinishSide, Sides
                FROM Pump
                ORDER BY Time DESC
                LIMIT {limit}
            """)

            records = []
            for row in cursor.fetchall():
                left_duration = row[2] or 0
                right_duration = row[3] or 0
                total_duration = left_duration + right_duration

                records.append({
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "left_duration": left_duration,
                    "right_duration": right_duration,
                    "total_duration": total_duration,
                    "left_amount": row[4] or 0,
                    "right_amount": row[5] or 0,
                    "total_amount": row[6] or 0,
                    "is_english_scale": bool(row[7]),
                    "unit": "oz" if row[7] else "ml",
                    "note": row[8] if row[8] else "",
                    "finish_side": row[9],
                    "sides": row[10]
                })

            return records
        finally:
            conn.close()

    def log_pump(self, baby_id: Optional[str] = None, left_duration: int = 0,
                 right_duration: int = 0, left_amount: float = 0, right_amount: float = 0,
                 is_english_scale: bool = False, note: str = "",
                 time: Optional[datetime] = None) -> bool:
        """
        Log a new pump session.

        :param baby_id: Optional baby ID (for future multi-baby support)
        :param left_duration: Duration on left side (minutes)
        :param right_duration: Duration on right side (minutes)
        :param left_amount: Amount from left side (ml or oz)
        :param right_amount: Amount from right side (ml or oz)
        :param is_english_scale: True if amounts are in oz, False for ml
        :param note: Optional note
        :param time: Optional time (defaults to now)
        :return: True if successful, False otherwise
        """
        import uuid

        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Use provided time or current time
            if time is None:
                time = datetime.now(timezone.utc)

            pump_time = time.timestamp()
            timestamp = datetime.now(timezone.utc).timestamp()

            # Calculate totals
            total_amount = left_amount + right_amount
            total_duration = left_duration + right_duration

            # Determine finish side
            if left_duration > 0 and right_duration == 0:
                finish_side = 1  # Left
            elif right_duration > 0 and left_duration == 0:
                finish_side = 0  # Right
            else:
                finish_side = 2  # Both

            # Determine sides (bitmask: 1=Right, 2=Left, 3=Both)
            if left_duration > 0 and right_duration > 0:
                sides = 3  # Both
            elif left_duration > 0:
                sides = 2  # Left only
            elif right_duration > 0:
                sides = 1  # Right only
            else:
                sides = 0  # None

            # Insert pump record
            cursor.execute("""
                INSERT INTO Pump (
                    ID, Timestamp, Time, LeftDuration, RightDuration,
                    LeftAmount, RightAmount, Amount, IsEnglishScale,
                    Note, FinishSide, Sides, HasPicture, Label, PumpedID
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(uuid.uuid4()),
                timestamp,
                pump_time,
                left_duration,
                right_duration,
                left_amount,
                right_amount,
                total_amount,
                1 if is_english_scale else 0,
                note,
                finish_side,
                sides,
                0,  # HasPicture
                "",  # Label
                None  # PumpedID (link to stored milk if needed)
            ))

            conn.commit()
            unit = "oz" if is_english_scale else "ml"
            _LOGGER.info(f"Logged pump session: {total_amount}{unit} in {total_duration} minutes")
            return True

        except Exception as e:
            _LOGGER.error(f"Error logging pump session: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_pump_summary(self, days: int = 7, baby_id: Optional[str] = None) -> Dict:
        """
        Get pump session summary statistics.

        :param days: Number of days to include in summary
        :param baby_id: Optional baby ID
        :return: Dictionary with pump statistics
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        # Get cutoff time
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_timestamp = cutoff_time.timestamp()

        records = self.get_pump_records(limit=500, baby_id=baby_id)

        # Filter to time range
        recent_records = [r for r in records if r["raw_time"] >= cutoff_timestamp]

        if not recent_records:
            return {
                "total_sessions": 0,
                "total_amount": 0,
                "total_duration": 0,
                "avg_amount_per_session": 0,
                "avg_duration_per_session": 0,
                "sessions_per_day": 0
            }

        total_sessions = len(recent_records)
        total_amount = sum(r["total_amount"] for r in recent_records)
        total_duration = sum(r["total_duration"] for r in recent_records)

        # Check unit from most recent record
        unit = recent_records[0]["unit"]

        return {
            "total_sessions": total_sessions,
            "total_amount": round(total_amount, 1),
            "total_duration": total_duration,
            "avg_amount_per_session": round(total_amount / total_sessions, 1) if total_sessions > 0 else 0,
            "avg_duration_per_session": round(total_duration / total_sessions, 1) if total_sessions > 0 else 0,
            "sessions_per_day": round(total_sessions / days, 1),
            "unit": unit,
            "days": days
        }

    def get_last_growth_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the most recent growth measurement by querying the Growth table directly.

        :param baby_id: Optional baby ID to filter by
        :return: Dictionary with growth details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Build query
            query = """
                SELECT ID, Time, Weight, Length, Head,
                       IsEnglishWeightScale, IsEnglishLengthScale, Note
                FROM Growth
                ORDER BY Time DESC
                LIMIT 1
            """

            cursor.execute(query)
            row = cursor.fetchone()

            if not row:
                return None

            # Parse data
            time_val = row[1]
            weight = row[2] or 0
            length = row[3] or 0
            head = row[4] or 0
            is_english_weight = bool(row[5])
            is_english_length = bool(row[6])
            note = row[7] or ""

            return {
                "id": row[0],
                "time": self._format_timestamp(time_val),
                "raw_time": time_val,
                "weight": weight,
                "length": length,
                "head": head,
                "weight_unit": "lbs" if is_english_weight else "kg",
                "length_unit": "in" if is_english_length else "cm",
                "is_english_weight": is_english_weight,
                "is_english_length": is_english_length,
                "note": note
            }
        finally:
            conn.close()

    def get_growth_records(self, limit: int = 50, baby_id: Optional[str] = None) -> List[Dict]:
        """
        Get growth measurement records.

        :param limit: Maximum number of records to return
        :param baby_id: Optional baby ID to filter by
        :return: List of dictionaries with growth details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Build query
            query = f"""
                SELECT ID, Time, Weight, Length, Head,
                       IsEnglishWeightScale, IsEnglishLengthScale, Note
                FROM Growth
                ORDER BY Time DESC
                LIMIT {limit}
            """

            cursor.execute(query)
            records = []

            for row in cursor.fetchall():
                time_val = row[1]
                weight = row[2] or 0
                length = row[3] or 0
                head = row[4] or 0
                is_english_weight = bool(row[5])
                is_english_length = bool(row[6])
                note = row[7] or ""

                records.append({
                    "id": row[0],
                    "time": self._format_timestamp(time_val),
                    "raw_time": time_val,
                    "weight": weight,
                    "length": length,
                    "head": head,
                    "weight_unit": "lbs" if is_english_weight else "kg",
                    "length_unit": "in" if is_english_length else "cm",
                    "is_english_weight": is_english_weight,
                    "is_english_length": is_english_length,
                    "note": note
                })

            return records
        finally:
            conn.close()

    def log_growth(self, baby_id: str, weight: float, length: float, head: float,
                   is_english_weight_scale: bool, is_english_length_scale: bool,
                   note: str = "", time: Optional[float] = None) -> bool:
        """
        Log a new growth measurement record.

        :param baby_id: Baby ID
        :param weight: Weight measurement
        :param length: Length/height measurement
        :param head: Head circumference measurement
        :param is_english_weight_scale: True for lbs, False for kg
        :param is_english_length_scale: True for inches, False for cm
        :param note: Optional note
        :param time: Optional time (defaults to now)
        :return: True if successful
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        import uuid

        if time is None:
            time = datetime.now(timezone.utc).timestamp()

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Generate new ID
            record_id = str(uuid.uuid4()).upper()

            # Insert growth record
            cursor.execute("""
                INSERT INTO Growth (
                    ID, Timestamp, Time, Note, HasPicture, BabyID,
                    Weight, Length, Head, IsEnglishWeightScale, IsEnglishLengthScale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record_id,
                time,  # Timestamp
                time,  # Time
                note,
                0,  # HasPicture
                baby_id,
                weight,
                length,
                head,
                1 if is_english_weight_scale else 0,
                1 if is_english_length_scale else 0
            ))

            conn.commit()
            return True
        except Exception as e:
            print(f"Error logging growth: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # ===== MILESTONE TRACKING =====

    def get_last_milestone_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the most recent milestone by querying the Milestone table directly.

        :param baby_id: Optional baby ID to filter by
        :return: Dictionary with milestone details or None
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None
                if baby_id is None:
                    return None

            # Query Milestone table with baby filter
            cursor.execute("""
                SELECT m.ID, m.Time, m.Note, m.MilestoneSelectionID, ms.Name, ms.Description
                FROM Milestone m
                LEFT JOIN MilestoneSelection ms ON m.MilestoneSelectionID = ms.ID
                WHERE m.BabyID = ?
                ORDER BY m.Time DESC
                LIMIT 1
            """, (baby_id,))

            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "note": row[2] if row[2] else "",
                    "milestone_selection_id": row[3],
                    "milestone_name": row[4] if row[4] else "Unknown",
                    "milestone_description": row[5] if row[5] else ""
                }
            return None
        finally:
            conn.close()

    def get_milestone_records(self, limit: int = 50, baby_id: Optional[str] = None) -> List[Dict]:
        """
        Get milestone records.

        :param limit: Maximum number of records to return
        :param baby_id: Optional baby ID to filter by
        :return: List of dictionaries with milestone details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None
                if baby_id is None:
                    return []

            # Query with baby filter
            cursor.execute(f"""
                SELECT m.ID, m.Time, m.Note, m.MilestoneSelectionID, ms.Name, ms.Description
                FROM Milestone m
                LEFT JOIN MilestoneSelection ms ON m.MilestoneSelectionID = ms.ID
                WHERE m.BabyID = ?
                ORDER BY m.Time DESC
                LIMIT {limit}
            """, (baby_id,))

            records = []
            for row in cursor.fetchall():
                records.append({
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "note": row[2] if row[2] else "",
                    "milestone_selection_id": row[3],
                    "milestone_name": row[4] if row[4] else "Unknown",
                    "milestone_description": row[5] if row[5] else ""
                })
            return records
        finally:
            conn.close()

    def get_milestone_selections(self) -> List[Dict]:
        """
        Get available milestone selections.

        :return: List of dictionaries with milestone selection details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT ID, Name, Description, ForAge
                FROM MilestoneSelection
                WHERE BabyID IS NULL OR BabyID = ''
                ORDER BY ForAge ASC, Name ASC
            """)

            selections = []
            for row in cursor.fetchall():
                selections.append({
                    "id": row[0],
                    "name": row[1],
                    "description": row[2] if row[2] else "",
                    "for_age": row[3] or 0
                })
            return selections
        finally:
            conn.close()

    def log_milestone(
        self,
        baby_id: str,
        milestone_selection_id: str,
        note: str = "",
        time: Optional[float] = None
    ) -> bool:
        """
        Log a milestone achievement to the database.

        :param baby_id: Baby ID
        :param milestone_selection_id: Milestone selection ID
        :param note: Optional note
        :param time: Optional timestamp (defaults to current time)
        :return: True if successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        import uuid

        if time is None:
            time = datetime.now(timezone.utc).timestamp()

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Generate new ID
            record_id = str(uuid.uuid4()).upper()

            # Insert milestone record
            cursor.execute("""
                INSERT INTO Milestone (
                    ID, Timestamp, Time, Note, HasPicture, BabyID, MilestoneSelectionID
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                record_id,
                time,  # Timestamp
                time,  # Time
                note,
                0,  # HasPicture
                baby_id,
                milestone_selection_id
            ))

            conn.commit()
            return True
        except Exception as e:
            print(f"Error logging milestone: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # ===== DOCTOR VISIT TRACKING =====

    def get_last_doctor_visit_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the most recent doctor visit by querying the DoctorVisit table directly.

        :param baby_id: Optional baby ID to filter by
        :return: Dictionary with doctor visit details or None
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None
                if baby_id is None:
                    return None

            # Query DoctorVisit table with baby filter
            cursor.execute("""
                SELECT ID, Time, Note, IsAppointment, VisitType, DoctorNote, Symptom
                FROM DoctorVisit
                WHERE BabyID = ?
                ORDER BY Time DESC
                LIMIT 1
            """, (baby_id,))

            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "note": row[2] if row[2] else "",
                    "is_appointment": bool(row[3]),
                    "visit_type": row[4] or 0,
                    "doctor_note": row[5] if row[5] else "",
                    "symptom": row[6] if row[6] else ""
                }
            return None
        finally:
            conn.close()

    def get_doctor_visit_records(self, limit: int = 50, baby_id: Optional[str] = None) -> List[Dict]:
        """
        Get doctor visit records.

        :param limit: Maximum number of records to return
        :param baby_id: Optional baby ID to filter by
        :return: List of dictionaries with doctor visit details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None
                if baby_id is None:
                    return []

            # Query with baby filter
            cursor.execute(f"""
                SELECT ID, Time, Note, IsAppointment, VisitType, DoctorNote, Symptom
                FROM DoctorVisit
                WHERE BabyID = ?
                ORDER BY Time DESC
                LIMIT {limit}
            """, (baby_id,))

            records = []
            for row in cursor.fetchall():
                records.append({
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "note": row[2] if row[2] else "",
                    "is_appointment": bool(row[3]),
                    "visit_type": row[4] or 0,
                    "doctor_note": row[5] if row[5] else "",
                    "symptom": row[6] if row[6] else ""
                })
            return records
        finally:
            conn.close()

    def log_doctor_visit(
        self,
        baby_id: str,
        is_appointment: bool = True,
        visit_type: int = 0,
        note: str = "",
        doctor_note: str = "",
        symptom: str = "",
        time: Optional[float] = None
    ) -> bool:
        """
        Log a doctor visit to the database.

        :param baby_id: Baby ID
        :param is_appointment: Whether this is a scheduled appointment
        :param visit_type: Type of visit (0=General, etc.)
        :param note: Optional note
        :param doctor_note: Doctor's notes
        :param symptom: Symptoms noted during visit
        :param time: Optional timestamp (defaults to current time)
        :return: True if successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        import uuid

        if time is None:
            time = datetime.now(timezone.utc).timestamp()

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Generate new ID
            record_id = str(uuid.uuid4()).upper()

            # Insert doctor visit record
            cursor.execute("""
                INSERT INTO DoctorVisit (
                    ID, Timestamp, Time, Note, HasPicture, BabyID,
                    IsAppointment, VisitType, DoctorNote, Symptom
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record_id,
                time,  # Timestamp
                time,  # Time
                note,
                0,  # HasPicture
                baby_id,
                1 if is_appointment else 0,
                visit_type,
                doctor_note,
                symptom
            ))

            conn.commit()
            return True
        except Exception as e:
            print(f"Error logging doctor visit: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # ===== VACCINE TRACKING =====

    def get_last_vaccine_direct(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Get the most recent vaccine by querying the Vaccine table directly.

        :param baby_id: Optional baby ID to filter by
        :return: Dictionary with vaccine details or None
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None
                if baby_id is None:
                    return None

            # Query Vaccine table with baby filter
            cursor.execute("""
                SELECT v.ID, v.Time, v.Note, v.VaccID, vs.Name, vs.Description
                FROM Vaccine v
                LEFT JOIN VaccineSelection vs ON v.VaccID = vs.ID
                WHERE v.BabyID = ?
                ORDER BY v.Time DESC
                LIMIT 1
            """, (baby_id,))

            row = cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "note": row[2] if row[2] else "",
                    "vacc_id": row[3],
                    "vaccine_name": row[4] if row[4] else "Unknown",
                    "vaccine_description": row[5] if row[5] else ""
                }
            return None
        finally:
            conn.close()

    def get_vaccine_records(self, limit: int = 50, baby_id: Optional[str] = None) -> List[Dict]:
        """
        Get vaccine records.

        :param limit: Maximum number of records to return
        :param baby_id: Optional baby ID to filter by
        :return: List of dictionaries with vaccine details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None
                if baby_id is None:
                    return []

            # Query with baby filter
            cursor.execute(f"""
                SELECT v.ID, v.Time, v.Note, v.VaccID, vs.Name, vs.Description
                FROM Vaccine v
                LEFT JOIN VaccineSelection vs ON v.VaccID = vs.ID
                WHERE v.BabyID = ?
                ORDER BY v.Time DESC
                LIMIT {limit}
            """, (baby_id,))

            records = []
            for row in cursor.fetchall():
                records.append({
                    "id": row[0],
                    "time": self._format_timestamp(row[1]) if row[1] else None,
                    "raw_time": row[1],
                    "note": row[2] if row[2] else "",
                    "vacc_id": row[3],
                    "vaccine_name": row[4] if row[4] else "Unknown",
                    "vaccine_description": row[5] if row[5] else ""
                })
            return records
        finally:
            conn.close()

    def get_vaccine_selections(self) -> List[Dict]:
        """
        Get available vaccine selections.

        :return: List of dictionaries with vaccine selection details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT ID, Name, Description, ForAge
                FROM VaccineSelection
                ORDER BY ForAge ASC, Name ASC
            """)

            selections = []
            for row in cursor.fetchall():
                selections.append({
                    "id": row[0],
                    "name": row[1],
                    "description": row[2] if row[2] else "",
                    "for_age": row[3] or 0
                })
            return selections
        finally:
            conn.close()

    def log_vaccine(
        self,
        baby_id: str,
        vacc_id: str,
        note: str = "",
        doc_visit_id: str = "",
        time: Optional[float] = None
    ) -> bool:
        """
        Log a vaccine administration to the database.

        :param baby_id: Baby ID
        :param vacc_id: Vaccine selection ID
        :param note: Optional note
        :param doc_visit_id: Optional doctor visit ID to link to
        :param time: Optional timestamp (defaults to current time)
        :return: True if successful, False otherwise
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        import uuid

        if time is None:
            time = datetime.now(timezone.utc).timestamp()

        # Generate empty doctor visit ID if not provided
        if not doc_visit_id:
            doc_visit_id = ""

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Generate new ID
            record_id = str(uuid.uuid4()).upper()

            # Insert vaccine record
            cursor.execute("""
                INSERT INTO Vaccine (
                    ID, Timestamp, Time, Note, HasPicture, BabyID, VaccID, DocVisitID
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record_id,
                time,  # Timestamp
                time,  # Time
                note,
                0,  # HasPicture
                baby_id,
                vacc_id,
                doc_visit_id
            ))

            conn.commit()
            return True
        except Exception as e:
            print(f"Error logging vaccine: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # Example usage
def main():
    # Initialize the database from a seed file
    try:
        # Replace with the path to your seed file
        db = BabyTrackerLocalDatabase('path/to/seed.zip')

        # Get baby info
        baby_info = db.get_baby_info()
        print("Baby Info:", baby_info)

        # Get last feeding
        last_feeding = db.get_last_feeding()
        print("Last Feeding:", last_feeding)

        # Get feedings from the last day
        recent_feedings = db.get_feedings(days_back=1)
        print("Recent Feedings:", recent_feedings)

        # Get last diaper change
        last_diaper = db.get_last_diaper()
        print("Last Diaper:", last_diaper)

        # Get diapers from the last day
        recent_diapers = db.get_diapers(days_back=1)
        print("Recent Diapers:", recent_diapers)

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    main()