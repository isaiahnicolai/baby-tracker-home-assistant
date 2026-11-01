"""
Record types synced with Baby Tracker and how each is stored locally.

Each RecordType maps a transaction's JSON (as sent by the apps) to the columns
of its SQLite table. The mappings follow the Android app's putValues methods
(data_objects/*.java), so a record stored here matches what the app would store.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# A column value is computed from the raw record and a date parser
Extractor = Callable[[Dict[str, Any], Callable[[Any], float]], Any]


def _bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def ref_id(record, *keys) -> str:
    """objectID of the first nested object present, or a flat ID field."""
    for key in keys:
        value = record.get(key)
        if isinstance(value, dict) and value.get("objectID"):
            return value["objectID"]
        if isinstance(value, str) and value:
            return value
    return ""


def _measure(record, key) -> Tuple[float, Optional[bool]]:
    """(value, englishMeasure) of a Measure field; englishMeasure is None if absent."""
    value = record.get(key)
    if isinstance(value, dict):
        english = value.get("englishMeasure")
        return float(value.get("value") or 0), (None if english is None else _bool(english))
    if value in (None, ""):
        return 0.0, None
    return float(value), None


def _positive(record, key) -> Tuple[float, Optional[bool]]:
    """_measure, but a value of zero or less counts as not measured (value 0, no scale)."""
    value, english = _measure(record, key)
    return (value, english) if value > 0 else (0.0, None)


def _enum(value, names: List[str], default: int) -> int:
    """
    Decode an enum sent as an int (iOS, and HA's own posts) or as a Java enum
    name such as "DiaperStatusWet" (stock Gson on Android).
    """
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value)
    if text.lstrip("-").isdigit():
        return int(text)
    lowered = text.lower()
    for index, name in enumerate(names):
        if lowered == name.lower():
            return index
    return default


DIAPER_STATUS = ["DiaperStatusWet", "DiaperStatusPoopy", "DiaperStatusMixed", "DiaperStatusDry"]
DIAPER_AMOUNT = ["DiaperAmountNone", "DiaperAmountLight", "DiaperAmountNormal",
                 "DiaperAmountHeavy", "DiaperAmountOverflow", "DiaperAmountNoset"]
NURSING_FINISH_SIDE = ["NursingFinishSideNotSet", "NursingFinishSideLeft", "NursingFinishSideRight"]
PUMP_FINISH_SIDE = ["PumpFinishSideNone", "PumpFinishSideLeft", "PumpFinishSideRight"]
PUMP_SIDES = ["PumpSidesBoth", "PumpSidesLeft", "PumpSidesRight"]


def has_picture(record) -> int:
    """Activity.isHasPictureNote: no picture loaded yet, or any picture not deleted."""
    if not _bool(record.get("pictureLoaded"), default=True):
        return 1
    pictures = record.get("pictureNote") or []
    return 1 if any(isinstance(p, dict) and not _bool(p.get("deleted")) for p in pictures) else 0


def _diaper_status(record):
    # Diaper.putValues stores Dry as Wet with amount None
    status = _enum(record.get("status"), DIAPER_STATUS, 0)
    return 0 if status == 3 else status


def _diaper_amount(record):
    if _enum(record.get("status"), DIAPER_STATUS, 0) == 3:
        return 0
    return _enum(record.get("amount"), DIAPER_AMOUNT, 2)  # a missing amount is saved as Normal


def _pump_has_label(record):
    return bool(record.get("label"))


def _pump_english(record):
    # Pump.putValues: from amount, else whichever side measure says English
    for key in ("amount", "leftAmount", "rightAmount"):
        _, english = _measure(record, key)
        if english is not None and (key == "amount" or english):
            return int(english)
    return 0


@dataclass
class RecordType:
    table: str
    columns: List[Tuple[str, Extractor]]
    baby: bool = False          # carries a BabyID
    activity: bool = True       # has Time/Note/HasPicture
    selection: bool = False     # a named selection (unique Name, in-use checks)
    # (record key, selection type) of nested selections to store if missing
    embedded: List[Tuple[str, str]] = field(default_factory=list)

    def row(self, record: Dict[str, Any], parse_date: Callable[[Any], float]) -> Dict[str, Any]:
        values = {
            "ID": record.get("objectID", ""),
            "Timestamp": parse_date(record.get("timestamp")),
        }
        if self.activity:
            values["Time"] = parse_date(record.get("time"))
            values["Note"] = record.get("note") or ""
            values["HasPicture"] = has_picture(record)
        if self.baby:
            values["BabyID"] = ref_id(record, "baby", "baby_id")
        for column, extract in self.columns:
            values[column] = extract(record, parse_date)
        return values


def _selection(table, *extra):
    return RecordType(table, [
        ("Name", lambda r, d: r.get("name") or ""),
        ("Description", lambda r, d: r.get("desc") or r.get("description") or ""),
        *extra,
    ], activity=False, selection=True)


_MEDICATION_SELECTION = _selection(
    "MedicineSelection",
    ("IsPrescription", lambda r, d: int(_bool(r.get("prescription", r.get("isPrescription"))))),
    ("AmountPerTime", lambda r, d: float(r.get("amountPerTime") or 0)),
    ("Unit", lambda r, d: r.get("unit") or ""),
    ("Interval", lambda r, d: int(r.get("interval") or 0)),
)
_OTHER_ACTIVITY_DESC = _selection("OtherActivityDesc")
_BATH_DESC = _selection("BathDesc")

# Selections the Android app only knows by schema (BTSQLiteOpenHelper, EditableSelectionType): they
# share EditableSelection's name/desc, so they map exactly like the others. The wire names of these
# types are the table names (as for BathDesc); the aliases below cover the iOS class names.
_DOCTOR = _selection(
    "DoctorSelection",
    ("Address", lambda r, d: r.get("address") or ""),
    ("ClinicName", lambda r, d: r.get("clinicName") or ""),
    ("PhoneNumber", lambda r, d: r.get("phoneNumber") or ""),
)


def _bottle(table, *extra):
    return RecordType(table, [
        ("DescID", lambda r, d: ref_id(r, "desc", "descID")),
        ("Amount", lambda r, d: _measure(r, "amount")[0]),
        ("IsEnglishScale", lambda r, d: int(_bool(_measure(r, "amount")[1], default=True))),
        *extra,
    ], baby=True, embedded=[("desc", "FeedDesc")])


RECORD_TYPES: Dict[str, RecordType] = {
    "Baby": RecordType("Baby", [
        ("Name", lambda r, d: r.get("name") or ""),
        ("DOB", lambda r, d: d(r.get("dob")) if r.get("dob") else 0.0),
        ("DueDay", lambda r, d: d(r.get("dueDay")) if r.get("dueDay") else 0.0),
        ("Gender", lambda r, d: int(_bool(r.get("gender")))),
        ("Picture", lambda r, d: r.get("pictureName") or ""),
    ], activity=False),

    "Diaper": RecordType("Diaper", [
        ("Status", lambda r, d: _diaper_status(r)),
        ("Amount", lambda r, d: _diaper_amount(r)),
        # Not fields in the Android app; iOS sends them. 5 = not set (column default)
        ("PeeColor", lambda r, d: int(r.get("peeColor", 5))),
        ("PooColor", lambda r, d: int(r.get("pooColor", 5))),
        ("Texture", lambda r, d: int(r.get("texture", 5))),
        ("Flag", lambda r, d: int(r.get("flag", 0))),
    ], baby=True),

    "Nursing": RecordType("Nursing", [
        ("DescID", lambda r, d: ref_id(r, "desc", "descID")),
        ("FinishSide", lambda r, d: _enum(r.get("finishSide"), NURSING_FINISH_SIDE, 0)),
        ("LeftDuration", lambda r, d: int(r.get("leftDuration") or 0)),
        ("RightDuration", lambda r, d: int(r.get("rightDuration") or 0)),
        ("BothDuration", lambda r, d: int(r.get("bothDuration") or 0)),
    ], baby=True, embedded=[("desc", "FeedDesc")]),

    "Formula": _bottle("Formula"),
    "Pumped": _bottle("Pumped", ("PumpID", lambda r, d: "")),

    "OtherFeed": RecordType("OtherFeed", [
        ("DescID", lambda r, d: ref_id(r, "desc")),
        ("TypeID", lambda r, d: ref_id(r, "feedType", "typeID")),
        ("Amount", lambda r, d: _measure(r, "amount")[0]),
        ("IsEnglishScale", lambda r, d: int(_bool(_measure(r, "amount")[1], default=True))),
        ("Unit", lambda r, d: r.get("unit") or ""),
    ], baby=True, embedded=[("feedType", "OtherFeedSelection"), ("desc", "FeedDesc")]),

    "Temperature": RecordType("Temperature", [
        ("Temp", lambda r, d: _measure(r, "temperature")[0]),
        ("IsEnglishScale", lambda r, d: int(_bool(_measure(r, "temperature")[1], default=True))),
    ], baby=True),

    "Sleep": RecordType("Sleep", [
        # Sleep.putValues clamps a negative duration to zero
        ("Duration", lambda r, d: max(int(r.get("duration") or 0), 0)),
        # The Android app writes both empty; iOS can send a selection or its ID
        ("LocationID", lambda r, d: ref_id(r, "location", "locationID")),
        ("DescID", lambda r, d: ref_id(r, "desc", "descID")),
    ], baby=True, embedded=[("location", "SleepLocationSelection"), ("desc", "SleepDesc")]),

    "Medication": RecordType("Medicine", [
        ("MedID", lambda r, d: ref_id(r, "medicationSelection", "medication", "medicine", "medID")),
        ("Amount", lambda r, d: float(r.get("amount") or 0)),
    ], baby=True, embedded=[("medicationSelection", "MedicationSelection")]),

    "OtherActivity": RecordType("OtherActivity", [
        ("DescID", lambda r, d: ref_id(r, "desc", "descID")),
        ("LocationID", lambda r, d: ref_id(r, "location", "locationID")),
        ("Duration", lambda r, d: int(r.get("duration") or 0)),
    ], baby=True, embedded=[("desc", "OtherActivityDescription"), ("location", "OtherActivityLocationSelection")]),

    "Bath": RecordType("Bath", [
        ("DescID", lambda r, d: ref_id(r, "bathType", "desc", "descID")),
    ], baby=True, embedded=[("bathType", "BathType")]),

    # Plain BabyActivity records: Joy and Journal add no columns of their own
    "Joy": RecordType("Joy", [], baby=True),
    "Journal": RecordType("Journal", [], baby=True),

    "Milestone": RecordType("Milestone", [
        ("MilestoneSelectionID", lambda r, d: ref_id(r, "milestoneType", "milestoneSelection", "milestoneSelectionID")),
    ], baby=True, embedded=[("milestoneType", "MilestoneSelection")]),

    "Vaccine": RecordType("Vaccine", [
        ("VaccID", lambda r, d: ref_id(r, "vaccineType", "vaccineSelection", "vaccID")),
        ("DocVisitID", lambda r, d: r.get("docVisitID") or "NotUsed"),
    ], baby=True, embedded=[("vaccineType", "VaccineSelection")]),

    # Growth.putValues stores a measure only when it is above zero
    "Growth": RecordType("Growth", [
        ("Weight", lambda r, d: _positive(r, "weight")[0]),
        ("Length", lambda r, d: _positive(r, "length")[0]),
        ("Head", lambda r, d: _positive(r, "head")[0]),
        ("IsEnglishWeightScale", lambda r, d: int(_bool(_positive(r, "weight")[1], default=True))),
        # The length's scale, else the head's, else English
        ("IsEnglishLengthScale", lambda r, d: int(_bool(
            _positive(r, "length")[1] if _positive(r, "length")[0] else _positive(r, "head")[1],
            default=True))),
    ], baby=True),

    # No BabyID: pumping belongs to the account
    "Pump": RecordType("Pump", [
        ("FinishSide", lambda r, d: _enum(r.get("finishSide"), PUMP_FINISH_SIDE, 0)),
        # An inventory adjustment (label set) has no sides (Pump.putValues)
        ("Sides", lambda r, d: 0 if _pump_has_label(r) else _enum(r.get("sides"), PUMP_SIDES, 0)),
        ("Amount", lambda r, d: _measure(r, "amount")[0]),
        ("IsEnglishScale", lambda r, d: _pump_english(r)),
        ("Label", lambda r, d: r.get("label") or ""),
        ("PumpedID", lambda r, d: ""),
        ("LeftAmount", lambda r, d: 0.0 if _pump_has_label(r) else _measure(r, "leftAmount")[0]),
        ("RightAmount", lambda r, d: 0.0 if _pump_has_label(r) else _measure(r, "rightAmount")[0]),
        ("LeftDuration", lambda r, d: 0 if _pump_has_label(r) else int(r.get("leftDuration") or 0)),
        ("RightDuration", lambda r, d: 0 if _pump_has_label(r) else int(r.get("rightDuration") or 0)),
    ]),

    # Not an Android type; kept for records from iOS and HA's local doctor visits
    "DoctorVisit": RecordType("DoctorVisit", [
        ("IsAppointment", lambda r, d: int(_bool(r.get("isAppointment"), default=True))),
        ("VisitType", lambda r, d: int(r.get("visitType") or 0)),
        ("DoctorID", lambda r, d: ref_id(r, "doctor", "doctorID")),
        ("DoctorNote", lambda r, d: r.get("doctorNote") or ""),
        ("Symptom", lambda r, d: r.get("symptom") or ""),
        ("GrowthID", lambda r, d: r.get("growthID") or ""),
        ("SickID", lambda r, d: r.get("sickID") or ""),
    ], baby=True, embedded=[("doctor", "DoctorSelection")]),

    # A join record: which medicines were prescribed at a visit
    "DoctorVisitMedicine": RecordType("DoctorVisitMedicine", [
        ("DoctorVisitID", lambda r, d: ref_id(r, "doctorVisit", "doctorVisitID", "docVisitID")),
        ("MedID", lambda r, d: ref_id(r, "medicationSelection", "medication", "medicine", "medID")),
    ], activity=False, embedded=[("medicationSelection", "MedicationSelection")]),

    "MedicationSelection": _MEDICATION_SELECTION,
    "OtherFeedSelection": _selection(
        "OtherFeedSelection", ("IsBottle", lambda r, d: int(_bool(r.get("bottle", r.get("isBottle")))))),
    "OtherActivityDescription": _OTHER_ACTIVITY_DESC,
    "MilestoneSelection": _selection(
        "MilestoneSelection",
        ("ForAge", lambda r, d: int(r.get("forAge") or 0)),
        ("BabyID", lambda r, d: r.get("babyID")),
    ),
    "VaccineSelection": _selection("VaccineSelection", ("ForAge", lambda r, d: int(r.get("forAge") or 0))),
    "BathType": _BATH_DESC,
    "FeedDesc": _selection("FeedDesc"),
    "SleepDesc": _selection("SleepDesc"),
    "SleepLocationSelection": _selection("SleepLocationSelection"),
    "SickDesc": _selection("SickDesc"),
    "AllergenSourceSelection": _selection("AllergenSourceSelection"),
    "OtherActivityLocationSelection": _selection("OtherActivityLocationSelection"),
    "DoctorSelection": _DOCTOR,
}

# Alternative type names seen in the wild
ALIASES = {
    "NursingSession": "Nursing",  # a Nursing subclass in the Android app
    "Medicine": "Medication",
    "MedicineSelection": "MedicationSelection",
    "OtherActivityDesc": "OtherActivityDescription",
    "BathDesc": "BathType",
    "FeedDescription": "FeedDesc",
    "SleepDescription": "SleepDesc",
    "SleepLocation": "SleepLocationSelection",
    "SickDescription": "SickDesc",
    "AllergenSource": "AllergenSourceSelection",
    "OtherActivityLocation": "OtherActivityLocationSelection",
    "Doctor": "DoctorSelection",
}

# Where each selection is used (BTDatabaseImple.selectionUsed), for in-use
# checks on delete and re-pointing references on conflict
SELECTION_USAGE = {
    "OtherActivityDescription": [("OtherActivity", "DescID")],
    "MilestoneSelection": [("Milestone", "MilestoneSelectionID")],
    "MedicationSelection": [("Medicine", "MedID")],
    "VaccineSelection": [("Vaccine", "VaccID")],
    "OtherFeedSelection": [("OtherFeed", "TypeID")],
    "BathType": [("Bath", "DescID")],
    "FeedDesc": [("Nursing", "DescID"), ("Formula", "DescID"), ("Pumped", "DescID"), ("OtherFeed", "DescID")],
    "SleepDesc": [("Sleep", "DescID")],
    "SleepLocationSelection": [("Sleep", "LocationID")],
    "SickDesc": [],  # the Sick table has no description column to point at it
    "AllergenSourceSelection": [("Allergen", "SourceID")],
    "OtherActivityLocationSelection": [("OtherActivity", "LocationID")],
    "DoctorSelection": [("DoctorVisit", "DoctorID")],
}
# A medicine selection is also named by the medicines prescribed at a visit
SELECTION_USAGE["MedicationSelection"].append(("DoctorVisitMedicine", "MedID"))

# Tables with a BabyID, re-pointed when two babies are merged
# (BTDatabaseImple.updateBabyReference). Pump has no BabyID.
BABY_REFERENCE_TABLES = [
    "Allergen", "Bath", "Diaper", "DoctorVisit", "Formula", "Growth",
    "HealthQuestion", "Journal", "Joy", "Medicine", "Milestone", "Nursing",
    "OtherActivity", "OtherFeed", "Pumped", "Sick", "Sleep", "Temperature",
    "Vaccine",
]


# Picture.mediaType (MediaType): the Picture table stores the index
MEDIA_TYPES = ["MediaTypePicture", "MediaTypeVideo", "MediaTypeAudio"]
THUMBNAIL_SUFFIX = "__thumbnail.jpg"  # DefaultValues.ThumbnailPost


def picture_entries(record) -> List[Dict[str, Any]]:
    """
    The pictureNote entries of an activity as Picture rows plus a `deleted`
    flag: [{ID, Timestamp, Type, FileName, deleted}]. Entries without an
    objectID can't be keyed and are left out. Nothing is returned for an
    activity whose pictures aren't loaded (Activity.isPictureLoaded).
    """
    if not _bool(record.get("pictureLoaded"), default=True):
        return []
    entries = []
    for picture in record.get("pictureNote") or []:
        if not isinstance(picture, dict) or not picture.get("objectID"):
            continue
        entries.append({
            "ID": picture["objectID"],
            "Timestamp": picture.get("timestamp"),
            "Type": _enum(picture.get("mediaType"), MEDIA_TYPES, 0),
            # Picture() defaults its file name to its own ID
            "FileName": picture.get("fileName") or picture["objectID"],
            "deleted": _bool(picture.get("deleted")),
        })
    return entries


def picture_wire(object_id: str, file_name: str, activity_id: str, timestamp, media_type: int = 0,
                 new: bool = False) -> Dict[str, Any]:
    """
    One entry of an activity's pictureNote as the Android app sends it (a Gson-serialised
    Picture: the BCObject fields plus activityID, attached, deleted, fileName, mediaType).
    `timestamp` is an API date string.
    """
    return {
        "BCObjectType": "Picture",
        "objectID": object_id,
        "timestamp": timestamp,
        "newFlage": new,
        "activityID": activity_id,
        "attached": True,
        "deleted": False,
        "fileName": file_name,
        "mediaType": MEDIA_TYPES[media_type],
    }


def media_files(file_name: str, media_type: int) -> Tuple[str, str]:
    """(file, thumbnail) names on the server for a Picture (Picture.getFileFullName/getThumbnailFullName)."""
    extension = {0: ".jpg", 1: ".mp4"}.get(media_type, "")
    return file_name + extension, file_name + THUMBNAIL_SUFFIX


def format_date(timestamp) -> str:
    """Unix seconds as the API's date string."""
    from datetime import datetime, timezone
    return datetime.fromtimestamp(float(timestamp or 0), timezone.utc).strftime("%Y-%m-%d %H:%M:%S +0000")


# Wire names that differ from the names we store records under
WIRE_NAMES = {"BathType": "BathDesc"}


def named_wire(object_type: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """
    A stored baby or selection as the apps send it, for the records we upload
    ourselves (ConflictRecord winners, RELIVE). `row` is its table row by column name.
    """
    wire = {
        "BCObjectType": WIRE_NAMES.get(object_type, object_type),
        "objectID": row["ID"],
        "timestamp": format_date(row["Timestamp"]),
        "newFlage": False,
        "name": row["Name"],
    }
    if object_type == "Baby":
        wire.update({
            "dob": format_date(row["DOB"]) if row["DOB"] else "",
            "dueDay": format_date(row["DueDay"]) if row["DueDay"] else "",
            "gender": bool(row["Gender"]),
            "pictureName": row["Picture"] or "",
        })
        return wire
    wire["desc"] = row["Description"] or ""
    if object_type == "MedicationSelection":
        wire.update({"prescription": bool(row["IsPrescription"]), "amountPerTime": row["AmountPerTime"] or 0,
                     "unit": row["Unit"] or "", "interval": row["Interval"] or 0})
    elif object_type == "OtherFeedSelection":
        wire["bottle"] = bool(row["IsBottle"])
    elif object_type == "DoctorSelection":
        wire.update({"address": row["Address"] or "", "clinicName": row["ClinicName"] or "",
                     "phoneNumber": row["PhoneNumber"] or ""})
    elif object_type in ("MilestoneSelection", "VaccineSelection"):
        wire["forAge"] = row["ForAge"] or 0
        if object_type == "MilestoneSelection" and row["BabyID"]:
            wire["babyID"] = row["BabyID"]
    return wire


# The selection a record points at: (column, selection type, key in the record's JSON)
SELECTION_REFERENCES = {
    "OtherFeed": ("TypeID", "OtherFeedSelection", "feedType"),
    "Medication": ("MedID", "MedicationSelection", "medicationSelection"),
    "OtherActivity": ("DescID", "OtherActivityDescription", "desc"),
    "Bath": ("DescID", "BathType", "bathType"),
    "Milestone": ("MilestoneSelectionID", "MilestoneSelection", "milestoneType"),
    "Vaccine": ("VaccID", "VaccineSelection", "vaccineType"),
    "Sleep": ("DescID", "SleepDesc", "desc"),
    "Nursing": ("DescID", "FeedDesc", "desc"),
    "Formula": ("DescID", "FeedDesc", "desc"),
    "Pumped": ("DescID", "FeedDesc", "desc"),
    "DoctorVisit": ("DoctorID", "DoctorSelection", "doctor"),
}


def _measure_wire(value, english, kind="VolumeMeasure") -> Dict[str, Any]:
    return {"value": value or 0, "englishMeasure": bool(english), "BCObjectType": kind}


def record_wire(object_type: str, row: Dict[str, Any], baby: Optional[Dict[str, Any]] = None,
                selection: Optional[Dict[str, Any]] = None, tz_offset: int = 0) -> Dict[str, Any]:
    """
    A stored record (not a baby or selection) as the apps send it, for the
    transactions we upload about records that already exist, i.e. deletes.
    `row` is its table row by column name; `baby` and `selection` are the
    nested wire objects (named_wire) it refers to, when they are known. The
    inverse of RecordType.row for the fields the apps read.
    """
    object_type = canonical_type(object_type)
    kind = RECORD_TYPES[object_type]
    wire: Dict[str, Any] = {
        "BCObjectType": object_type,
        "objectID": row["ID"],
        "timestamp": format_date(row["Timestamp"]),
        "newFlage": False,
        "pictureLoaded": True,
        "pictureNote": [],
        "timezone": tz_offset,
    }
    if kind.activity:
        wire["time"] = format_date(row["Time"])
        wire["note"] = row["Note"] or ""
    if kind.baby:
        wire["baby"] = baby or {"objectID": row["BabyID"]}
    ref = SELECTION_REFERENCES.get(object_type)
    if ref and selection:
        wire[ref[2]] = selection

    def amount(english="IsEnglishScale"):
        return _measure_wire(row["Amount"], row[english])

    if object_type == "Diaper":
        wire.update({"status": row["Status"], "amount": row["Amount"], "peeColor": row["PeeColor"],
                     "pooColor": row["PooColor"], "texture": row["Texture"], "flag": row["Flag"] or 0})
    elif object_type == "Nursing":
        wire.update({"finishSide": row["FinishSide"], "leftDuration": row["LeftDuration"] or 0,
                     "rightDuration": row["RightDuration"] or 0, "bothDuration": row["BothDuration"] or 0})
    elif object_type in ("Formula", "Pumped"):
        wire["amount"] = amount()
    elif object_type == "OtherFeed":
        wire.update({"amount": amount(), "unit": row["Unit"] or ""})
    elif object_type == "Temperature":
        wire["temperature"] = _measure_wire(row["Temp"], row["IsEnglishScale"], "TemperatureMeasure")
    elif object_type == "Sleep":
        wire["duration"] = row["Duration"] or 0
        if row["LocationID"]:
            wire["locationID"] = row["LocationID"]
    elif object_type == "Medication":
        wire["amount"] = row["Amount"] or 0
    elif object_type == "OtherActivity":
        wire["duration"] = row["Duration"] or 0
        if row["LocationID"]:
            wire["locationID"] = row["LocationID"]
    elif object_type == "Milestone":
        wire["hasNewType"] = False
    elif object_type == "Growth":
        wire.update({"deleted": False, "queryIndex": 0})
        for key, column, scale in (("weight", "Weight", "IsEnglishWeightScale"),
                                   ("length", "Length", "IsEnglishLengthScale"),
                                   ("head", "Head", "IsEnglishLengthScale")):
            if row[column]:
                wire[key] = _measure_wire(row[column], row[scale])
    elif object_type == "DoctorVisit":
        wire.update({"isAppointment": bool(row["IsAppointment"]), "visitType": row["VisitType"] or 0,
                     "doctorNote": row["DoctorNote"] or "", "symptom": row["Symptom"] or "",
                     "growthID": row["GrowthID"] or "", "sickID": row["SickID"] or ""})
        if row["DoctorID"]:
            wire["doctorID"] = row["DoctorID"]
    elif object_type == "Pump":
        english = row["IsEnglishScale"]
        wire.update({
            "amount": _measure_wire(row["Amount"], english), "leftAmount": _measure_wire(row["LeftAmount"], english),
            "rightAmount": _measure_wire(row["RightAmount"], english), "leftDuration": row["LeftDuration"] or 0,
            "rightDuration": row["RightDuration"] or 0, "finishSide": row["FinishSide"] or 0,
            "sides": row["Sides"] or 0})
        if row["Label"]:
            wire["label"] = row["Label"]
    return wire


def canonical_type(object_type: str) -> str:
    return ALIASES.get(object_type, object_type)


def record_type(object_type: str) -> Optional[RecordType]:
    return RECORD_TYPES.get(canonical_type(object_type))


def usages(object_type: str) -> List[Tuple[str, str]]:
    object_type = canonical_type(object_type)
    if object_type == "Baby":
        return [(table, "BabyID") for table in BABY_REFERENCE_TABLES]
    return SELECTION_USAGE.get(object_type, [])
