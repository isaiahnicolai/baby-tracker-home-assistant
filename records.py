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


def _bottle(table, *extra):
    return RecordType(table, [
        ("DescID", lambda r, d: ""),
        ("Amount", lambda r, d: _measure(r, "amount")[0]),
        ("IsEnglishScale", lambda r, d: int(_bool(_measure(r, "amount")[1], default=True))),
        *extra,
    ], baby=True)


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
        ("DescID", lambda r, d: ""),
        ("FinishSide", lambda r, d: _enum(r.get("finishSide"), NURSING_FINISH_SIDE, 0)),
        ("LeftDuration", lambda r, d: int(r.get("leftDuration") or 0)),
        ("RightDuration", lambda r, d: int(r.get("rightDuration") or 0)),
        ("BothDuration", lambda r, d: int(r.get("bothDuration") or 0)),
    ], baby=True),

    "Formula": _bottle("Formula"),
    "Pumped": _bottle("Pumped", ("PumpID", lambda r, d: "")),

    "OtherFeed": RecordType("OtherFeed", [
        ("DescID", lambda r, d: ref_id(r, "desc")),
        ("TypeID", lambda r, d: ref_id(r, "feedType", "typeID")),
        ("Amount", lambda r, d: _measure(r, "amount")[0]),
        ("IsEnglishScale", lambda r, d: int(_bool(_measure(r, "amount")[1], default=True))),
        ("Unit", lambda r, d: r.get("unit") or ""),
    ], baby=True, embedded=[("feedType", "OtherFeedSelection")]),

    "Temperature": RecordType("Temperature", [
        ("Temp", lambda r, d: _measure(r, "temperature")[0]),
        ("IsEnglishScale", lambda r, d: int(_bool(_measure(r, "temperature")[1], default=True))),
    ], baby=True),

    "Sleep": RecordType("Sleep", [
        ("Duration", lambda r, d: int(r.get("duration") or 0)),
        ("LocationID", lambda r, d: ""),
        ("DescID", lambda r, d: ""),
    ], baby=True),

    "Medication": RecordType("Medicine", [
        ("MedID", lambda r, d: ref_id(r, "medicationSelection", "medication", "medicine", "medID")),
        ("Amount", lambda r, d: float(r.get("amount") or 0)),
    ], baby=True, embedded=[("medicationSelection", "MedicationSelection")]),

    "OtherActivity": RecordType("OtherActivity", [
        ("DescID", lambda r, d: ref_id(r, "desc", "descID")),
        ("LocationID", lambda r, d: r.get("locationID") or ""),
        ("Duration", lambda r, d: int(r.get("duration") or 0)),
    ], baby=True, embedded=[("desc", "OtherActivityDescription")]),

    "Bath": RecordType("Bath", [
        ("DescID", lambda r, d: ref_id(r, "bathType", "desc", "descID")),
    ], baby=True, embedded=[("bathType", "BathType")]),

    "Milestone": RecordType("Milestone", [
        ("MilestoneSelectionID", lambda r, d: ref_id(r, "milestoneType", "milestoneSelection", "milestoneSelectionID")),
    ], baby=True, embedded=[("milestoneType", "MilestoneSelection")]),

    "Vaccine": RecordType("Vaccine", [
        ("VaccID", lambda r, d: ref_id(r, "vaccineType", "vaccineSelection", "vaccID")),
        ("DocVisitID", lambda r, d: r.get("docVisitID") or "NotUsed"),
    ], baby=True, embedded=[("vaccineType", "VaccineSelection")]),

    "Growth": RecordType("Growth", [
        ("Weight", lambda r, d: _measure(r, "weight")[0]),
        ("Length", lambda r, d: _measure(r, "length")[0]),
        ("Head", lambda r, d: _measure(r, "head")[0]),
        ("IsEnglishWeightScale", lambda r, d: int(_bool(_measure(r, "weight")[1], default=True))),
        ("IsEnglishLengthScale", lambda r, d: int(_bool(
            _measure(r, "length")[1] if _measure(r, "length")[1] is not None else _measure(r, "head")[1],
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
    ], baby=True),

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
}

# Alternative type names seen in the wild
ALIASES = {
    "Medicine": "Medication",
    "MedicineSelection": "MedicationSelection",
    "OtherActivityDesc": "OtherActivityDescription",
    "BathDesc": "BathType",
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
}

# Tables with a BabyID, re-pointed when two babies are merged
# (BTDatabaseImple.updateBabyReference). Pump has no BabyID.
BABY_REFERENCE_TABLES = [
    "Allergen", "Bath", "Diaper", "DoctorVisit", "Formula", "Growth",
    "HealthQuestion", "Journal", "Joy", "Medicine", "Milestone", "Nursing",
    "OtherActivity", "OtherFeed", "Pumped", "Sick", "Sleep", "Temperature",
    "Vaccine",
]


def canonical_type(object_type: str) -> str:
    return ALIASES.get(object_type, object_type)


def record_type(object_type: str) -> Optional[RecordType]:
    return RECORD_TYPES.get(canonical_type(object_type))


def usages(object_type: str) -> List[Tuple[str, str]]:
    object_type = canonical_type(object_type)
    if object_type == "Baby":
        return [(table, "BabyID") for table in BABY_REFERENCE_TABLES]
    return SELECTION_USAGE.get(object_type, [])
