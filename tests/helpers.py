"""Constants and helpers shared by the client tests."""
import base64
import json

EMAIL = "me@example.com"
OURS = "ha-device-uuid"
IPHONE = "IPHONE-DEVICE-UUID"
AVA = "BABY-AVA"
TWIN = "BABY-TWIN"
MILESTONE = "MILESTONE-SMILE"
VACCINE = "VACCINE-HEPB"


# The fields every baby record carries
COMMON = {"timestamp": "2026-10-30 12:00:00 +0000", "time": "2026-10-30 11:00:00 +0000", "note": "",
          "pictureLoaded": True, "pictureNote": [], "baby": {"objectID": AVA}}


def b64(record):
    return base64.b64encode(json.dumps(record).encode()).decode()


def unb64(text):
    return json.loads(base64.b64decode(text))
