"""Constants and helpers shared by the client tests."""
import base64
import json

EMAIL = "me@example.com"
OURS = "ha-device-uuid"
IPHONE = "IPHONE-DEVICE-UUID"
EVERLY = "BABY-EVERLY"
TWIN = "BABY-TWIN"
MILESTONE = "MILESTONE-SMILE"
VACCINE = "VACCINE-HEPB"


def b64(record):
    return base64.b64encode(json.dumps(record).encode()).decode()


def unb64(text):
    return json.loads(base64.b64decode(text))
