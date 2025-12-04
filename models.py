#models.py

from datetime import datetime, timezone
from typing import Optional, Dict, Any
import uuid
import base64
import json 
import logging


class BaseModel:
    """Base class for all Baby Tracker models"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.object_id: str = None
        self.timestamp: str = None
        self.object_type: str = None
        
        if data:
            self.from_dict(data)
        else:
            # Generate a new UUID if not provided
            self.object_id = str(uuid.uuid4())
            # Set the current timestamp
            self.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load data from a dictionary"""
        self.object_id = data.get("objectID", str(uuid.uuid4()))
        self.timestamp = data.get("timestamp", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000"))
        self.object_type = data.get("BCObjectType", self.__class__.__name__)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model to a dictionary"""
        return {
            "objectID": self.object_id,
            "timestamp": self.timestamp,
            "BCObjectType": self.object_type,
            "newFlage": True  # This seems to be common in your code
        }
    
    def __str__(self) -> str:
        """String representation of the model"""
        return f"{self.object_type}(id={self.object_id})"
class Baby(BaseModel):
    """Model representing a baby"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.name: str = None
        self.dob: str = None  # Date of birth
        self.due_day: str = None
        self.gender: bool = False  # False for female, True for male
        self.picture_name: str = None
        
        super().__init__(data)
        self.object_type = "Baby"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load baby data from a dictionary"""
        super().from_dict(data)
        self.name = data.get("name", "")
        self.dob = data.get("dob", "")
        self.due_day = data.get("dueDay", "")
        self.gender = data.get("gender", False)
        self.picture_name = data.get("pictureName", "")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert baby model to a dictionary"""
        data = super().to_dict()
        data.update({
            "name": self.name,
            "dob": self.dob,
            "dueDay": self.due_day,
            "gender": self.gender,
            "pictureName": self.picture_name
        })
        return data
class Diaper(BaseModel):
        """Model representing a diaper change"""
        
        # Define status constants
        STATUS_WET = 0
        STATUS_POOPY = 1
        STATUS_MIXED = 2
        STATUS_DRY = 3
        
        def __init__(self, data: Dict[str, Any] = None):
            self.time: str = None
            self.status: int = self.STATUS_WET
            self.pee_color: int = 0
            self.poo_color: int = 0
            self.texture: int = 0
            self.amount: int = 2
            self.note: str = ""
            self.baby_id: str = None
            self.timezone: int = -21600  # Default timezone offset
            self.picture_loaded: bool = False
            
            super().__init__(data)
            self.object_type = "Diaper"
        
        def from_dict(self, data: Dict[str, Any]) -> None:
            """Load diaper data from a dictionary"""
            super().from_dict(data)
            self.time = data.get("time", self.timestamp)
            self.status = data.get("status", self.STATUS_WET)
            self.pee_color = data.get("peeColor", 0)
            self.poo_color = data.get("pooColor", 0)
            self.texture = data.get("texture", 0)
            self.amount = data.get("amount", 2)
            self.note = data.get("note", "")
            
            # Handle baby reference
            baby_data = data.get("baby", {})
            if isinstance(baby_data, dict):
                self.baby_id = baby_data.get("objectID", "")
            else:
                self.baby_id = data.get("baby_id", "")
            
            self.timezone = data.get("timezone", -21600)
            self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
        
        def to_dict(self) -> Dict[str, Any]:
            """Convert diaper model to a dictionary"""
            data = super().to_dict()
            data.update({
                "time": self.time,
                "status": self.status,
                "peeColor": self.pee_color,
                "pooColor": self.poo_color,
                "texture": self.texture,
                "amount": self.amount,
                "note": self.note,
                "timezone": self.timezone,
                "pictureNote": [],
                "pictureLoaded": str(self.picture_loaded).lower()
            })
            if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
            return data
class Nursing(BaseModel):
    """Model representing a nursing session"""
    
    # Define finish side constants
    FINISH_RIGHT = 0
    FINISH_LEFT = 1
    FINISH_BOTH = 2
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.left_duration: int = 0
        self.right_duration: int = 0
        self.both_duration: int = 0
        self.finish_side: int = self.FINISH_LEFT
        self.note: str = ""
        self.baby_id: str = None
        self.timezone: int = -21600
        self.picture_loaded: bool = False
        
        super().__init__(data)
        self.object_type = "Nursing"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load nursing data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.left_duration = data.get("leftDuration", 0)
        self.right_duration = data.get("rightDuration", 0)
        self.both_duration = data.get("bothDuration", 0)
        self.finish_side = data.get("finishSide", self.FINISH_LEFT)
        self.note = data.get("note", "")
        
        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")
        
        self.timezone = data.get("timezone", -21600)
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert nursing model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "leftDuration": self.left_duration,
            "rightDuration": self.right_duration,
            "bothDuration": self.both_duration,
            "finishSide": self.finish_side,
            "note": self.note,
            "timezone": self.timezone,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
        })
        if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
        return data
    
    @property
    def total_duration(self) -> int:
        """Calculate the total nursing duration in minutes"""
        if (self.left_duration == 0 or self.left_duration is None) and (self.right_duration == 0 or self.right_duration is None):
            return self.both_duration
        elif (self.left_duration == 0 or self.left_duration is None) and self.right_duration > 0:
            return self.right_duration
        elif self.left_duration > 0 and (self.right_duration == 0 or self.right_duration is None):
            return self.left_duration
        elif self.left_duration > 0 and self.right_duration > 0:
            return self.left_duration + self.right_duration
        return 0
class VolumeMeasure(BaseModel):
    """Model representing a volume measurement for feeding"""
    
    def __init__(self, data: Dict[str, Any] = None, value: float = 0, english_measure: bool = False):
        self.value: float = value
        self.english_measure: bool = english_measure
        
        super().__init__(data)
        self.object_type = "VolumeMeasure"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load volume measure data from a dictionary"""
        super().from_dict(data)
        self.value = float(data.get("value", 0))
        self.english_measure = str(data.get("englishMeasure", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert volume measure model to a dictionary"""
        data = super().to_dict()
        data.update({
            "value": self.value,
            "englishMeasure": str(self.english_measure).lower()
        })
        return data
    
    @property
    def oz(self) -> float:
        """Get the volume in ounces"""
        if self.english_measure:
            return self.value
        else:
            return self.value / 29.5735
    
    @property
    def ml(self) -> float:
        """Get the volume in milliliters"""
        if not self.english_measure:
            return self.value
        else:
            return self.value * 29.5735
class Formula(BaseModel):
    """Model representing a formula feeding"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.amount: VolumeMeasure = VolumeMeasure()
        self.note: str = ""
        self.baby_id: str = None
        self.timezone: int = -21600
        self.picture_loaded: bool = False
        
        super().__init__(data)
        self.object_type = "Formula"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load formula data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        
        # Handle amount data
        amount_data = data.get("amount", {})
        if isinstance(amount_data, dict):
            self.amount = VolumeMeasure(amount_data)
        else:
            # For backward compatibility
            self.amount.value = float(data.get("amount", 0))
            self.amount.english_measure = bool(data.get("isEnglishScale", False))
        
        self.note = data.get("note", "")
        
        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")
        
        self.timezone = data.get("timezone", -21600)
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert formula model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "amount": self.amount.to_dict(),
            "note": self.note,
            "timezone": self.timezone,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
        })
        if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
        return data
class OtherFeed(BaseModel):
    """Model representing other feeding types"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.amount: VolumeMeasure = VolumeMeasure()
        self.note: str = ""
        self.baby_id: str = None
        self.timezone: int = -21600
        self.picture_loaded: bool = False
        self.type_id: str = None        # Added field for type ID
        self.desc_id: str = None        # Added field for description ID 
        self.unit: str = ""             # Added field for unit
        self.is_english_scale: bool = False  # Boolean flag for measurement system
        
        super().__init__(data)
        self.object_type = "OtherFeed"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load other feeding data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        
        # Handle amount data
        amount_data = data.get("amount", {})
        if isinstance(amount_data, dict):
            self.amount = VolumeMeasure(amount_data)
        else:
            # For backward compatibility
            self.amount.value = float(data.get("amount", 0))
            self.amount.english_measure = bool(data.get("isEnglishScale", False))
        
        # Handle additional OtherFeed specific fields
        self.type_id = data.get("typeID", "")
        self.desc_id = data.get("descID", "")
        self.unit = data.get("unit", "")
        self.is_english_scale = bool(data.get("isEnglishScale", False))
        
        self.note = data.get("note", "")
        
        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")
        
        self.timezone = data.get("timezone", -21600)
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert other feeding model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "amount": self.amount.to_dict(),
            "typeID": self.type_id,
            "descID": self.desc_id,
            "unit": self.unit,
            "isEnglishScale": self.is_english_scale,
            "note": self.note,
            "timezone": self.timezone,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
        })
        if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
        return data
class Temperature(BaseModel):
    """Model representing a temperature reading"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.temperature: float = 0.0
        self.is_english_temp_measure: bool = False  # False for Celsius, True for Fahrenheit
        self.note: str = ""
        self.baby_id: str = None
        self.picture_loaded: bool = False
        
        super().__init__(data)
        self.object_type = "Temperature"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load temperature data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        
        # Handle temperature data
        temp_data = data.get("temperature", {})
        if isinstance(temp_data, dict):
            self.temperature = float(temp_data.get("value", 0.0))
            self.is_english_temp_measure = str(temp_data.get("englishMeasure", "false")).lower() == "true"
        else:
            # For backward compatibility
            self.temperature = float(data.get("temperature", 0.0))
            self.is_english_temp_measure = bool(data.get("isEnglishTemperatureMeasure", False))
        
        self.note = data.get("note", "")
        
        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")
    
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert temperature model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "temperature": {
                "value": self.temperature,
                "englishMeasure": str(self.is_english_temp_measure).lower(),
                "BCObjectType": "TemperatureMeasure"
            },
            "note": self.note,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
        })
        if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
        return data
    
    @property
    def celsius(self) -> float:
        """Get the temperature in Celsius"""
        if not self.is_english_temp_measure:
            return self.temperature
        else:
            return (self.temperature - 32) * 5/9
    
    @property
    def fahrenheit(self) -> float:
        """Get the temperature in Fahrenheit"""
        if self.is_english_temp_measure:
            return self.temperature
        else:
            return (self.temperature * 9/5) + 32
class Sleep(BaseModel):
    """Model representing a sleep record"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.duration: int = 0  # Duration in minutes
        self.note: str = ""
        self.baby_id: str = None
        self.picture_loaded: bool = False
        
        super().__init__(data)
        self.object_type = "Sleep"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load sleep data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.duration = int(data.get("duration", 0))
        self.note = data.get("note", "")
        
        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")
        
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert sleep model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "duration": self.duration,
            "note": self.note,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
        })
        if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
        return data
class FeedType(BaseModel):
    """Model representing a feed type (for supplements)"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.name: str = ""
        self.desc_id: str = ""
        self.is_bottle: bool = False
        
        super().__init__(data)
        self.object_type = "FeedType"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load feed type data from a dictionary"""
        super().from_dict(data)
        self.name = data.get("name", "")
        self.desc_id = data.get("descID", "")
        self.is_bottle = str(data.get("isBottle", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert feed type model to a dictionary"""
        data = super().to_dict()
        data.update({
            "name": self.name,
            "descID": self.desc_id,
            "isBottle": str(self.is_bottle).lower()
        })
        return data
class OtherFeed(BaseModel):
    """Model representing a supplement/other feed"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.feed_type: FeedType = FeedType()
        self.amount: VolumeMeasure = VolumeMeasure()
        self.unit: str = ""
        self.note: str = ""
        self.baby_id: str = None
        self.timezone: int = -21600
        self.picture_loaded: bool = False
        
        super().__init__(data)
        self.object_type = "OtherFeed"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load other feed data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        
        # Handle feed type
        feed_type_data = data.get("feedType", {})
        if isinstance(feed_type_data, dict):
            self.feed_type = FeedType(feed_type_data)
        
        # Handle amount data
        amount_data = data.get("amount", {})
        if isinstance(amount_data, dict):
            self.amount = VolumeMeasure(amount_data)
        
        self.unit = data.get("unit", "")
        self.note = data.get("note", "")
        
        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")
        
        self.timezone = data.get("timezone", -21600)
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert other feed model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "feedType": self.feed_type.to_dict(),
            "amount": self.amount.to_dict(),
            "unit": self.unit,
            "note": self.note,
            "timezone": self.timezone,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
        })
        if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
        return data
class Pump(BaseModel):
    """Model representing a pumping session"""
    
    # Define finish side constants
    FINISH_RIGHT = 0
    FINISH_LEFT = 1
    FINISH_BOTH = 2
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.finish_side: int = self.FINISH_RIGHT
        self.sides: int = 0
        self.amount: VolumeMeasure = VolumeMeasure()
        self.left_amount: float = 0.0
        self.right_amount: float = 0.0
        self.left_duration: int = 0
        self.right_duration: int = 0
        self.is_english_scale: bool = False
        self.label: str = ""
        self.pumped_id: str = None
        self.note: str = ""
        self.baby_id: str = None
        self.timezone: int = -21600
        self.picture_loaded: bool = False
        
        super().__init__(data)
        self.object_type = "Pump"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load pump data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.finish_side = data.get("finishSide", self.FINISH_RIGHT)
        self.sides = data.get("sides", 0)
        
        # Handle amount data
        amount_data = data.get("amount", {})
        if isinstance(amount_data, dict):
            self.amount = VolumeMeasure(amount_data)
        else:
            # For backward compatibility
            self.amount.value = float(data.get("amount", 0))
            self.amount.english_measure = bool(data.get("isEnglishScale", False))
        
        # Handle left amount
        left_amount_data = data.get("leftAmount", {})
        if isinstance(left_amount_data, dict):
            self.left_amount = float(left_amount_data.get("value", 0))
        else:
            self.left_amount = float(data.get("leftAmount", 0))
        
        # Handle right amount
        right_amount_data = data.get("rightAmount", {})
        if isinstance(right_amount_data, dict):
            self.right_amount = float(right_amount_data.get("value", 0))
        else:
            self.right_amount = float(data.get("rightAmount", 0))
        
        self.left_duration = int(data.get("leftDuration", 0))
        self.right_duration = int(data.get("rightDuration", 0))
        self.is_english_scale = str(data.get("isEnglishScale", "false")).lower() == "true"
        self.label = data.get("label", "")
        self.pumped_id = data.get("pumpedID", "")
        self.note = data.get("note", "")
        
   
        self.timezone = data.get("timezone", -21600)
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert pump model to a dictionary"""
        data = super().to_dict()
        
        # Create VolumeMeasure objects for left and right amounts
        left_amount = VolumeMeasure(None, self.left_amount, self.is_english_scale)
        right_amount = VolumeMeasure(None, self.right_amount, self.is_english_scale)
        
        data.update({
            "time": self.time,
            "finishSide": self.finish_side,
            "sides": self.sides,
            "amount": self.amount.to_dict(),
            "leftAmount": left_amount.to_dict(),
            "rightAmount": right_amount.to_dict(),
            "leftDuration": self.left_duration,
            "rightDuration": self.right_duration,
            "isEnglishScale": str(self.is_english_scale).lower(),
            "label": self.label,
            "pumpedID": self.pumped_id,
            "note": self.note,
            "timezone": self.timezone,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
        })
        
       
    
            
        return data
    
    @property
    def total_amount(self) -> float:
        """Get the total amount pumped"""
        return self.left_amount + self.right_amount
    
    @property
    def total_duration(self) -> int:
        """Get the total duration of the pumping session"""
        return self.left_duration + self.right_duration
class Pumped(BaseModel):
    """Model representing a pumped milk record"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.amount: VolumeMeasure = VolumeMeasure()
        self.note: str = ""
        self.baby_id: str = None
        self.timezone: int = -21600
        self.picture_loaded: bool = False
        
        super().__init__(data)
        self.object_type = "Pumped"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load pumped milk data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        
        # Handle amount data
        amount_data = data.get("amount", {})
        if isinstance(amount_data, dict):
            self.amount = VolumeMeasure(amount_data)
        else:
            # For backward compatibility with flatter structure
            self.amount.value = float(data.get("amount", 0))
            self.amount.english_measure = bool(data.get("isEnglishScale", False))
        
        self.note = data.get("note", "")
        
        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")
        self.timezone = data.get("timezone", -21600)
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert pumped milk model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "amount": self.amount.to_dict(),
            "note": self.note,
            "timezone": self.timezone,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
        })
        if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
        return data
class MedicationSelection(BaseModel):
    """Model representing a medicine type selection"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.name: str = ""
        self.description: str = ""
        self.is_prescription: bool = False
        self.amount_per_time: float = 0.0
        self.unit: str = ""
        self.interval: int = 0  # Interval in hours
        
        super().__init__(data)
        self.object_type = "MedicationSelection"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load medicine selection data from a dictionary"""
        super().from_dict(data)
        self.name = data.get("name", "")
        self.description = data.get("description", "")
        self.is_prescription = str(data.get("isPrescription", "false")).lower() == "true"
        self.amount_per_time = float(data.get("amountPerTime", 0.0))
        self.unit = data.get("unit", "")
        self.interval = int(data.get("interval", 0))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert medicine selection model to a dictionary"""
        data = super().to_dict()
        data.update({
            "name": self.name,
            "description": self.description,
            "isPrescription": str(self.is_prescription).lower(),
            "amountPerTime": self.amount_per_time,
            "unit": self.unit,
            "interval": self.interval
        })
        return data

class Medication(BaseModel):
    """Model representing a medicine administration record"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.med_id: str = None
        self.amount: float = 0.0
        self.note: str = ""
        self.baby_id: str = None
        self.picture_loaded: bool = False
        self.medication_selection: MedicationSelection = None
        
        super().__init__(data)
        self.object_type = "Medication"  # Changed from Medicine
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load medicine data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.amount = float(data.get("amount", 0.0))
        self.note = data.get("note", "")
        
        # Handle medicine selection reference
        medicine_data = data.get("medicine", {})
        if isinstance(medicine_data, dict):
            self.medicine_selection = MedicineSelection(medicine_data)
            self.med_id = medicine_data.get("objectID", "")
        else:
            self.med_id = data.get("medID", "")
        
        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")
        
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert medicine model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "medID": self.med_id,
            "amount": self.amount,
            "note": self.note,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
       })
        if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
        
        # Include medicine selection if available
        if self.medicine_selection:
            data["medicine"] = self.medicine_selection.to_dict()
            
        return data
class OtherActivityDesc(BaseModel):
    """Model representing an other activity description"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.name: str = ""
        self.desc: str = ""
        
        super().__init__(data)
        self.object_type = "OtherActivityDescription"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load activity description data from a dictionary"""
        super().from_dict(data)
        self.name = data.get("name", "")
        self.desc = data.get("desc", "")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert activity description model to a dictionary"""
        data = super().to_dict()
        data.update({
            "name": self.name,
            "desc": self.desc
        })
        return data

class OtherActivity(BaseModel):
    """Model representing an other activity record"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.desc_id: str = None
        self.location_id: str = None
        self.duration: int = 0  # Duration in minutes
        self.note: str = ""
        self.baby_id: str = None
        self.picture_loaded: bool = False
        self.activity_desc: OtherActivityDesc = None
        
        super().__init__(data)
        self.object_type = "OtherActivity"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load activity data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.duration = int(data.get("duration", 0))
        self.note = data.get("note", "")
        
        # Handle activity description reference
        desc_data = data.get("desc", {})
        if isinstance(desc_data, dict):
            self.activity_desc = OtherActivityDesc(desc_data)
            self.desc_id = desc_data.get("objectID", "")
        else:
            self.desc_id = data.get("descID", "")
        
        self.location_id = data.get("locationID", "")
        
        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")
        
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert other activity model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "duration": self.duration,
            "note": self.note,
            "locationID": self.location_id,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
        })
        if self.desc_id:
            data["descID"] =self.desc_id
        if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
        
        # Include activity description if available
        if self.activity_desc:
            data["desc"] = self.activity_desc.to_dict()
        else:
            data["descID"] = self.desc_id
            
        return data
class MedicineSelection(BaseModel):
    """Model representing a medicine type selection"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.name: str = ""
        self.description: str = ""
        self.is_prescription: bool = False
        self.amount_per_time: float = 0.0
        self.unit: str = ""
        self.interval: int = 0  # Interval in hours
        
        super().__init__(data)
        self.object_type = "MedicineSelection"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load medicine selection data from a dictionary"""
        super().from_dict(data)
        self.name = data.get("name", "")
        self.description = data.get("description", "")
        self.is_prescription = str(data.get("isPrescription", "false")).lower() == "true"
        self.amount_per_time = float(data.get("amountPerTime", 0.0))
        self.unit = data.get("unit", "")
        self.interval = int(data.get("interval", 0))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert medicine selection model to a dictionary"""
        data = super().to_dict()
        data.update({
            "name": self.name,
            "description": self.description,
            "isPrescription": str(self.is_prescription).lower(),
            "amountPerTime": self.amount_per_time,
            "unit": self.unit,
            "interval": self.interval
        })
        return data

class Medicine(BaseModel):
    """Model representing a medicine administration record"""
    
    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.med_id: str = None
        self.amount: float = 0.0
        self.note: str = ""
        self.baby_id: str = None
        self.picture_loaded: bool = False
        self.medicine_selection: MedicineSelection = None
        
        super().__init__(data)
        self.object_type = "Medicine"
    
    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load medicine data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.amount = float(data.get("amount", 0.0))
        self.note = data.get("note", "")
        
        # Handle medicine selection reference
        medicine_data = data.get("medicine", {})
        if isinstance(medicine_data, dict):
            self.medicine_selection = MedicineSelection(medicine_data)
            self.med_id = medicine_data.get("objectID", "")
        else:
            self.med_id = data.get("medID", "")
        
        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")
        
        self.picture_loaded = str(data.get("pictureLoaded", "false")).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert medicine model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "medID": self.med_id,
            "amount": self.amount,
            "note": self.note,
            "pictureNote": [],
            "pictureLoaded": str(self.picture_loaded).lower()
       })
        if self.baby_id:
                data["baby"] = {"objectID": self.baby_id}
        
        # Include medicine selection if available
        if self.medicine_selection:
            data["medicine"] = self.medicine_selection.to_dict()
            
        return data
class MilestoneSelection(BaseModel):
    """Model representing a milestone selection/type"""

    def __init__(self, data: Dict[str, Any] = None):
        self.name: str = ""
        self.description: str = ""

        super().__init__(data)
        self.object_type = "MilestoneSelection"

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load milestone selection data from a dictionary"""
        super().from_dict(data)
        self.name = data.get("name", "")
        self.description = data.get("description", "")

    def to_dict(self) -> Dict[str, Any]:
        """Convert milestone selection model to a dictionary"""
        data = super().to_dict()
        data.update({
            "name": self.name,
            "description": self.description
        })
        return data

class Milestone(BaseModel):
    """Model representing a milestone achievement"""

    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.milestone_selection_id: str = None
        self.note: str = ""
        self.baby_id: str = None
        self.has_picture: bool = False
        self.milestone_selection: MilestoneSelection = None

        super().__init__(data)
        self.object_type = "Milestone"

    def from_dict(self, data: Dict[str, Any] = None) -> None:
        """Load milestone data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.note = data.get("note", "")

        # Handle milestone selection reference
        milestone_data = data.get("milestoneSelection", {})
        if isinstance(milestone_data, dict):
            self.milestone_selection = MilestoneSelection(milestone_data)
            self.milestone_selection_id = milestone_data.get("objectID", "")
        else:
            self.milestone_selection_id = data.get("milestoneSelectionID", "")

        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")

        self.has_picture = bool(data.get("hasPicture", False))

    def to_dict(self) -> Dict[str, Any]:
        """Convert milestone model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "milestoneSelectionID": self.milestone_selection_id,
            "note": self.note,
            "hasPicture": self.has_picture
        })
        if self.baby_id:
            data["baby"] = {"objectID": self.baby_id}

        # Include milestone selection if available
        if self.milestone_selection:
            data["milestoneSelection"] = self.milestone_selection.to_dict()

        return data

class DoctorVisit(BaseModel):
    """Model representing a doctor visit"""

    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.is_appointment: bool = True
        self.visit_type: int = 0
        self.doctor_id: str = None
        self.doctor_note: str = ""
        self.symptom: str = ""
        self.growth_id: str = None
        self.sick_id: str = None
        self.note: str = ""
        self.baby_id: str = None
        self.has_picture: bool = False

        super().__init__(data)
        self.object_type = "DoctorVisit"

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load doctor visit data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.is_appointment = bool(data.get("isAppointment", True))
        self.visit_type = int(data.get("visitType", 0))
        self.doctor_id = data.get("doctorID", "")
        self.doctor_note = data.get("doctorNote", "")
        self.symptom = data.get("symptom", "")
        self.growth_id = data.get("growthID", "")
        self.sick_id = data.get("sickID", "")
        self.note = data.get("note", "")

        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")

        self.has_picture = bool(data.get("hasPicture", False))

    def to_dict(self) -> Dict[str, Any]:
        """Convert doctor visit model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "isAppointment": self.is_appointment,
            "visitType": self.visit_type,
            "doctorID": self.doctor_id,
            "doctorNote": self.doctor_note,
            "symptom": self.symptom,
            "growthID": self.growth_id,
            "sickID": self.sick_id,
            "note": self.note,
            "hasPicture": self.has_picture
        })
        if self.baby_id:
            data["baby"] = {"objectID": self.baby_id}

        return data

class VaccineSelection(BaseModel):
    """Model representing a vaccine selection/type"""

    def __init__(self, data: Dict[str, Any] = None):
        self.name: str = ""
        self.description: str = ""

        super().__init__(data)
        self.object_type = "VaccineSelection"

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load vaccine selection data from a dictionary"""
        super().from_dict(data)
        self.name = data.get("name", "")
        self.description = data.get("description", "")

    def to_dict(self) -> Dict[str, Any]:
        """Convert vaccine selection model to a dictionary"""
        data = super().to_dict()
        data.update({
            "name": self.name,
            "description": self.description
        })
        return data

class Vaccine(BaseModel):
    """Model representing a vaccine administration"""

    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.vacc_id: str = None
        self.doc_visit_id: str = None
        self.note: str = ""
        self.baby_id: str = None
        self.has_picture: bool = False
        self.vaccine_selection: VaccineSelection = None

        super().__init__(data)
        self.object_type = "Vaccine"

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load vaccine data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.doc_visit_id = data.get("docVisitID", "")
        self.note = data.get("note", "")

        # Handle vaccine selection reference
        vaccine_data = data.get("vaccineSelection", {})
        if isinstance(vaccine_data, dict):
            self.vaccine_selection = VaccineSelection(vaccine_data)
            self.vacc_id = vaccine_data.get("objectID", "")
        else:
            self.vacc_id = data.get("vaccID", "")

        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")

        self.has_picture = bool(data.get("hasPicture", False))

    def to_dict(self) -> Dict[str, Any]:
        """Convert vaccine model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "vaccID": self.vacc_id,
            "docVisitID": self.doc_visit_id,
            "note": self.note,
            "hasPicture": self.has_picture
        })
        if self.baby_id:
            data["baby"] = {"objectID": self.baby_id}

        # Include vaccine selection if available
        if self.vaccine_selection:
            data["vaccineSelection"] = self.vaccine_selection.to_dict()

        return data

class Growth(BaseModel):
    """Model representing a growth measurement"""

    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.weight: float = 0.0
        self.length: float = 0.0
        self.head: float = 0.0
        self.is_english_weight_scale: bool = True
        self.is_english_length_scale: bool = True
        self.note: str = ""
        self.baby_id: str = None
        self.has_picture: bool = False

        super().__init__(data)
        self.object_type = "Growth"

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load growth data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.weight = float(data.get("weight", 0.0))
        self.length = float(data.get("length", 0.0))
        self.head = float(data.get("head", 0.0))
        self.is_english_weight_scale = bool(data.get("isEnglishWeightScale", True))
        self.is_english_length_scale = bool(data.get("isEnglishLengthScale", True))
        self.note = data.get("note", "")

        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")

        self.has_picture = bool(data.get("hasPicture", False))

    def to_dict(self) -> Dict[str, Any]:
        """Convert growth model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "weight": self.weight,
            "length": self.length,
            "head": self.head,
            "isEnglishWeightScale": self.is_english_weight_scale,
            "isEnglishLengthScale": self.is_english_length_scale,
            "note": self.note,
            "hasPicture": self.has_picture
        })
        if self.baby_id:
            data["baby"] = {"objectID": self.baby_id}

        return data

class BathType(BaseModel):
    """Model representing a bath type/description"""

    def __init__(self, data: Dict[str, Any] = None):
        self.name: str = ""

        super().__init__(data)
        self.object_type = "BathType"

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load bath type data from a dictionary"""
        super().from_dict(data)
        self.name = data.get("name", "")

    def to_dict(self) -> Dict[str, Any]:
        """Convert bath type model to a dictionary"""
        data = super().to_dict()
        data.update({
            "name": self.name
        })
        return data

class Bath(BaseModel):
    """Model representing a bath record"""

    def __init__(self, data: Dict[str, Any] = None):
        self.time: str = None
        self.desc_id: str = None
        self.note: str = ""
        self.baby_id: str = None
        self.has_picture: bool = False
        self.bath_type: BathType = None

        super().__init__(data)
        self.object_type = "Bath"

    def from_dict(self, data: Dict[str, Any]) -> None:
        """Load bath data from a dictionary"""
        super().from_dict(data)
        self.time = data.get("time", self.timestamp)
        self.note = data.get("note", "")

        # Handle bath type reference
        bath_type_data = data.get("bathType", {})
        if isinstance(bath_type_data, dict):
            self.bath_type = BathType(bath_type_data)
            self.desc_id = bath_type_data.get("objectID", "")
        else:
            self.desc_id = data.get("descID", "")

        # Handle baby reference
        baby_data = data.get("baby", {})
        if isinstance(baby_data, dict):
            self.baby_id = baby_data.get("objectID", "")
        else:
            self.baby_id = data.get("baby_id", "")

        self.has_picture = bool(data.get("hasPicture", False))

    def to_dict(self) -> Dict[str, Any]:
        """Convert bath model to a dictionary"""
        data = super().to_dict()
        data.update({
            "time": self.time,
            "descID": self.desc_id,
            "note": self.note,
            "hasPicture": self.has_picture
        })
        if self.baby_id:
            data["baby"] = {"objectID": self.baby_id}

        # Include bath type if available
        if self.bath_type:
            data["bathType"] = self.bath_type.to_dict()

        return data
