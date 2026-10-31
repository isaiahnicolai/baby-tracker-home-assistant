#database.py
from .models import Baby
from . import records
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
    def __init__(self, db_path=None, db_filename='babytracker.db', tz=None):
        """
        Initialize the local database

        :param db_path: Path to the database file
        :param db_filename: Name of the database file (defaults to 'babytracker.db')
        :param tz: tzinfo that "today", day buckets and night hours are worked out in
            (defaults to the system's local zone)
        """
        self.tz = tz  # None: the system's local zone, looked up at use so DST changes are followed
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

    def _now(self) -> datetime:
        """The current time in the configured zone."""
        return datetime.now(self.tz) if self.tz else datetime.now().astimezone()

    def _local(self, timestamp: float) -> datetime:
        """A UTC timestamp as a datetime in the configured zone."""
        if self.tz:
            return datetime.fromtimestamp(timestamp, self.tz)
        return datetime.fromtimestamp(timestamp).astimezone()

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

    def get_feedings(self, limit=50, baby_id: Optional[str] = None) -> List[Dict]:
        """
        Retrieve all feeding records (nursing, formula, pumped milk, supplements)

        :param limit: Maximum number of records to return
        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :return: List of dictionaries with feeding details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
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
                    "raw_time": row[2],
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
                    "raw_time": row[2],
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
                    "raw_time": row[2],
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
                    "raw_time": row[2],
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

            # Sort all feedings by raw timestamp (descending) for correct ordering
            feedings.sort(key=lambda x: x.get("raw_time", 0) or 0, reverse=True)

            return feedings[:limit]
        finally:
            conn.close()

    def get_last_feeding(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Retrieve the most recent feeding from any feeding type

        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :return: Dictionary with feeding details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        feedings = self.get_feedings(limit=1, baby_id=baby_id)
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
        end_date = self._now()
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
        end_date = self._now()
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
                SELECT CASE WHEN Status = 0 AND Amount = 0 THEN 3 ELSE Status END AS DisplayStatus, COUNT(ID)
                FROM Diaper
                WHERE BabyID = ? AND Time >= ? AND Time <= ?
                GROUP BY DisplayStatus
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
                WHERE BabyID = ? AND Time >= ? AND Time <= ? AND (Status = 0 OR Status = 2) AND NOT (Status = 0 AND Amount = 0)
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
                now_timestamp = self._now().timestamp()
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

    def get_today_wet_diaper_count(self, baby_id: Optional[str] = None) -> int:
        """
        Get the count of wet diapers (Status 0=wet or 2=mixed) for today.

        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :return: Integer count of wet diapers today
        """
        if not os.path.exists(self.db_path):
            return 0

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            if not baby_id:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_id_row = cursor.fetchone()
                baby_id = baby_id_row[0] if baby_id_row else None
            if not baby_id:
                return 0

            today_start = int(self._now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

            cursor.execute("""
                SELECT COUNT(ID) FROM Diaper
                WHERE BabyID = ? AND Time >= ? AND Status IN (0, 2) AND NOT (Status = 0 AND Amount = 0)
            """, (baby_id, today_start))
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def get_daily_summary(self, baby_id: Optional[str] = None) -> Dict:
        """
        Get today's totals for all tracked activities.

        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :return: Dictionary with today's totals
        """
        if not os.path.exists(self.db_path):
            return {}

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            if not baby_id:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_id_row = cursor.fetchone()
                baby_id = baby_id_row[0] if baby_id_row else None
            if not baby_id:
                return {}

            today_start = int(self._now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())

            summary = {
                "total_feedings": 0,
                "formula_oz": 0,
                "nursing_minutes": 0,
                "diaper_count": 0,
                "sleep_hours": 0,
            }

            # Formula count and total oz
            cursor.execute("""
                SELECT COUNT(ID),
                       SUM(CASE WHEN IsEnglishScale=1 THEN Amount ELSE Amount/29.5735 END)
                FROM Formula
                WHERE BabyID = ? AND Time >= ?
            """, (baby_id, today_start))
            row = cursor.fetchone()
            formula_count = row[0] or 0
            summary["formula_oz"] = round(row[1] or 0, 1)
            summary["total_feedings"] += formula_count

            # Nursing count and total minutes
            cursor.execute("""
                SELECT COUNT(ID),
                       SUM(COALESCE(LeftDuration,0) + COALESCE(RightDuration,0) + COALESCE(BothDuration,0))
                FROM Nursing
                WHERE BabyID = ? AND Time >= ?
            """, (baby_id, today_start))
            row = cursor.fetchone()
            nursing_count = row[0] or 0
            summary["nursing_minutes"] = row[1] or 0
            summary["total_feedings"] += nursing_count

            # Pumped count
            cursor.execute("""
                SELECT COUNT(ID) FROM Pumped
                WHERE BabyID = ? AND Time >= ?
            """, (baby_id, today_start))
            row = cursor.fetchone()
            summary["total_feedings"] += row[0] or 0

            # OtherFeed count
            cursor.execute("""
                SELECT name FROM sqlite_master WHERE type='table' AND name='OtherFeed'
            """)
            if cursor.fetchone():
                cursor.execute("""
                    SELECT COUNT(ID) FROM OtherFeed
                    WHERE BabyID = ? AND Time >= ?
                """, (baby_id, today_start))
                row = cursor.fetchone()
                summary["total_feedings"] += row[0] or 0

            # Diaper count
            cursor.execute("""
                SELECT COUNT(ID) FROM Diaper
                WHERE BabyID = ? AND Time >= ?
            """, (baby_id, today_start))
            row = cursor.fetchone()
            summary["diaper_count"] = row[0] or 0

            # Sleep hours (completed sleeps only, Duration > 0, in minutes)
            cursor.execute("""
                SELECT SUM(Duration) FROM Sleep
                WHERE BabyID = ? AND Time >= ? AND Duration > 0
            """, (baby_id, today_start))
            row = cursor.fetchone()
            total_sleep_minutes = row[0] or 0
            summary["sleep_hours"] = round(total_sleep_minutes / 60.0, 1)

            return summary
        finally:
            conn.close()

    def get_sleep_analysis(self, baby_id: Optional[str] = None, days: int = 14) -> Dict:
        """
        Analyze sleep patterns over the last N days for bedtime/wake graphing.

        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :param days: Number of days to analyze
        :return: Dictionary with average bedtime, wake time, per-day data
        """
        if not os.path.exists(self.db_path):
            return {}

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            if not baby_id:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_id_row = cursor.fetchone()
                baby_id = baby_id_row[0] if baby_id_row else None
            if not baby_id:
                return {}

            cutoff = int((self._now() - timedelta(days=days)).timestamp())

            cursor.execute("""
                SELECT Time, Duration FROM Sleep
                WHERE BabyID = ? AND Time >= ? AND Duration > 0
                ORDER BY Time ASC
            """, (baby_id, cutoff))

            rows = cursor.fetchall()

            if not rows:
                return {
                    "avg_bedtime": "N/A",
                    "avg_bedtime_minutes": None,
                    "avg_wake_time": "N/A",
                    "avg_wake_time_minutes": None,
                    "avg_sleep_duration_hours": None,
                    "days_analyzed": 0,
                    "per_day": [],
                }

            # Classify night sleeps: start hour between 6pm (18) and midnight (0-5)
            night_sleeps = []
            for start_ts, duration_minutes in rows:
                start_dt = self._local(start_ts)
                start_hour = start_dt.hour

                # Night sleep: started at or after 6pm, local time
                is_night = start_hour >= 18

                if not is_night:
                    continue

                end_ts = start_ts + duration_minutes * 60
                end_dt = self._local(end_ts)

                # Normalize bedtime hour for averaging:
                # Hours before 6am treated as 24+hour to avoid midnight crossing issues
                bed_hour = start_dt.hour + start_dt.minute / 60.0

                wake_hour = end_dt.hour + end_dt.minute / 60.0
                # If wake is before 6am next day, it's early morning
                # No normalization needed for wake since we expect 4am-10am range

                duration_hours = duration_minutes / 60.0

                date_str = start_dt.strftime("%Y-%m-%d")

                night_sleeps.append({
                    "date": date_str,
                    "bedtime_hour": bed_hour,
                    "wake_hour": wake_hour,
                    "duration_hours": round(duration_hours, 2),
                    "bedtime_dt": start_dt,
                    "wake_dt": end_dt,
                })

            if not night_sleeps:
                return {
                    "avg_bedtime": "N/A",
                    "avg_bedtime_minutes": None,
                    "avg_wake_time": "N/A",
                    "avg_wake_time_minutes": None,
                    "avg_sleep_duration_hours": None,
                    "days_analyzed": 0,
                    "per_day": [],
                }

            # Compute averages
            total_bed = sum(s["bedtime_hour"] for s in night_sleeps)
            total_wake = sum(s["wake_hour"] for s in night_sleeps)
            total_dur = sum(s["duration_hours"] for s in night_sleeps)
            count = len(night_sleeps)

            avg_bed_hour = total_bed / count
            avg_wake_hour = total_wake / count
            avg_dur = round(total_dur / count, 1)

            # Convert average bed hour to minutes from midnight
            avg_bed_minutes = int(round(avg_bed_hour * 60))
            avg_wake_minutes = int(round(avg_wake_hour * 60))

            # Format times
            def format_time(hour_float):
                h = int(hour_float) % 24
                m = int(round((hour_float - int(hour_float)) * 60))
                if m == 60:
                    h += 1
                    m = 0
                h = h % 24
                period = "AM" if h < 12 else "PM"
                display_h = h % 12
                if display_h == 0:
                    display_h = 12
                return f"{display_h}:{m:02d} {period}"

            # Build per-day list
            per_day = []
            for s in night_sleeps:
                bed_min = int(round(s["bedtime_hour"] * 60))
                wake_min = int(round(s["wake_hour"] * 60))
                per_day.append({
                    "date": s["date"],
                    "bedtime": format_time(s["bedtime_hour"]),
                    "bedtime_minutes": bed_min,
                    "wake_time": format_time(s["wake_hour"]),
                    "wake_time_minutes": wake_min,
                    "duration_hours": s["duration_hours"],
                })

            return {
                "avg_bedtime": format_time(avg_bed_hour),
                "avg_bedtime_minutes": avg_bed_minutes,
                "avg_wake_time": format_time(avg_wake_hour),
                "avg_wake_time_minutes": avg_wake_minutes,
                "avg_sleep_duration_hours": avg_dur,
                "days_analyzed": count,
                "per_day": per_day,
            }
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
            query = ("SELECT Temp, Time, IsEnglishScale FROM Temperature "
                     "WHERE BabyID = ? ORDER BY Time DESC LIMIT 1")
            params = [baby_id]
            cursor.execute(query, params)

            temp_reading = cursor.fetchone()

            if temp_reading:
                value = temp_reading[0]
                # The app records each reading in the scale it was entered in
                english = temp_reading[2] is None or bool(temp_reading[2])
                if english:
                    fahrenheit, celsius = value, (value - 32) * 5 / 9
                else:
                    fahrenheit, celsius = value * 9 / 5 + 32, value
                return {
                    "temp": value,
                    "unit": "°F" if english else "°C",
                    "fahrenheit": round(fahrenheit, 2),
                    "celsius": round(celsius, 2),
                    "time": self._format_timestamp(temp_reading[1]) if temp_reading[1] else None
                }
            return None
        except Exception as e:
            _LOGGER.error(f"Error getting last temperature: {e}")
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
                    "status": self._get_diaper_status(row[2], row[3]),
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
    def _get_diaper_status(self, status_code: int, amount: int = None) -> str:
        """
        Convert diaper status code to human-readable string

        :param status_code: Status code from the database
        :param amount: DiaperAmount; the app stores dry as wet with amount 0 (None)
        :return: Diaper status description
        """
        if status_code == 0 and amount == 0:
            return "Dry"
        status_map = {
            0: "Wet",    # DiaperStatusWet
            1: "Poopy",  # DiaperStatusPoopy
            2: "Mixed",  # DiaperStatusMixed
            3: "Dry"     # DiaperStatusDry
        }
        return status_map.get(status_code, "Unknown")
    # Localised AM/PM markers the Android app accepts (DateTypeAdapter), in
    # its order; only the first match is replaced
    _AM_PM_TOKENS = [
        ("a.m.", "AM"), ("p.m.", "PM"), ("vorm.", "AM"), ("nachm.", "PM"),
        ("午前", "AM"), ("午後", "PM"), ("上午", "AM"), ("下午", "PM"),
        ("a. m.", "AM"), ("p. m.", "PM"), ("fm", "AM"), ("em", "PM"),
        ("오전", "AM"), ("오후", "PM"),
    ]

    def convert_timestamp(self, timestamp_str: str) -> float:
        """
        Convert an API date ("yyyy-MM-dd HH:mm:ss Z") to Unix seconds.

        Accepts the same fallbacks as the Android app's DateTypeAdapter
        (12-hour times with localised AM/PM markers). Raises ValueError for
        anything else rather than silently returning 1970.
        """
        if timestamp_str is None or timestamp_str == "":
            return 0.0
        if isinstance(timestamp_str, (int, float)):
            return float(timestamp_str)
        text = str(timestamp_str).strip().replace(" UTC", " +0000").replace(" GMT", " +0000")
        candidates = [text]
        for token, marker in self._AM_PM_TOKENS:
            if token in text:
                candidates.append(text.replace(token, marker, 1))
                break
        for candidate in candidates:
            for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %I:%M:%S %p %z"):
                try:
                    return datetime.strptime(candidate, fmt).timestamp()
                except ValueError:
                    continue
        raise ValueError(f"Unrecognised date: {timestamp_str!r}")
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
            _LOGGER.error(f"Error formatting timestamp {timestamp}: {e}")
            return None
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

    def get_activity_records(self, limit=50, baby_id: Optional[str] = None) -> List[Dict]:
        """
        Retrieve other activity records

        :param limit: Maximum number of records to return
        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :return: List of dictionaries with activity details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            if not baby_id:
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

    def get_last_activity(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Retrieve the most recent other activity

        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :return: Dictionary with activity details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        records = self.get_activity_records(limit=1, baby_id=baby_id)
        return records[0] if records else None

    def get_medicine_records(self, limit=50, baby_id: Optional[str] = None) -> List[Dict]:
        """
        Retrieve medicine administration records

        :param limit: Maximum number of records to return
        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :return: List of dictionaries with medicine details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()

            # Get baby ID if not provided
            if baby_id is None:
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

    def get_last_medicine(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Retrieve the most recent medicine administration

        :param baby_id: Optional baby ID to filter by (defaults to first baby)
        :return: Dictionary with medicine details
        """
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        records = self.get_medicine_records(limit=1, baby_id=baby_id)
        return records[0] if records else None
    # ===== MILESTONE TRANSACTION METHODS =====

    # ===== DOCTOR VISIT TRANSACTION METHODS =====

    # ===== VACCINE TRANSACTION METHODS =====

    # ===== GROWTH TRANSACTION METHODS =====

    # ===== BATH TRANSACTION METHODS =====

    # ===== OTHER FEED SELECTION TRANSACTION METHODS =====

    def time_since_last_feeding(self, baby_id: Optional[str] = None) -> Optional[Dict]:
        """
        Retrieve the time since the last feeding with precision for infant care

        :param baby_id: Optional baby ID to filter by
        :return: Dictionary with detailed feeding details, or None if no feedings
        """
        # Check if database exists
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")

        # Get current time in UTC
        now = datetime.now(timezone.utc)

        # Get the most recent feeding record
        feedings = self.get_feedings(limit=1, baby_id=baby_id)
        if not feedings:
            return None

        feeding = feedings[0]

        # Parse the feeding time correctly with timezone handling
        try:
            datetime_obj = parser.parse(feeding["time"])
        except Exception as e:
            _LOGGER.error(f"Error parsing feeding time: {e}")
            return None

        # Ensure datetime_obj is timezone-aware for comparison
        if datetime_obj.tzinfo is None:
            datetime_obj = datetime_obj.replace(tzinfo=timezone.utc)

        # Calculate the time difference
        time_diff = now - datetime_obj

        # Calculate hours and minutes for precision
        total_minutes = time_diff.total_seconds() / 60
        # Return float hours so sensor can calculate accurate minutes
        hours_float = total_minutes / 60
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
            "hours_since_last_feeding": hours_float,
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
                    "status": self._get_diaper_status(diaper_row[0], diaper_row[4]),
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
                    "status": self._get_diaper_status(row[2], row[6]),
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

            if not baby_id:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None
                if baby_id is None:
                    return None

            # Build query
            query = """
                SELECT ID, Time, Weight, Length, Head,
                       IsEnglishWeightScale, IsEnglishLengthScale, Note
                FROM Growth
                WHERE BabyID = ?
                ORDER BY Time DESC
                LIMIT 1
            """

            cursor.execute(query, (baby_id,))
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

            if not baby_id:
                cursor.execute("SELECT ID FROM Baby LIMIT 1")
                baby_row = cursor.fetchone()
                baby_id = baby_row[0] if baby_row else None
                if baby_id is None:
                    return []

            # Build query
            query = f"""
                SELECT ID, Time, Weight, Length, Head,
                       IsEnglishWeightScale, IsEnglishLengthScale, Note
                FROM Growth
                WHERE BabyID = ?
                ORDER BY Time DESC
                LIMIT {limit}
            """

            cursor.execute(query, (baby_id,))
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

    # Example usage

    # ===== SYNC SUPPORT =====
    # Generic helpers used by TransactionHandler and the upload queue. These
    # mirror BTDatabaseImple's merge/TransactionLog behaviour in the Android app.

    def _connect(self):
        if not os.path.exists(self.db_path):
            raise ValueError("No database loaded")
        return sqlite3.connect(self.db_path)

    def _table_exists(self, cursor, table):
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
        return cursor.fetchone() is not None

    def get_row_timestamp(self, table: str, object_id: str) -> Optional[float]:
        """Timestamp of an existing row, or None if the row (or table) doesn't exist."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            if not self._table_exists(cursor, table):
                return None
            cursor.execute(f'SELECT Timestamp FROM "{table}" WHERE ID = ?', (object_id,))
            row = cursor.fetchone()
            return None if row is None else float(row[0] or 0)
        finally:
            conn.close()

    def find_id_by_name(self, table: str, name: str) -> Optional[tuple]:
        """(ID, Timestamp) of the row with this Name, for UNIQUE(Name) clashes."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            if not self._table_exists(cursor, table):
                return None
            cursor.execute(f'SELECT ID, Timestamp FROM "{table}" WHERE Name = ?', (name,))
            row = cursor.fetchone()
            return None if row is None else (row[0], float(row[1] or 0))
        finally:
            conn.close()

    def is_referenced(self, usages, object_id: str) -> bool:
        """True if any (table, column) in usages refers to object_id."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            for table, column in usages:
                if not self._table_exists(cursor, table):
                    continue
                cursor.execute(f'SELECT 1 FROM "{table}" WHERE "{column}" = ? LIMIT 1', (object_id,))
                if cursor.fetchone():
                    return True
            return False
        finally:
            conn.close()

    def merge_references(self, table: str, usages, winner_id: str, loser_id: str) -> None:
        """Re-point every reference from loser to winner, then delete the loser row."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            for ref_table, column in usages:
                if self._table_exists(cursor, ref_table):
                    cursor.execute(
                        f'UPDATE "{ref_table}" SET "{column}" = ? WHERE "{column}" = ?',
                        (winner_id, loser_id),
                    )
            cursor.execute(f'DELETE FROM "{table}" WHERE ID = ?', (loser_id,))
            conn.commit()
        finally:
            conn.close()

    def upsert_record(self, object_type: str, record: Dict) -> bool:
        """
        Insert or replace a synced record using its records.RECORD_TYPES mapping.
        Nested selections it references (e.g. a medicine's selection) are stored
        too if missing, so lookups by name work. Raises on failure.
        """
        record_type = records.record_type(object_type)
        if record_type is None:
            raise ValueError(f"Unsupported record type: {object_type}")
        row = record_type.row(record, self.convert_timestamp)

        conn = self._connect()
        try:
            cursor = conn.cursor()
            for key, selection_type in record_type.embedded:
                nested = record.get(key)
                if isinstance(nested, dict) and nested.get("objectID") and nested.get("name"):
                    self._insert_row(cursor, records.record_type(selection_type).table,
                                     records.record_type(selection_type).row(nested, self.convert_timestamp),
                                     "INSERT OR IGNORE")
            self._insert_row(cursor, record_type.table, row, "INSERT OR REPLACE")
            conn.commit()
            return True
        finally:
            conn.close()

    def delete_record(self, object_type: str, object_id: str) -> bool:
        """Delete a synced record by ID. Raises on failure."""
        record_type = records.record_type(object_type)
        if record_type is None:
            raise ValueError(f"Unsupported record type: {object_type}")
        conn = self._connect()
        try:
            conn.execute(f'DELETE FROM "{record_type.table}" WHERE ID = ?', (object_id,))
            conn.commit()
            return True
        finally:
            conn.close()

    @staticmethod
    def _insert_row(cursor, table, row, verb):
        columns = ", ".join(f'"{c}"' for c in row)
        placeholders = ", ".join("?" for _ in row)
        cursor.execute(f'{verb} INTO "{table}" ({columns}) VALUES ({placeholders})', list(row.values()))

    def _ensure_sync_tables(self, cursor):
        # Same schema as the Android app (BTSQLiteOpenHelper)
        cursor.execute('CREATE TABLE IF NOT EXISTS "TransactionLog" '
                       '("ID" INTEGER PRIMARY KEY AUTOINCREMENT, "OpCode" INTEGER NOT NULL, "Log" BLOB NOT NULL)')
        cursor.execute('CREATE TABLE IF NOT EXISTS "ReliveList" ("ID" TEXT PRIMARY KEY NOT NULL UNIQUE)')

    def add_relive(self, object_id: str) -> None:
        conn = self._connect()
        try:
            cursor = conn.cursor()
            self._ensure_sync_tables(cursor)
            cursor.execute('INSERT OR IGNORE INTO ReliveList (ID) VALUES (?)', (object_id,))
            conn.commit()
        finally:
            conn.close()

    def pop_relive(self, object_id: str) -> bool:
        """Consume a pending relive for this ID; True if there was one."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            self._ensure_sync_tables(cursor)
            cursor.execute('DELETE FROM ReliveList WHERE ID = ?', (object_id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def enqueue_transaction(self, op_code: int, transaction_b64: str, min_sync_id: int = 0) -> int:
        """
        Queue a transaction for upload. Its row ID is the SyncID it is sent
        under, as in the Android app; the sequence is first raised past
        min_sync_id (the server's LastSyncID for this device) so IDs never go back.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            self._ensure_sync_tables(cursor)
            cursor.execute("SELECT seq FROM sqlite_sequence WHERE name = 'TransactionLog'")
            row = cursor.fetchone()
            if row is None:
                cursor.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('TransactionLog', ?)", (min_sync_id,))
            elif row[0] < min_sync_id:
                cursor.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'TransactionLog'", (min_sync_id,))
            cursor.execute('INSERT INTO TransactionLog (OpCode, Log) VALUES (?, ?)', (op_code, transaction_b64))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def get_pending_transactions(self) -> List[tuple]:
        """Queued uploads as (SyncID, OpCode, Transaction), oldest first."""
        conn = self._connect()
        try:
            cursor = conn.cursor()
            self._ensure_sync_tables(cursor)
            cursor.execute('SELECT ID, OpCode, Log FROM TransactionLog ORDER BY ID')
            return [(r[0], r[1], r[2].decode() if isinstance(r[2], bytes) else r[2]) for r in cursor.fetchall()]
        finally:
            conn.close()

    def delete_pending_transaction(self, sync_id: int) -> None:
        conn = self._connect()
        try:
            conn.execute('DELETE FROM TransactionLog WHERE ID = ?', (sync_id,))
            conn.commit()
        finally:
            conn.close()

    def clear_sync_state(self) -> None:
        """
        Drop queued uploads and relives inherited from a seed database
        (BTDatabaseImple.deleteAllTransactionLogImple), so another device's
        pending work is never uploaded as ours.
        """
        conn = self._connect()
        try:
            cursor = conn.cursor()
            self._ensure_sync_tables(cursor)
            cursor.execute('DELETE FROM TransactionLog')
            cursor.execute('DELETE FROM ReliveList')
            conn.commit()
        finally:
            conn.close()

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