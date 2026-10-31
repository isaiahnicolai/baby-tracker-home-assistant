"""
Baby model returned by the local database's baby lookups.

Synced records are stored straight from their transaction JSON (see records.py),
so no other models are needed.
"""

from datetime import datetime, timezone
from typing import Dict, Any
import uuid


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
