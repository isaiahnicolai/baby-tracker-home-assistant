"""The integration inside Home Assistant: setup, entity migration, services, and config flows."""
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfMass, UnitOfTemperature, UnitOfVolume
from homeassistant.core import State
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry

from custom_components.baby_tracker import BabyTrackerDataCoordinator
from custom_components.baby_tracker import intent as bt_intent
from custom_components.baby_tracker.client import AccountResetError, AuthenticationError
from custom_components.baby_tracker.client.models import Baby
from custom_components.baby_tracker.const import DOMAIN

EMAIL = "me@example.com"
AVA = Baby({"objectID": "ID-AVA", "name": "Ava", "dob": "", "dueDay": ""})
TWIN = Baby({"objectID": "ID-TWIN", "name": "Ann Marie", "dob": "", "dueDay": ""})
CORE = "custom_components.baby_tracker.client.core.BabyTracker"
REAL_FETCH = BabyTrackerDataCoordinator._fetch  # the `backend` fixture swaps it out while a test runs


@pytest.fixture(autouse=True)
def joined():
    """The account was joined and its history imported (the background first sync has its own tests)."""
    with patch(f"{CORE}.needs_first_sync", return_value=False) as needs:
        yield needs


def make_entry(unit_system="imperial", options=None):
    return MockConfigEntry(
        domain=DOMAIN, unique_id=EMAIL, title="Baby Tracker", version=2,
        data={"email": EMAIL, "password": "pw", "scan_interval": 15, "unit_system": unit_system,
              "device_uuid": "ha-uuid"},
        options=options or {},
    )


# The account's medicines and solids foods, as the client returns them
MEDICINES = [
    {"id": "MED-TYLENOL", "name": "Tylenol", "amount_per_time": 3.75, "unit": "ml"},
    {"id": "MED-VITD", "name": "Vitamin D", "amount_per_time": 1.0, "unit": "ml"},
]
# What get_recent_records returns for Ava (newest first), and what undo_last deletes
RECENT = [
    {"object_type": "Diaper", "object_id": "DIAPER-1", "time": "2026-03-01T10:00:00+00:00",
     "kind": "wet diaper", "note": ""},
    {"object_type": "Formula", "object_id": "FORMULA-1", "time": "2026-03-01T09:30:00+00:00",
     "kind": "formula 4 oz", "note": "after the nap"},
]
FOODS = [{"id": "FOOD-BANANA", "name": "Banana", "description": "", "is_bottle": False}]


# What BabyTracker.get_insights returns (datetimes as ISO strings)
INSIGHTS = {
    "baby_id": "ID-AVA",
    "name": "Ava",
    "generated_at": "2026-03-01T10:00:00+00:00",
    "age": {
        "chronological_days": 60, "corrected_days": 46, "chronological_months": 1.97,
        "corrected_months": 1.51, "gestation_days": 244, "premature": True,
        "correction_days": 14, "correction_applied": True,
    },
    "next_feed": {
        "predicted_at": "2026-03-01T12:30:00+00:00", "interval_hours": 3.0, "basis": "history",
        "sample_count": 6, "bucket": "day", "last_feed_at": "2026-03-01T09:30:00+00:00",
        "overdue": False, "max_gap_hours": 5.0, "wake_by": "2026-03-01T14:30:00+00:00",
    },
    "next_sleep": {  # Ava is asleep (since 11:00), as in last_sleep below
        "is_asleep": True, "asleep_since": "2026-03-01T11:00:00+00:00",
        "expected_wake_at": "2026-03-01T12:40:00+00:00", "awake_since": None, "wake_window_hours": None,
        "window_min_hours": 1.0, "window_max_hours": 2.5, "next_sleep_at": None, "overdue": False,
        "max_awake_hours": 2.5, "basis": "history", "sample_count": 5, "bucket": "day",
    },
    "intake": {
        "actual_ml": 420.0, "expected_min_ml": 600, "expected_max_ml": 800, "status": "low",
        "reason": "420 ml is under 600 ml (150 ml/kg)", "bottle_feeds": 6, "nursing_feeds": 1,
        "ml_per_kg": 105.0,
    },
    "diapers": {
        "status": "ok", "wet_status": "ok", "stool_status": "ok", "wet_count": 7, "dirty_count": 3,
        "day_of_life": 61, "expected_min_wet": 6, "low_below_wet": 5, "expected_min_dirty": 0,
        "note": "Infrequent stools are normal after 6 weeks",
    },
    "growth": {
        "weight": {
            "kind": "weight", "age_months": 1.4, "value": 4.0, "z": -0.5, "percentile": 30.9,
            "p3": 3.2, "p50": 4.5, "p97": 5.9, "measured_at": "2026-02-27T09:00:00+00:00",
        },
        "length": {
            "kind": "length", "age_months": 1.4, "value": 54.0, "z": -0.2, "percentile": 42.1,
            "p3": 50.0, "p50": 55.0, "p97": 60.0, "measured_at": "2026-02-27T09:00:00+00:00",
        },
    },
    "weight_velocity": {
        "status": "ok", "grams_per_day": 27.5, "expected_min": 20.0, "expected_max": 35.0,
        "span_days": 14.0, "from_at": "2026-02-13T09:00:00+00:00", "to_at": "2026-02-27T09:00:00+00:00",
        "reason": "28 g/day against 20-35 g/day expected",
    },
}


# What the coordinator keeps for Ava besides the insights (client values: UTC times as text)
AVA_DATA = {
    "insights": INSIGHTS,
    "time_since_last_feeding": {
        "hours_since_last_feeding": 2.5, "last_feeding_time": "2026-03-01T09:30:00+00:00",
        "time_difference": "2:30:00",
    },
    "last_feeding": {"time": "2026-03-01 09:30:00 +0000", "type": "Formula", "amount": 4.0,
                     "amount_oz": 4.0, "amount_ml": 118.3},
    "last_diaper": {"time": "2026-03-01 10:00:00 +0000", "status": "Wet"},
    "last_sleep": {"time": "2026-03-01 11:00:00 +0000", "is_sleeping": True, "duration": 0,
                   "current_duration": 45, "status": "sleeping"},
    "last_nursing": {"time": "2026-03-01 08:00:00 +0000", "total_duration": 12},
    "last_pump": {"time": "2026-03-01 07:00:00 +0000", "total_amount": 4.0, "unit": "oz"},
    "pump_summary": {"total_sessions": 3, "total_amount": 12.0, "unit": "oz", "days": 7},
    "last_growth": {"time": "2026-02-27 09:00:00 +0000", "weight": 10.0, "length": 20.0, "head": 14.0,
                    "weight_unit": "lbs", "length_unit": "in", "is_english_weight": True,
                    "is_english_length": True},
    "last_temperature": {"time": "2026-03-01 06:00:00 +0000", "fahrenheit": 99.1, "celsius": 37.3},
    "last_doctor_visit": {"time": "2026-02-20 15:00:00 +0000"},
    "last_activity": {"time": "2026-03-01 10:30:00 +0000", "duration": 15, "activity_name": "Tummy Time"},
    "feeding_summary": {"total_feedings": 20, "nursing_total_minutes": 90, "bottle_amount_ml": 500.0,
                        "bottle_amount_oz": 16.9},
    "diaper_summary": {"total_diapers": 30, "poopy_count": 5, "mixed_count": 2, "wet_count": 20},
    "daily_summary": {"total_feedings": 6, "diaper_count": 5},
    "sleep_analysis": {"avg_bedtime": "N/A", "avg_wake_time": "N/A", "days_analyzed": 0, "per_day": []},
    "next_breast": {"next_side": "right", "last_side": "left", "last_type": "nursing",
                    "last_time": "2026-03-01 08:00:00 +0000"},
    "next_medicine_dose": {"medicine_name": "Tylenol", "med_id": "MED", "amount": 2.5, "unit": "ml",
                           "last_given": "2026-03-01 06:00:00 +0000", "interval_minutes": 240,
                           "next_dose_at": "2026-03-01T10:00:00+00:00"},
    "upcoming_milestones": [{"id": "MS1", "name": "First smile", "description": "", "for_age": 2},
                            {"id": "MS2", "name": "Rolls over", "description": "", "for_age": 5}],
    "upcoming_vaccines": [{"id": "V1", "name": "HepB", "description": "", "for_age": 0}],
    "recent_records": RECENT,
}

# What the coordinator keeps for the account as a whole
ACCOUNT = {"pumped_milk_inventory": {"ml": 479.1, "pumped_ml": 588.3, "fed_ml": 109.2}, "pending_uploads": 2}


def fake_fetch(self, photo_dir):
    babies = [TWIN, AVA]
    data = {b.name: {"baby_info": b, **(AVA_DATA if b is AVA else {"insights": {}})} for b in babies}
    return babies, AVA, {}, data, ACCOUNT, MEDICINES


def fetch_with(**changes):
    """A fetch like fake_fetch, but with Ava's data changed (as after something new is logged)."""
    def fetch(self, photo_dir):
        babies, info, pictures, data, account, medicines = fake_fetch(self, photo_dir)
        data["Ava"] = {**data["Ava"], **changes}
        return babies, info, pictures, data, account, medicines
    return fetch


@pytest.fixture
def backend():
    """Stand in for the Baby Tracker client; records write calls."""
    calls = []

    def add_diaper(self, baby_id, time_str=None, *args):
        calls.append(("add_diaper", baby_id, time_str))
        return {"status": "success", "objectID": "new"}

    def add_temperature(self, baby_id, time_str=None, temperature=98.6, is_fahrenheit=True, note=""):
        calls.append(("add_temperature", baby_id, temperature, is_fahrenheit))
        return {"status": "success"}

    def log_growth(self, baby_id, weight, length, head, is_english_weight_scale, is_english_length_scale,
                   note="", time=None):
        calls.append(("log_growth", baby_id, is_english_weight_scale, is_english_length_scale))
        return {"status": "success"}

    def volume_feed(kind):
        def add(self, baby_id, time_str=None, amount=0, is_english_measure=False, note=""):
            calls.append((kind, baby_id, amount, is_english_measure))
            return {"status": "success"}
        return add

    def add_nursing(self, baby_id, time_str=None, left_duration=0, right_duration=0, both_duration=0,
                    finish_side=1, note=""):
        calls.append(("add_nursing", baby_id, time_str, left_duration, right_duration, finish_side))
        return {"status": "success"}

    def add_medicine(self, baby_id, time_str=None, med_id=None, amount=0, note=""):
        calls.append(("add_medicine", baby_id, med_id, amount))
        return {"status": "success"}

    def add_activity(self, baby_id, time_str=None, activity_name="Tummy Time", duration=0, location_id=None,
                     note=""):
        calls.append(("add_activity", baby_id, activity_name, duration, time_str))
        return {"status": "success"}

    def add_other_feed(self, baby_id, time_str=None, feed_type_id=None, amount=0, unit="",
                       is_english_measure=True, note=""):
        calls.append(("add_other_feed", baby_id, feed_type_id, amount, unit, is_english_measure))
        return {"status": "success"}

    def undo_last(self, baby_id, within_hours=24):
        calls.append(("undo_last", baby_id, within_hours))
        return {"status": "success", "deleted": RECENT[0], "queued": True}

    def delete_record(self, object_type, object_id):
        calls.append(("delete_record", object_type, object_id))
        return {"status": "success", "object_type": object_type, "object_id": object_id, "queued": True}

    def add_joy(self, baby_id, note="", time_str=None, photo_path=None, picture_dir=None):
        calls.append(("add_joy", baby_id, note, time_str, photo_path, picture_dir))
        return {"status": "success", "objectID": "JOY-1", "queued": False}

    def attach_photo(self, object_type, object_id, photo_path, picture_dir=None):
        calls.append(("attach_photo", object_type, object_id, photo_path, picture_dir))
        return {"status": "success", "objectID": object_id, "pictureID": "PIC-1", "queued": False}

    with patch(f"{CORE}.authenticate", return_value={"status": "success"}), \
         patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fake_fetch), \
         patch(f"{CORE}.undo_last", undo_last), \
         patch(f"{CORE}.delete_record", delete_record), \
         patch(f"{CORE}.add_joy", add_joy), \
         patch(f"{CORE}.attach_photo", attach_photo), \
         patch(f"{CORE}.add_diaper", add_diaper), \
         patch(f"{CORE}.add_temperature", add_temperature), \
         patch(f"{CORE}.log_growth", log_growth), \
         patch(f"{CORE}.add_formula", volume_feed("add_formula")), \
         patch(f"{CORE}.add_pumped", volume_feed("add_pumped")), \
         patch(f"{CORE}.add_nursing", add_nursing), \
         patch(f"{CORE}.add_medicine", add_medicine), \
         patch(f"{CORE}.add_activity", add_activity), \
         patch(f"{CORE}.add_other_feed", add_other_feed), \
         patch(f"{CORE}.get_medicine_selections", lambda self: MEDICINES), \
         patch(f"{CORE}.get_other_feed_selections", lambda self: FOODS), \
         patch(f"{CORE}.get_baby_by_name", lambda self, name: next((b for b in (TWIN, AVA) if b.name == name), None)):
        yield calls


async def setup(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_name_based_entities_migrate_to_baby_ids(hass, backend):
    entry = make_entry()
    entry.add_to_hass(hass)
    ent_reg, dev_reg = er.async_get(hass), dr.async_get(hass)
    # As older versions created them: keyed by the baby's name
    device = dev_reg.async_get_or_create(config_entry_id=entry.entry_id,
                                         identifiers={(DOMAIN, f"{EMAIL}_ann_marie")})
    old = ent_reg.async_get_or_create("button", DOMAIN, f"{DOMAIN}_{EMAIL}_ann_marie_add_wet_diaper",
                                      config_entry=entry, suggested_object_id="ann_marie_add_wet_diaper",
                                      device_id=device.id)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    migrated = ent_reg.async_get(old.entity_id)
    assert migrated.unique_id == f"{DOMAIN}_{EMAIL}_ID-TWIN_add_wet_diaper"
    assert migrated.entity_id == "button.ann_marie_add_wet_diaper"  # unchanged, so dashboards keep working
    assert dev_reg.async_get(device.id).identifiers == {(DOMAIN, f"{EMAIL}_ID-TWIN")}
    wet = [e for e in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
           if e.unique_id.endswith("ID-TWIN_add_wet_diaper")]
    assert len(wet) == 1


async def test_each_baby_gets_its_own_diaper_buttons(hass, backend):
    await setup(hass, make_entry())
    for baby_id, slug in (("ID-TWIN", "ann_marie"), ("ID-AVA", "ava")):
        for kind in ("wet", "dirty", "mixed"):
            entity_id = f"button.{slug}_add_{kind}_diaper"
            assert hass.states.get(entity_id), entity_id
            await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
            assert backend[-1][:2] == ("add_diaper", baby_id)


async def test_services_target_a_baby_by_device(hass, backend):
    await setup(hass, make_entry())
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    device = next(d for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
                  if (DOMAIN, f"{EMAIL}_ID-TWIN") in d.identifiers)
    await hass.services.async_call(DOMAIN, "add_diaper", {"device_id": device.id, "pee": True}, blocking=True)
    assert backend[-1][:2] == ("add_diaper", "ID-TWIN")

    await hass.services.async_call(DOMAIN, "add_diaper", {"baby_name": "Ava"}, blocking=True)
    assert backend[-1][:2] == ("add_diaper", "ID-AVA")

    # Two babies and none chosen: refuse rather than guess
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "add_diaper", {"pee": True}, blocking=True)


async def test_rejected_password_asks_to_log_in_again(hass):
    entry = make_entry()
    entry.add_to_hass(hass)
    with patch(f"{CORE}.authenticate", side_effect=AuthenticationError("Login rejected (401)")):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    flow = next(f for f in hass.config_entries.flow.async_progress()
                if f["context"]["source"] == config_entries.SOURCE_REAUTH)
    with patch("custom_components.baby_tracker.config_flow.validate_login", return_value=None), \
         patch("custom_components.baby_tracker.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"password": "new-pw"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["password"] == "new-pw"


async def test_setup_flow_gives_the_integration_its_own_device_id(hass):
    with patch("custom_components.baby_tracker.config_flow.validate_login", return_value=None) as login, \
         patch("custom_components.baby_tracker.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"email": EMAIL, "password": "pw", "scan_interval": 15, "unit_system": "metric"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["device_uuid"]
    # The dialog only checks the password; joining and importing happen once the entry exists
    assert login.call_args.args[1:] == (EMAIL, "pw", result["data"]["device_uuid"])
    assert result["title"] == "Baby Tracker"


async def test_setup_flow_reports_a_wrong_password(hass):
    from custom_components.baby_tracker.config_flow import InvalidAuth
    with patch("custom_components.baby_tracker.config_flow.validate_login", side_effect=InvalidAuth("401")):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"email": EMAIL, "password": "bad", "scan_interval": 15, "unit_system": "metric"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_first_setup_imports_the_history_in_the_background_then_reloads(hass, backend, joined):
    joined.side_effect = [True, False]  # first setup: not joined yet; after the import: joined
    notifications = []
    with patch("custom_components.baby_tracker.persistent_notification.async_create",
               lambda hass, message, title=None, notification_id=None: notifications.append(notification_id)), \
         patch("custom_components.baby_tracker.persistent_notification.async_dismiss",
               lambda hass, notification_id: notifications.remove(notification_id)):
        entry = make_entry()
        await setup(hass, entry)
        await hass.async_block_till_done(wait_background_tasks=True)  # the import, then the reload
        await hass.async_block_till_done()

    assert entry.state is config_entries.ConfigEntryState.LOADED
    assert hass.states.get("button.ava_add_wet_diaper") is not None  # set up again after the import
    assert entry.title == "Baby Tracker (Ann Marie & Ava)"
    assert notifications == []  # shown during the import, dismissed after
    assert joined.call_count == 2


async def test_a_failed_first_import_keeps_the_entry_loaded_and_unloads_cleanly(hass, joined):
    joined.return_value = True
    notifications = []

    def failing_fetch(self, photo_dir):
        raise ConnectionError("server unreachable")

    with patch(f"{CORE}.authenticate", return_value={"status": "success"}), \
         patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", failing_fetch), \
         patch("custom_components.baby_tracker.persistent_notification.async_create",
               lambda hass, message, title=None, notification_id=None: notifications.append(notification_id)):
        entry = make_entry()
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)  # returns at once, the import runs on
        await hass.async_block_till_done(wait_background_tasks=False)

        assert entry.state is config_entries.ConfigEntryState.LOADED
        assert hass.states.get("button.ava_add_wet_diaper") is None  # no entities until the import works
        assert len(notifications) == 1
        assert await hass.config_entries.async_unload(entry.entry_id)  # cancels the retry
        assert entry.entry_id not in hass.data[DOMAIN]


async def test_migration_leaves_account_level_entities_alone(hass):
    from custom_components.baby_tracker.const import ACCOUNT_ENTITY_KEYS
    from custom_components.baby_tracker.entity import migrate_to_baby_ids
    from custom_components.baby_tracker.sensor import HOUSEHOLD_SENSORS

    # The list the migration trusts matches the entities the integration really creates
    assert ACCOUNT_ENTITY_KEYS == {"sync_now", "force_resync"} | {f"system_{c._sensor_type}" for c in HOUSEHOLD_SENSORS}

    entry = make_entry()
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    account = {}
    for domain, key in (("sensor", "system_next_feed_due"), ("button", "sync_now"), ("button", "force_resync")):
        unique_id = f"{DOMAIN}_{EMAIL}_{key}"
        account[unique_id] = ent_reg.async_get_or_create(domain, DOMAIN, unique_id, config_entry=entry).entity_id
    # A baby-level entity from before babies were keyed by ID: this one does migrate
    ent_reg.async_get_or_create("sensor", DOMAIN, f"{DOMAIN}_{EMAIL}_system_last_feeding", config_entry=entry)

    # Babies whose names look like the start of an account-level entity's ID
    babies = [Baby({"objectID": f"ID-{name.upper()}", "name": name, "dob": "", "dueDay": ""})
              for name in ("System", "Sync", "Force")]
    migrate_to_baby_ids(hass, entry, EMAIL, babies)

    for unique_id, entity_id in account.items():
        assert ent_reg.async_get(entity_id).unique_id == unique_id
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{EMAIL}_ID-SYSTEM_last_feeding")


async def test_a_bad_row_in_the_diaper_or_medicine_reads_does_not_fail_the_refresh(hass, backend):
    from unittest.mock import MagicMock

    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)
    tracker = MagicMock()
    tracker.sync.return_value = {"status": "success"}
    tracker.get_all_babies.return_value = [AVA]
    tracker.get_baby_info.return_value = AVA
    tracker.get_events_between.return_value = []
    tracker.get_diaper_summary.side_effect = ValueError("bad row")
    tracker.get_medicine_selections.side_effect = ValueError("bad row")
    coordinator.baby_tracker = tracker

    # The real _fetch (the fixture replaced it on the class)
    _, _, _, baby_data, _, medicines = REAL_FETCH(coordinator, coordinator.photo_dir)

    assert baby_data["Ava"]["diaper_summary"] is None
    assert medicines == []


async def test_a_second_account_cannot_be_added(hass):
    # Every entry shares one local database, so the manifest allows a single entry
    make_entry().add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_options_flow(hass):
    entry = make_entry()
    entry.add_to_hass(hass)
    with patch("custom_components.baby_tracker.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 5, "unit_system": "metric"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # What was left alone keeps its default; the fever temperature stays unset (blank = 100.4 F / 38.0 C)
    assert entry.options == {
        "scan_interval": 5, "unit_system": "metric", "feeding_overdue_hours": 0, "low_wet_minimum": 4,
        "night_start_hour": 19, "night_end_hour": 7,
    }


async def test_options_flow_sets_the_alert_thresholds(hass):
    entry = make_entry()
    entry.add_to_hass(hass)
    settings = {"scan_interval": 5, "unit_system": "imperial", "feeding_overdue_hours": 2.5, "low_wet_minimum": 6,
                "night_start_hour": 20, "night_end_hour": 6, "fever_threshold": 100.0}
    with patch("custom_components.baby_tracker.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], settings)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == settings


async def test_options_flow_refuses_a_fever_temperature_in_the_wrong_unit(hass):
    entry = make_entry()
    entry.add_to_hass(hass)
    with patch("custom_components.baby_tracker.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        # 38 is a Celsius fever; the entry is in Fahrenheit
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 15, "unit_system": "imperial", "fever_threshold": 38.0})
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"fever_threshold": "invalid_fever_threshold"}

        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 15, "unit_system": "metric", "fever_threshold": 38.0})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["fever_threshold"] == 38.0


async def test_insight_entities(hass, backend):
    await setup(hass, make_entry(unit_system="metric"))

    assert hass.states.get("sensor.ava_next_feed").state == "2026-03-01T12:30:00+00:00"
    next_feed = hass.states.get("sensor.ava_next_feed").attributes
    assert next_feed["basis"] == "history" and next_feed["wake_by"] == "2026-03-01T14:30:00+00:00"

    intake = hass.states.get("sensor.ava_intake_24h")
    assert float(intake.state) == 420.0
    assert intake.attributes["unit_of_measurement"] == "mL"
    assert intake.attributes["status"] == "low"
    assert intake.attributes["expected_min_ml"] == 600
    assert intake.attributes["bottle_feeds"] == 6

    assert hass.states.get("sensor.ava_intake_status").state == "low"
    assert hass.states.get("sensor.ava_diaper_adequacy").state == "ok"
    assert float(hass.states.get("sensor.ava_weight_percentile").state) == 30.9
    assert hass.states.get("sensor.ava_weight_percentile").attributes["p50"] == 4.5
    assert hass.states.get("sensor.ava_head_percentile").state == "unknown"  # no head measurement
    assert float(hass.states.get("sensor.ava_weight_gain").state) == 27.5
    assert hass.states.get("sensor.ava_corrected_age").state == "46"

    assert hass.states.get("binary_sensor.ava_intake_low").state == "on"
    assert hass.states.get("binary_sensor.ava_feed_due").state == "on"  # the prediction is in the past
    assert hass.states.get("binary_sensor.ava_wake_to_feed").state == "on"

    # A baby with no insights has unknown values rather than errors
    assert hass.states.get("sensor.ann_marie_next_feed").state == "unknown"
    assert hass.states.get("binary_sensor.ann_marie_intake_low").state == "off"


AWAKE = {  # awake since 10:30, with a 1 h 45 min wake window: sleepy at 12:15
    "is_asleep": False, "asleep_since": None, "expected_wake_at": None,
    "awake_since": "2026-03-01T10:30:00+00:00", "wake_window_hours": 1.75,
    "window_min_hours": 1.0, "window_max_hours": 2.5, "next_sleep_at": "2026-03-01T12:15:00+00:00",
    "overdue": False, "max_awake_hours": 2.5, "basis": "age_default", "sample_count": 2, "bucket": "day",
}


def with_next_sleep(next_sleep):
    return fetch_with(insights={**INSIGHTS, "next_sleep": next_sleep})


async def test_sleep_prediction_entities_for_an_awake_baby(hass, backend, freezer):
    freezer.move_to("2026-03-01 12:00:00+00:00")
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", with_next_sleep(AWAKE)):
        await setup(hass, make_entry())

    next_sleep = hass.states.get("sensor.ava_next_sleep")
    assert next_sleep.state == "2026-03-01T12:15:00+00:00"
    assert next_sleep.attributes["device_class"] == "timestamp"
    assert next_sleep.attributes["awake_since"] == "2026-03-01T10:30:00+00:00"
    assert next_sleep.attributes["wake_window_hours"] == 1.75
    assert (next_sleep.attributes["window_min_hours"], next_sleep.attributes["window_max_hours"]) == (1.0, 2.5)
    assert next_sleep.attributes["max_awake_hours"] == 2.5
    assert (next_sleep.attributes["basis"], next_sleep.attributes["sample_count"]) == ("age_default", 2)
    assert (next_sleep.attributes["bucket"], next_sleep.attributes["overdue"]) == ("day", False)

    window = hass.states.get("sensor.ava_wake_window")
    assert float(window.state) == 1.75
    assert window.attributes["unit_of_measurement"] == "h" and window.attributes["device_class"] == "duration"
    assert window.attributes["state_class"] == "measurement"
    assert (window.attributes["window_min_hours"], window.attributes["window_max_hours"]) == (1.0, 2.5)
    assert window.attributes["basis"] == "age_default"

    assert hass.states.get("sensor.ava_expected_wake").state == "unknown"  # awake
    assert hass.states.get("binary_sensor.ava_sleep_due").state == "off"
    assert hass.states.get("binary_sensor.ava_nap_running_long").state == "off"


async def test_sleep_prediction_entities_for_a_sleeping_baby(hass, backend, freezer):
    freezer.move_to("2026-03-01 12:00:00+00:00")
    await setup(hass, make_entry())

    expected = hass.states.get("sensor.ava_expected_wake")
    assert expected.state == "2026-03-01T12:40:00+00:00"
    assert expected.attributes["device_class"] == "timestamp"
    assert expected.attributes["asleep_since"] == "2026-03-01T11:00:00+00:00"
    assert (expected.attributes["basis"], expected.attributes["sample_count"], expected.attributes["bucket"]) == (
        "history", 5, "day")

    assert hass.states.get("sensor.ava_next_sleep").state == "unknown"  # asleep
    assert hass.states.get("sensor.ava_wake_window").state == "unknown"
    assert hass.states.get("binary_sensor.ava_sleep_due").state == "off"
    assert hass.states.get("binary_sensor.ava_nap_running_long").state == "off"  # not yet 13:10

    # A baby with no insights has unknown values rather than errors
    for key in ("sensor.ann_marie_next_sleep", "sensor.ann_marie_expected_wake", "sensor.ann_marie_wake_window"):
        assert hass.states.get(key).state == "unknown", key
    assert hass.states.get("binary_sensor.ann_marie_sleep_due").state == "off"
    assert hass.states.get("binary_sensor.ann_marie_nap_running_long").state == "off"


async def test_sleep_due_turns_on_when_the_clock_passes_the_wake_window(hass, backend, freezer):
    freezer.move_to("2026-03-01 12:05:00+00:00")
    fetches = []
    fetch = with_next_sleep(AWAKE)

    def counting_fetch(self, photo_dir):
        fetches.append(photo_dir)
        return fetch(self, photo_dir)

    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", counting_fetch):
        await setup(hass, make_entry())
        assert hass.states.get("binary_sensor.ava_sleep_due").state == "off"  # sleepy at 12:15

        freezer.tick(timedelta(minutes=11))  # past 12:15, short of the next 15-minute refresh
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert len(fetches) == 1
        due = hass.states.get("binary_sensor.ava_sleep_due")
        assert due.state == "on"
        assert due.attributes["next_sleep_at"] == "2026-03-01T12:15:00+00:00"
        assert due.attributes["awake_since"] == "2026-03-01T10:30:00+00:00"
        assert due.attributes["wake_window_hours"] == 1.75
        assert hass.states.get("binary_sensor.ava_nap_running_long").state == "off"  # awake

        # It can be dismissed until the next episode
        await hass.services.async_call(
            DOMAIN, "dismiss_alert", {"entity_id": "binary_sensor.ava_sleep_due"}, blocking=True)
        assert hass.states.get("binary_sensor.ava_sleep_due").state == "off"


async def test_nap_running_long_turns_on_half_an_hour_after_the_expected_wake(hass, backend, freezer):
    freezer.move_to("2026-03-01 13:08:00+00:00")  # expected wake 12:40, so 13:10 is the line
    await setup(hass, make_entry())
    assert hass.states.get("binary_sensor.ava_nap_running_long").state == "off"
    assert hass.states.get("binary_sensor.ava_sleep_due").state == "off"  # asleep

    freezer.tick(timedelta(minutes=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    running_long = hass.states.get("binary_sensor.ava_nap_running_long")
    assert running_long.state == "on"
    assert running_long.attributes["expected_wake_at"] == "2026-03-01T12:40:00+00:00"
    assert running_long.attributes["asleep_since"] == "2026-03-01T11:00:00+00:00"


async def test_sensors_have_numeric_states_and_device_classes(hass, backend):
    await setup(hass, make_entry(unit_system="metric"))

    def check(entity_id, state, unit=None, device_class=None, state_class=None):
        found = hass.states.get(entity_id)
        assert found, entity_id
        assert found.state == state, entity_id
        assert found.attributes.get("unit_of_measurement") == unit, entity_id
        assert found.attributes.get("device_class") == device_class, entity_id
        assert found.attributes.get("state_class") == state_class, entity_id
        return found.attributes

    attrs = check("sensor.ava_time_since_last_feeding", "150", "min", "duration", "measurement")
    assert attrs["feeding_status"] == "Due for feeding soon" and attrs["needs_feeding"] is False
    attrs = check("sensor.ava_last_sleep", "45", "min", "duration", "measurement")
    assert attrs["sleeping"] is True
    check("sensor.ava_last_nursing", "12", "min", "duration", "measurement")
    check("sensor.ava_nursing_minutes", "90", "min", "duration", "measurement")
    # Amounts, not meter readings: volume_storage (HA allows only total classes for "volume")
    check("sensor.ava_last_pump", "118.3", "mL", "volume_storage", "measurement")  # recorded as 4 oz
    check("sensor.ava_pump_summary", "354.9", "mL", "volume_storage", "measurement")
    check("sensor.ava_bottle_volume", "500.0", "mL", "volume_storage", "measurement")
    check("sensor.ava_weight", "4.536", "kg", "weight", "measurement")  # recorded as 10 lb
    check("sensor.ava_length", "50.8", "cm", "distance", "measurement")  # recorded as 20 in
    check("sensor.ava_head_circumference", "35.6", "cm", "distance", "measurement")
    check("sensor.ava_temperature", "37.3", "°C", "temperature", "measurement")
    attrs = check("sensor.ava_feedings", "20", "feedings", None, "measurement")
    assert attrs["window_days"] == 7
    check("sensor.ava_diapers", "30", "diapers", None, "measurement")
    check("sensor.ava_poopy_diapers", "7", "diapers", None, "measurement")  # mixed ones count
    check("sensor.ava_wet_diapers", "22", "diapers", None, "measurement")
    check("sensor.ava_daily_summary", "6", "feedings", None, "measurement")

    # Times are real timestamps; the kinds of feeding and diaper are enum states
    check("sensor.ava_last_feeding_time", "2026-03-01T09:30:00+00:00", device_class="timestamp")
    check("sensor.ava_last_diaper_time", "2026-03-01T10:00:00+00:00", device_class="timestamp")
    check("sensor.ava_last_sleep_time", "2026-03-01T11:00:00+00:00", device_class="timestamp")
    check("sensor.ava_last_doctor_visit", "2026-02-20T15:00:00+00:00", device_class="timestamp")
    check("sensor.ava_last_feeding", "formula", device_class="enum")
    check("sensor.ava_last_diaper", "wet", device_class="enum")
    check("sensor.ava_average_bedtime", "unknown")  # nothing to average yet

    # The oz half of Bottle Volume is gone; the ml half kept its ID
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{EMAIL}_ID-AVA_bottle_ml")
    assert not ent_reg.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{EMAIL}_ID-AVA_bottle_oz")
    assert hass.states.get("sensor.ava_bottle_oz") is None

    # Housekeeping entities are kept out of the way
    assert ent_reg.async_get("sensor.ava_info").entity_category is EntityCategory.DIAGNOSTIC
    assert ent_reg.async_get("sensor.ava_pump_summary").entity_category is EntityCategory.DIAGNOSTIC
    for key in ("sync_now", "force_resync"):
        entity_id = ent_reg.async_get_entity_id("button", DOMAIN, f"{DOMAIN}_{EMAIL}_{key}")
        assert ent_reg.async_get(entity_id).entity_category is EntityCategory.CONFIG


async def test_imperial_entry_shows_imperial_units(hass, backend):
    await setup(hass, make_entry(unit_system="imperial"))

    weight = hass.states.get("sensor.ava_weight")
    assert weight.attributes["unit_of_measurement"] == UnitOfMass.POUNDS
    assert float(weight.state) == pytest.approx(10, abs=0.05)
    length = hass.states.get("sensor.ava_length")
    assert length.attributes["unit_of_measurement"] == UnitOfLength.INCHES
    assert float(length.state) == pytest.approx(20, abs=0.05)
    pump = hass.states.get("sensor.ava_last_pump")
    assert pump.attributes["unit_of_measurement"] == UnitOfVolume.FLUID_OUNCES
    assert float(pump.state) == pytest.approx(4, abs=0.05)
    bottles = hass.states.get("sensor.ava_bottle_volume")
    assert bottles.attributes["unit_of_measurement"] == UnitOfVolume.FLUID_OUNCES
    assert float(bottles.state) == pytest.approx(16.9, abs=0.05)
    temperature = hass.states.get("sensor.ava_temperature")
    assert temperature.attributes["unit_of_measurement"] == UnitOfTemperature.FAHRENHEIT
    assert float(temperature.state) == 99.1


async def test_retired_bottle_oz_sensor_is_removed(hass, backend):
    entry = make_entry()
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create("sensor", DOMAIN, f"{DOMAIN}_{EMAIL}_ID-AVA_bottle_oz",
                                      config_entry=entry, suggested_object_id="ava_bottle_oz")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ent_reg.async_get(old.entity_id) is None


async def test_services_date_the_record_at_the_time_given(hass, backend):
    await setup(hass, make_entry())

    await hass.services.async_call(
        DOMAIN, "add_diaper", {"baby_name": "Ava", "time": "2026-03-01T09:30:00+00:00"}, blocking=True)
    assert backend[-1] == ("add_diaper", "ID-AVA", "2026-03-01 09:30:00 +0000")

    # A time with no zone is in Home Assistant's time zone
    await hass.services.async_call(
        DOMAIN, "add_diaper", {"baby_name": "Ava", "time": "2026-03-01 09:30:00"}, blocking=True)
    local = datetime(2026, 3, 1, 9, 30, tzinfo=dt_util.get_default_time_zone())
    assert backend[-1][2] == dt_util.as_utc(local).strftime("%Y-%m-%d %H:%M:%S +0000")

    # With no time the client dates it now
    await hass.services.async_call(DOMAIN, "add_diaper", {"baby_name": "Ava"}, blocking=True)
    assert backend[-1][2] is None


@pytest.mark.parametrize(("unit_system", "imperial"), [("imperial", True), ("metric", False)])
async def test_service_units_follow_the_entry_unless_given(hass, backend, unit_system, imperial):
    await setup(hass, make_entry(unit_system=unit_system))
    base = {"baby_name": "Ava"}

    await hass.services.async_call(DOMAIN, "add_temperature", {**base, "temperature": 37.0}, blocking=True)
    assert backend[-1] == ("add_temperature", "ID-AVA", 37.0, imperial)
    await hass.services.async_call(DOMAIN, "log_growth", {**base, "weight": 4.0}, blocking=True)
    assert backend[-1] == ("log_growth", "ID-AVA", imperial, imperial)

    # What the call says wins
    await hass.services.async_call(
        DOMAIN, "add_temperature", {**base, "temperature": 37.0, "is_fahrenheit": not imperial}, blocking=True)
    assert backend[-1] == ("add_temperature", "ID-AVA", 37.0, not imperial)
    await hass.services.async_call(
        DOMAIN, "log_growth", {**base, "weight": 4.0, "is_english_length_scale": not imperial}, blocking=True)
    assert backend[-1] == ("log_growth", "ID-AVA", imperial, not imperial)


async def test_dismiss_alert_takes_the_insight_alert_types(hass, backend):
    await setup(hass, make_entry())
    for alert_type in ("intake_low", "feed_due", "wake_to_feed", "sleep_due", "wake_overdue"):
        await hass.services.async_call(
            DOMAIN, "dismiss_alert", {"baby_name": "Ava", "alert_type": alert_type}, blocking=True)
    assert hass.states.get("binary_sensor.ava_feed_due").state == "off"  # dismissed while still true
    assert hass.states.get("binary_sensor.ava_intake_low").state == "off"


async def test_version_1_entry_is_migrated_to_its_own_device_id(hass, backend):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=EMAIL, title="Baby Tracker", version=1,
        data={"email": EMAIL, "password": "pw", "scan_interval": 15, "unit_system": "imperial"},
    )
    await setup(hass, entry)

    assert (entry.version, entry.minor_version) == (2, 1)
    assert entry.data["device_uuid"]
    assert entry.data["email"] == EMAIL  # nothing else changed


async def test_version_1_entry_keeps_the_device_id_it_has(hass, backend):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=EMAIL, title="Baby Tracker", version=1,
        data={"email": EMAIL, "password": "pw", "device_uuid": "ha-uuid"},
    )
    await setup(hass, entry)

    assert entry.version == 2
    assert entry.data["device_uuid"] == "ha-uuid"


async def test_diagnostics_hide_credentials(hass, hass_client, backend):
    entry = make_entry()
    await setup(hass, entry)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    data = diagnostics["entry"]["data"]
    assert data["password"] == "**REDACTED**"
    assert data["email"] == "**REDACTED**"
    assert data["device_uuid"] == "**REDACTED**"
    assert data["unit_system"] == "imperial"
    assert "'pw'" not in str(diagnostics) and EMAIL not in str(diagnostics)
    assert diagnostics["babies"] == [
        {"id": "ID-TWIN", "name": "Ann Marie", "dob": ""},
        {"id": "ID-AVA", "name": "Ava", "dob": ""},
    ]
    assert diagnostics["insights"]["ID-AVA"]["intake"]["status"] == "low"
    assert "pending_uploads" in diagnostics and "last_sync" in diagnostics


async def test_diagnostics_include_controls_and_nursing_timers(hass, hass_client, backend):
    entry = make_entry()
    await setup(hass, entry)
    await set_number(hass, "number.ava_bottle_size", 6.5)
    await select_option(hass, "select.ava_bottle_type", "pumped")
    await press(hass, "button.ava_start_nursing_left")

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    controls = diagnostics["controls"]["ID-AVA"]
    assert controls["bottle_size"] == 6.5 and controls["bottle_type"] == "pumped"
    timer = diagnostics["nursing_timers"]["ID-AVA"]
    assert timer["side"] == "left" and timer["seconds"] == {"left": 0.0, "right": 0.0}
    assert timer["started_at"] and timer["segment_started_at"]
    assert "ID-TWIN" not in diagnostics["nursing_timers"]


async def test_baby_photo_is_an_image_entity_in_a_private_folder(hass, hass_client):
    baby = Baby({"objectID": "ID-AVA", "name": "Ava", "dob": "", "dueDay": "", "pictureName": "ava.jpg"})
    photo_dir = hass.config.path("baby_tracker")

    def download(self, picture_name, save_dir):
        assert save_dir == photo_dir  # not under www, which serves files without a login
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, picture_name)
        with open(path, "wb") as photo:
            photo.write(b"photo-bytes")
        return path

    # The real coordinator fetch, against a client with no database yet
    with patch(f"{CORE}.authenticate", return_value={"status": "success"}), \
         patch(f"{CORE}.sync", return_value={"status": "success"}) as sync, \
         patch(f"{CORE}.get_all_babies", return_value=[baby]), \
         patch(f"{CORE}.get_baby_info", return_value=baby), \
         patch(f"{CORE}.download_baby_picture", download):
        await setup(hass, make_entry())

    assert sync.call_args.kwargs["picture_dir"] == os.path.join(photo_dir, "pictures")
    state = hass.states.get("image.ava_photo")
    assert state is not None
    assert "/local/" not in str(state.attributes)

    response = await (await hass_client()).get(state.attributes["entity_picture"])
    assert response.status == 200
    assert await response.read() == b"photo-bytes"
    assert hass.states.get("sensor.ava_info").attributes.get("entity_picture") is None


async def test_baby_without_a_photo_still_has_an_image_entity(hass, backend):
    await setup(hass, make_entry())
    assert hass.states.get("image.ava_photo").state == "unknown"
    assert hass.states.get("image.ann_marie_photo") is not None
    assert hass.states.get("image.ava_photo_landscape") is None  # only babies with a landscape photo get one


def household_fetch(self, photo_dir):
    """Two babies with data: Ann Marie is due to feed first, Ava was fed last, both are asleep."""
    twin = {
        "baby_info": TWIN,
        "insights": {"next_feed": {"predicted_at": "2026-03-01T11:15:00+00:00"}},
        "last_feeding": {"time": "2026-03-01 08:00:00 +0000", "type": "Nursing"},
        "last_sleep": {"time": "2026-03-01 10:45:00 +0000", "is_sleeping": True, "duration": 0},
        "daily_summary": {"total_feedings": 4},
    }
    return [TWIN, AVA], AVA, {}, {"Ann Marie": twin, "Ava": {"baby_info": AVA, **AVA_DATA}}, ACCOUNT, MEDICINES


async def test_household_sensors_look_across_the_babies(hass, backend):
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", household_fetch):
        await setup(hass, make_entry(unit_system="metric"))

    due = hass.states.get("sensor.baby_tracker_next_feed_due")
    assert due.state == "2026-03-01T11:15:00+00:00"  # the earlier of 11:15 and Ava's 12:30
    assert due.attributes["device_class"] == "timestamp"
    assert due.attributes["baby"] == "Ann Marie"
    assert due.attributes["predictions"] == {
        "Ann Marie": "2026-03-01T11:15:00+00:00", "Ava": "2026-03-01T12:30:00+00:00"}
    assert hass.states.get("sensor.baby_tracker_next_feed_baby").state == "Ann Marie"

    last_fed = hass.states.get("sensor.baby_tracker_last_fed_baby")
    assert last_fed.state == "Ava"  # fed at 09:30, after Ann Marie's 08:00
    assert last_fed.attributes["time"] == "2026-03-01T09:30:00+00:00"

    asleep = hass.states.get("sensor.baby_tracker_babies_asleep")
    assert asleep.state == "2" and sorted(asleep.attributes["babies"]) == ["Ann Marie", "Ava"]

    feeds = hass.states.get("sensor.baby_tracker_feeds_today")
    assert feeds.state == "10"  # 4 + 6
    assert feeds.attributes["per_baby"] == {"Ann Marie": 4, "Ava": 6}

    pending = hass.states.get("sensor.baby_tracker_pending_uploads")
    assert pending.state == "2"
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get("sensor.baby_tracker_pending_uploads").entity_category is EntityCategory.DIAGNOSTIC

    # They live on the account's own device, not a baby's
    device = dr.async_get(hass).async_get(ent_reg.async_get("sensor.baby_tracker_next_feed_due").device_id)
    assert device.identifiers == {(DOMAIN, f"{EMAIL}_system")}


async def test_household_sensors_skip_a_baby_with_no_data(hass, backend):
    await setup(hass, make_entry())  # fake_fetch: Ann Marie has nothing, Ava's feed is the only prediction
    assert hass.states.get("sensor.baby_tracker_next_feed_baby").state == "Ava"
    assert hass.states.get("sensor.baby_tracker_babies_asleep").state == "1"
    assert hass.states.get("sensor.baby_tracker_feeds_today").state == "6"


async def test_pumped_milk_inventory_follows_the_unit_setting(hass, backend):
    await setup(hass, make_entry(unit_system="metric"))
    inventory = hass.states.get("sensor.baby_tracker_pumped_milk_inventory")
    assert inventory.state == "479.1"
    assert inventory.attributes["unit_of_measurement"] == UnitOfVolume.MILLILITERS
    assert inventory.attributes["device_class"] == "volume_storage"  # a stock level
    assert inventory.attributes["pumped_ml"] == 588.3 and inventory.attributes["fed_ml"] == 109.2


async def test_pumped_milk_inventory_is_shown_in_ounces_for_imperial(hass, backend):
    await setup(hass, make_entry(unit_system="imperial"))
    inventory = hass.states.get("sensor.baby_tracker_pumped_milk_inventory")
    assert inventory.attributes["unit_of_measurement"] == UnitOfVolume.FLUID_OUNCES
    assert float(inventory.state) == pytest.approx(16.2, abs=0.05)


async def test_derived_sensors(hass, backend):
    await setup(hass, make_entry())

    breast = hass.states.get("sensor.ava_which_breast_next")
    assert breast.state == "right" and breast.attributes["device_class"] == "enum"
    assert breast.attributes["last_side"] == "left" and breast.attributes["last_type"] == "nursing"
    assert breast.attributes["last_time"] == "2026-03-01T08:00:00+00:00"

    dose = hass.states.get("sensor.ava_next_medicine_dose")
    assert dose.state == "2026-03-01T10:00:00+00:00" and dose.attributes["device_class"] == "timestamp"
    assert dose.attributes["medicine_name"] == "Tylenol" and dose.attributes["amount"] == 2.5
    assert dose.attributes["unit"] == "ml" and dose.attributes["last_given"] == "2026-03-01T06:00:00+00:00"

    milestones = hass.states.get("sensor.ava_upcoming_milestones")
    assert milestones.state == "First smile"
    assert milestones.attributes["count"] == 2
    assert milestones.attributes["upcoming"] == [
        {"name": "First smile", "for_age_months": 2}, {"name": "Rolls over", "for_age_months": 5}]
    assert hass.states.get("sensor.ava_upcoming_vaccines").state == "HepB"

    # Nothing known for Ann Marie
    for entity_id in ("which_breast_next", "next_medicine_dose", "upcoming_milestones", "upcoming_vaccines"):
        assert hass.states.get(f"sensor.ann_marie_{entity_id}").state == "unknown", entity_id


async def test_medicine_without_an_interval_has_no_next_dose(hass, backend):
    dose = {"medicine_name": "Vitamin D", "amount": 1.0, "unit": "ml", "last_given": "2026-03-01 06:00:00 +0000",
            "interval_minutes": 0, "next_dose_at": None}
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fetch_with(next_medicine_dose=dose)):
        await setup(hass, make_entry())
    state = hass.states.get("sensor.ava_next_medicine_dose")
    assert state.state == "unknown" and state.attributes["medicine_name"] == "Vitamin D"


async def test_time_based_alerts_follow_the_clock_between_refreshes(hass, backend, freezer):
    fetches = []
    last_fed_3h24m_ago = {"hours_since_last_feeding": 3.4, "last_feeding_time": "2026-03-01T09:00:00+00:00",
                          "time_difference": "3:24:00"}
    fetch = fetch_with(time_since_last_feeding=last_fed_3h24m_ago)

    def counting_fetch(self, photo_dir):
        fetches.append(photo_dir)
        return fetch(self, photo_dir)

    freezer.move_to("2026-03-01 12:20:00+00:00")
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", counting_fetch):
        await setup(hass, make_entry())
        assert hass.states.get("binary_sensor.ava_feed_due").state == "off"  # predicted for 12:30
        assert hass.states.get("binary_sensor.ava_wake_to_feed").state == "off"  # wake by 14:30
        assert hass.states.get("binary_sensor.ava_feeding_overdue").state == "off"  # 3.4 h, over at 3.5
        assert hass.states.get("sensor.ava_time_since_last_feeding").state == "204"

        # 11 minutes pass; the 15-minute refresh is not due yet
        freezer.tick(timedelta(minutes=11))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert len(fetches) == 1  # no refresh, yet the alerts and the sensor moved on
        assert hass.states.get("binary_sensor.ava_feed_due").state == "on"
        assert hass.states.get("binary_sensor.ava_feeding_overdue").state == "on"
        assert hass.states.get("binary_sensor.ava_wake_to_feed").state == "off"
        assert hass.states.get("sensor.ava_time_since_last_feeding").state == "215"


async def test_night_mode_turns_on_when_night_falls(hass, backend, freezer):
    local = dt_util.get_default_time_zone()
    freezer.move_to(dt_util.as_utc(datetime(2026, 3, 1, 18, 59, tzinfo=local)))
    await setup(hass, make_entry())
    assert hass.states.get("binary_sensor.ava_night_mode").state == "off"  # asleep, but it is still day

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.ava_night_mode").state == "on"


@pytest.mark.parametrize(("changes", "event_type"), [
    ({"last_feeding": {"time": "2026-03-01 12:00:00 +0000", "type": "Pumped"}}, "feeding"),
    ({"last_diaper": {"time": "2026-03-01 12:00:00 +0000", "status": "Poopy"}}, "diaper"),
    ({"last_sleep": {"time": "2026-03-01 11:00:00 +0000", "is_sleeping": False, "duration": 50}}, "sleep_end"),
    ({"last_sleep": {"time": "2026-03-01 12:00:00 +0000", "is_sleeping": True, "duration": 0}}, "sleep_start"),
    ({"last_bath": {"time": "2026-03-01 12:00:00 +0000", "bath_type": "Bath"}}, "bath"),
    ({"last_medicine": {"time": "2026-03-01 12:00:00 +0000", "medicine_name": "Tylenol", "amount": 2.5}}, "medicine"),
])
async def test_activity_event_fires_when_something_new_is_found(hass, backend, changes, event_type):
    entry = make_entry()
    await setup(hass, entry)
    assert hass.states.get("event.ava_activity").state == "unknown"  # nothing has happened yet
    bus_events = async_capture_events(hass, f"baby_tracker_{event_type.split('_')[0]}")

    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fetch_with(**changes)):
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()

    state = hass.states.get("event.ava_activity")
    assert state.attributes["event_type"] == event_type
    assert state.attributes["event_types"] == [
        "feeding", "diaper", "sleep_start", "sleep_end", "bath", "medicine", "photo", "undo"]
    assert state.attributes["baby_name"] == "Ava"
    assert state.attributes["time"] == next(iter(changes.values()))["time"]
    assert hass.states.get("event.ann_marie_activity").state == "unknown"  # only Ava's changed

    # The bus events are still fired for feedings, diapers and sleeps
    assert len(bus_events) == (0 if event_type in ("bath", "medicine") else 1)


# ----- latest photo -----

def picture(path, picture_id="PIC1", time="2026-03-01 12:00:00 +0000", **more):
    return {"picture_id": picture_id, "path": path, "thumbnail_path": None, "time": time,
            "object_type": "Joy", "object_id": "JOY1", "kind": "joy", "note": "Smiling", **more}


def write_picture(hass, name, content):
    path = hass.config.path("baby_tracker", "pictures", name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(content)
    return path


async def test_latest_photo_serves_the_newest_picture_with_its_details(hass, hass_client, backend):
    path = write_picture(hass, "pic1.jpg", b"joy-bytes")
    pictures = [picture(path), picture(None, "PIC0", "2026-02-28 12:00:00 +0000", kind="bath")]
    entry = make_entry()
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               fetch_with(latest_picture=pictures[0], pictures=pictures)):
        await setup(hass, entry)

    state = hass.states.get("image.ava_latest_photo")
    assert state is not None and state.state != "unknown"
    assert state.attributes["kind"] == "joy"
    assert state.attributes["note"] == "Smiling"
    assert state.attributes["object_type"] == "Joy"
    assert state.attributes["object_id"] == "JOY1"
    assert state.attributes["picture_id"] == "PIC1"
    assert state.attributes["time"] == "2026-03-01 12:00:00 +0000"
    assert state.attributes["recent"] == [
        {"picture_id": "PIC1", "kind": "joy", "time": "2026-03-01 12:00:00 +0000"},
        {"picture_id": "PIC0", "kind": "bath", "time": "2026-02-28 12:00:00 +0000"},
    ]
    assert str(path) not in str(state.attributes)  # file paths stay internal

    response = await (await hass_client()).get(state.attributes["entity_picture"])
    assert response.status == 200
    assert await response.read() == b"joy-bytes"
    unique_id = er.async_get(hass).async_get("image.ava_latest_photo").unique_id
    assert unique_id == f"{DOMAIN}_{EMAIL}_ID-AVA_latest_photo"


async def test_latest_photo_is_unknown_without_a_picture(hass, backend):
    await setup(hass, make_entry())
    assert hass.states.get("image.ava_latest_photo").state == "unknown"
    assert hass.states.get("image.ann_marie_latest_photo").state == "unknown"


async def test_latest_photo_timestamp_changes_with_a_new_picture(hass, backend):
    first = write_picture(hass, "pic1.jpg", b"one")
    second = write_picture(hass, "pic2.jpg", b"two")
    entry = make_entry()
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               fetch_with(latest_picture=picture(first))):
        await setup(hass, entry)
    before = hass.states.get("image.ava_latest_photo").state

    newer = picture(second, "PIC2", "2026-03-01 13:00:00 +0000")
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               fetch_with(latest_picture=newer)):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=5))
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()
    after = hass.states.get("image.ava_latest_photo")
    assert after.state != before
    assert after.attributes["picture_id"] == "PIC2"


async def test_photo_event_fires_once_for_a_new_picture(hass, backend):
    first = picture("/x/pic1.jpg")
    entry = make_entry()
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               fetch_with(latest_picture=first)):
        await setup(hass, entry)
    assert hass.states.get("event.ava_activity").state == "unknown"  # the first refresh announces nothing

    newer = picture("/x/pic2.jpg", "PIC2", "2026-03-01 13:00:00 +0000", kind="bath", object_type="Bath",
                    object_id="BATH1")
    coordinator = hass.data[DOMAIN][entry.entry_id]
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               fetch_with(latest_picture=newer)):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        state = hass.states.get("event.ava_activity")
        assert state.attributes["event_type"] == "photo"
        assert state.attributes["kind"] == "bath"
        assert state.attributes["time"] == "2026-03-01 13:00:00 +0000"
        assert state.attributes["object_type"] == "Bath"
        assert state.attributes["object_id"] == "BATH1"
        assert state.attributes["picture_id"] == "PIC2"
        fired_at = state.state

        # The same picture again is not new
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get("event.ava_activity").state == fired_at


async def test_an_older_picture_becoming_the_latest_is_not_announced(hass, backend):
    entry = make_entry()
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               fetch_with(latest_picture=picture("/x/pic2.jpg", "PIC2", "2026-03-01 13:00:00 +0000"))):
        await setup(hass, entry)
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               fetch_with(latest_picture=picture("/x/pic1.jpg", "PIC1", "2026-03-01 12:00:00 +0000"))):
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("event.ava_activity").state == "unknown"


async def test_diagnostics_are_unaffected_by_pictures(hass, hass_client, backend):
    entry = make_entry()
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               fetch_with(latest_picture=picture("/secret/pic1.jpg"), pictures=[picture("/secret/pic1.jpg")])):
        await setup(hass, entry)
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)
    assert "/secret/" not in str(diagnostics)
    assert diagnostics["insights"]["ID-AVA"]["intake"]["status"] == "low"


async def test_unchanged_data_fires_no_activity_event(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("event.ava_activity").state == "unknown"


async def test_an_older_record_becoming_the_latest_is_not_announced(hass, backend):
    """After an undo the previous feed is the newest again; that is not a new feeding."""
    entry = make_entry()
    await setup(hass, entry)
    older = {"last_feeding": {"time": "2026-03-01 08:00:00 +0000", "type": "Nursing"},
             "last_diaper": {"time": "2026-03-01 07:00:00 +0000", "status": "Wet"}}
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fetch_with(**older)):
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("event.ava_activity").state == "unknown"


async def test_calendar_returns_a_days_feed_and_sleep(hass, backend):
    await setup(hass, make_entry())
    feed = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)
    nap = datetime(2026, 3, 1, 11, 0, tzinfo=UTC)
    asked = []

    def get_events(self, baby_id, start, end):
        asked.append(baby_id)
        return [
            {"start": feed, "end": feed + timedelta(minutes=15), "summary": "Formula 4 oz",
             "kind": "feeding", "description": ""},
            {"start": nap, "end": nap + timedelta(minutes=80), "summary": "Sleep (1h 20m)",
             "kind": "sleep", "description": "Crib"},
        ]

    with patch(f"{CORE}.get_events_between", get_events):
        result = await hass.services.async_call(
            "calendar", "get_events",
            {"entity_id": "calendar.ava_calendar",
             "start_date_time": "2026-03-01T00:00:00+00:00", "end_date_time": "2026-03-02T00:00:00+00:00"},
            blocking=True, return_response=True)

    assert asked == ["ID-AVA"]
    events = result["calendar.ava_calendar"]["events"]
    assert [e["summary"] for e in events] == ["Formula 4 oz", "Sleep (1h 20m)"]
    assert events[1]["description"] == "Crib"
    assert hass.states.get("calendar.ann_marie_calendar") is not None


async def test_calendars_current_event_is_the_most_recent_one(hass, backend, freezer):
    freezer.move_to("2026-03-01 12:00:00+00:00")
    nap = datetime(2026, 3, 1, 11, 0, tzinfo=UTC)
    latest = {"start": nap, "end": nap + timedelta(minutes=80), "summary": "Sleep (1h 20m)",
              "kind": "sleep", "description": ""}
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fetch_with(last_event=latest)):
        await setup(hass, make_entry())

    calendar = hass.states.get("calendar.ava_calendar")
    assert calendar.state == "on"  # the nap runs until 12:20
    assert calendar.attributes["message"] == "Sleep (1h 20m)"
    assert hass.states.get("calendar.ann_marie_calendar").state == "off"
# ----- controls, nursing timer, activities, thresholds, robustness and repairs -----

async def press(hass, entity_id):
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)


async def set_number(hass, entity_id, value):
    await hass.services.async_call("number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True)


async def select_option(hass, entity_id, option):
    await hass.services.async_call("select", "select_option", {"entity_id": entity_id, "option": option},
                                   blocking=True)


def coordinator_for(hass, entry):
    return hass.data[DOMAIN][entry.entry_id]


def allow_another_press(hass, entry):
    """Forget when buttons were pressed, so a test can press one again within the debounce window."""
    coordinator_for(hass, entry)._button_presses.clear()


async def test_controls_follow_the_unit_setting(hass, backend):
    await setup(hass, make_entry(unit_system="imperial"))

    size = hass.states.get("number.ava_bottle_size")
    assert float(size.state) == 4
    assert size.attributes["unit_of_measurement"] == "oz"
    assert (size.attributes["min"], size.attributes["max"], size.attributes["step"]) == (1, 12, 0.5)
    assert size.attributes["mode"] == "box"
    assert hass.states.get("number.ann_marie_bottle_size") is not None  # every baby has the controls

    # It starts at the usual dose of the first medicine, whose unit it shows
    assert float(hass.states.get("number.ava_medicine_amount").state) == 3.75
    assert hass.states.get("number.ava_medicine_amount").attributes["step"] == 0.1
    assert hass.states.get("number.ava_medicine_amount").attributes["unit"] == "ml"
    assert float(hass.states.get("number.ava_tummy_time_minutes").state) == 15

    bottle_type = hass.states.get("select.ava_bottle_type")
    assert bottle_type.state == "formula"
    assert bottle_type.attributes["options"] == ["formula", "pumped"]
    medicine = hass.states.get("select.ava_medicine")
    assert medicine.attributes["options"] == ["Tylenol", "Vitamin D"]
    assert medicine.state == "Tylenol"


async def test_metric_bottle_size_is_in_ml(hass, backend):
    await setup(hass, make_entry(unit_system="metric"))
    size = hass.states.get("number.ava_bottle_size")
    assert float(size.state) == 120
    assert size.attributes["unit_of_measurement"] == "mL"
    assert (size.attributes["min"], size.attributes["max"], size.attributes["step"]) == (30, 360, 10)


async def test_add_bottle_logs_the_amount_and_kind_chosen(hass, backend):
    entry = make_entry()
    await setup(hass, entry)

    await set_number(hass, "number.ava_bottle_size", 6.5)
    await press(hass, "button.ava_add_bottle")
    assert backend[-1] == ("add_formula", "ID-AVA", 6.5, True)

    await select_option(hass, "select.ava_bottle_type", "pumped")
    await set_number(hass, "number.ava_bottle_size", 3)
    allow_another_press(hass, entry)
    await press(hass, "button.ava_add_bottle")
    assert backend[-1] == ("add_pumped", "ID-AVA", 3.0, True)

    # Each baby has its own settings
    await press(hass, "button.ann_marie_add_bottle")
    assert backend[-1] == ("add_formula", "ID-TWIN", 4.0, True)


async def test_add_bottle_in_a_metric_entry_logs_ml(hass, backend):
    await setup(hass, make_entry(unit_system="metric"))
    await set_number(hass, "number.ava_bottle_size", 150)
    await press(hass, "button.ava_add_bottle")
    assert backend[-1] == ("add_formula", "ID-AVA", 150.0, False)


async def test_give_medicine_logs_the_selected_medicine_and_amount(hass, backend):
    entry = make_entry()
    await setup(hass, entry)

    # Until one is chosen, the first medicine and its usual dose
    await press(hass, "button.ava_give_medicine")
    assert backend[-1] == ("add_medicine", "ID-AVA", "MED-TYLENOL", 3.75)

    await select_option(hass, "select.ava_medicine", "Vitamin D")
    await set_number(hass, "number.ava_medicine_amount", 2.5)
    allow_another_press(hass, entry)
    await press(hass, "button.ava_give_medicine")
    assert backend[-1] == ("add_medicine", "ID-AVA", "MED-VITD", 2.5)
    assert hass.states.get("select.ava_medicine").state == "Vitamin D"


async def test_controls_are_restored_after_a_restart(hass, backend):
    mock_restore_cache_with_extra_data(hass, [
        (State("number.ava_bottle_size", "7.5"),
         {"native_max_value": 12, "native_min_value": 1, "native_step": 0.5,
          "native_unit_of_measurement": "oz", "native_value": 7.5}),
        # Saved in another unit, so meaningless here: the restored medicine's usual dose stands
        (State("number.ava_medicine_amount", "9"),
         {"native_max_value": 100, "native_min_value": 0.1, "native_step": 0.1,
          "native_unit_of_measurement": "mL", "native_value": 9}),
        (State("select.ava_bottle_type", "pumped"), {}),
        (State("select.ava_medicine", "Vitamin D"), {}),
    ])
    await setup(hass, make_entry())

    assert float(hass.states.get("number.ava_bottle_size").state) == 7.5
    assert float(hass.states.get("number.ava_medicine_amount").state) == 1.0  # Vitamin D's
    assert hass.states.get("select.ava_bottle_type").state == "pumped"
    assert hass.states.get("select.ava_medicine").state == "Vitamin D"
    await press(hass, "button.ava_add_bottle")
    assert backend[-1] == ("add_pumped", "ID-AVA", 7.5, True)


async def test_a_bottle_size_saved_in_another_unit_is_not_restored(hass, backend):
    mock_restore_cache_with_extra_data(hass, [
        (State("number.ava_bottle_size", "150"),
         {"native_max_value": 360, "native_min_value": 30, "native_step": 10,
          "native_unit_of_measurement": "mL", "native_value": 150}),
    ])
    await setup(hass, make_entry(unit_system="imperial"))
    assert float(hass.states.get("number.ava_bottle_size").state) == 4


async def test_pressing_a_button_twice_quickly_logs_once(hass, backend):
    entry = make_entry()
    await setup(hass, entry)

    for _ in range(3):
        await press(hass, "button.ava_add_wet_diaper")
    assert [call[0] for call in backend].count("add_diaper") == 1

    # Another button isn't affected, and the same one works again after the window
    await press(hass, "button.ava_add_dirty_diaper")
    assert [call[0] for call in backend].count("add_diaper") == 2
    allow_another_press(hass, entry)
    await press(hass, "button.ava_add_wet_diaper")
    assert [call[0] for call in backend].count("add_diaper") == 3


async def test_the_fixed_size_buttons_are_off_for_new_installs(hass, backend):
    await setup(hass, make_entry())
    ent_reg = er.async_get(hass)
    for unique_id in ("add_4oz_bottle", "give_tylenol"):
        entity_id = ent_reg.async_get_entity_id("button", DOMAIN, f"{DOMAIN}_{EMAIL}_ID-AVA_{unique_id}")
        assert ent_reg.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get("button.ava_add_bottle") is not None


async def test_nursing_timer_logs_the_minutes_on_each_side(hass, backend, freezer):
    await setup(hass, make_entry())
    timer = "binary_sensor.ava_nursing"
    assert hass.states.get(timer).state == "off"

    started = dt_util.utcnow()
    await press(hass, "button.ava_start_nursing_left")
    assert hass.states.get(timer).state == "on"
    assert hass.states.get(timer).attributes["side"] == "left"
    assert hass.states.get(timer).attributes["started_at"] == started.isoformat()

    freezer.tick(timedelta(minutes=10))
    await press(hass, "button.ava_start_nursing_right")  # switch sides
    assert hass.states.get(timer).attributes["side"] == "right"

    freezer.tick(timedelta(minutes=6))
    await press(hass, "button.ava_end_nursing")

    # Dated when it started: 10 minutes left, 6 right, finished on the right (2)
    assert backend[-1] == ("add_nursing", "ID-AVA", started.strftime("%Y-%m-%d %H:%M:%S +0000"), 10, 6, 2)
    assert hass.states.get(timer).state == "off"
    assert hass.states.get(timer).attributes.get("side") is None


async def test_a_very_short_nursing_session_counts_a_minute(hass, backend, freezer):
    await setup(hass, make_entry())
    await press(hass, "button.ava_start_nursing_right")
    freezer.tick(timedelta(seconds=10))
    await press(hass, "button.ava_end_nursing")
    assert backend[-1][3:] == (0, 1, 2)


async def test_ending_nursing_with_no_timer_is_refused(hass, backend):
    await setup(hass, make_entry())
    with pytest.raises(ServiceValidationError):
        await press(hass, "button.ava_end_nursing")
    assert not [call for call in backend if call[0] == "add_nursing"]


async def test_a_failed_nursing_log_keeps_the_timer_running(hass, backend):
    await setup(hass, make_entry())
    await press(hass, "button.ava_start_nursing_left")
    with patch(f"{CORE}.add_nursing", return_value={"status": "error", "message": "offline"}), \
         pytest.raises(HomeAssistantError):
        await press(hass, "button.ava_end_nursing")
    assert hass.states.get("binary_sensor.ava_nursing").state == "on"


async def test_nursing_timers_are_per_baby(hass, backend):
    await setup(hass, make_entry())
    await press(hass, "button.ava_start_nursing_left")
    assert hass.states.get("binary_sensor.ava_nursing").state == "on"
    assert hass.states.get("binary_sensor.ann_marie_nursing").state == "off"


async def test_log_activity_service_and_tummy_time_button(hass, backend):
    entry = make_entry()
    await setup(hass, entry)

    await hass.services.async_call(
        DOMAIN, "log_activity",
        {"baby_name": "Ava", "activity_name": "Reading", "duration": 20, "time": "2026-03-01T09:30:00+00:00"},
        blocking=True)
    assert backend[-1] == ("add_activity", "ID-AVA", "Reading", 20, "2026-03-01 09:30:00 +0000")

    # Tummy time is the default activity
    await hass.services.async_call(DOMAIN, "log_activity", {"baby_name": "Ava", "duration": 5}, blocking=True)
    assert backend[-1][:4] == ("add_activity", "ID-AVA", "Tummy Time", 5)

    # The button logs the Tummy Time Minutes number (15 until changed)
    await press(hass, "button.ava_log_tummy_time")
    assert backend[-1][:4] == ("add_activity", "ID-AVA", "Tummy Time", 15)
    await set_number(hass, "number.ava_tummy_time_minutes", 25)
    allow_another_press(hass, entry)
    await press(hass, "button.ava_log_tummy_time")
    assert backend[-1][:4] == ("add_activity", "ID-AVA", "Tummy Time", 25)

    with pytest.raises(ServiceValidationError):  # two babies and none chosen
        await hass.services.async_call(DOMAIN, "log_activity", {"duration": 5}, blocking=True)


async def test_last_activity_sensor(hass, backend):
    await setup(hass, make_entry())
    last = hass.states.get("sensor.ava_last_activity")
    assert last.state == "Tummy Time"
    assert last.attributes["duration"] == 15
    assert last.attributes["time"] == "2026-03-01 10:30:00 +0000"
    assert hass.states.get("sensor.ann_marie_last_activity").state == "unknown"


async def test_add_solids_service(hass, backend):
    await setup(hass, make_entry())

    await hass.services.async_call(
        DOMAIN, "add_solids", {"baby_name": "Ava", "food_name": "banana", "amount": 2, "unit": "tbsp"},
        blocking=True)
    assert backend[-1] == ("add_other_feed", "ID-AVA", "FOOD-BANANA", 2.0, "tbsp", True)

    await hass.services.async_call(
        DOMAIN, "add_solids",
        {"baby_name": "Ava", "food_name": "Banana", "amount": 30, "unit": "g", "is_english_measure": False},
        blocking=True)
    assert backend[-1] == ("add_other_feed", "ID-AVA", "FOOD-BANANA", 30.0, "g", False)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "add_solids", {"baby_name": "Ava", "food_name": "Dragonfruit", "amount": 1}, blocking=True)


async def test_writes_ask_for_a_debounced_refresh(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)
    with patch.object(coordinator, "async_request_refresh") as request, \
         patch.object(coordinator, "async_refresh") as refresh:
        await hass.services.async_call(DOMAIN, "add_diaper", {"baby_name": "Ava"}, blocking=True)
        await hass.services.async_call(DOMAIN, "log_activity", {"baby_name": "Ava", "duration": 5}, blocking=True)
    assert request.call_count == 2
    refresh.assert_not_called()


async def test_feeding_overdue_uses_the_age_based_hours_by_default(hass, backend):
    # Ava last fed 2.5 hours ago; the default for a baby of unknown age is 3.5 hours
    await setup(hass, make_entry())
    overdue = hass.states.get("binary_sensor.ava_feeding_overdue")
    assert overdue.state == "off"
    assert overdue.attributes["threshold"] == 3.5


async def test_feeding_overdue_turns_on_after_two_hours_when_set_to_two(hass, backend):
    entry = make_entry(options={"feeding_overdue_hours": 2})
    await setup(hass, entry)
    overdue = hass.states.get("binary_sensor.ava_feeding_overdue")
    assert overdue.state == "on"
    assert overdue.attributes["threshold"] == 2
    assert overdue.attributes["age_bracket"] == "custom"

    # 0 means by age again
    hass.config_entries.async_update_entry(entry, options={"feeding_overdue_hours": 0})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.ava_feeding_overdue").state == "off"


async def test_fever_threshold_is_in_the_entrys_unit(hass, backend, freezer):
    # Ava's last reading was 99.1 F (37.3 C), taken at 06:00
    freezer.move_to("2026-03-01 08:00:00+00:00")
    await setup(hass, make_entry(options={"fever_threshold": 99.0}))
    fever = hass.states.get("binary_sensor.ava_fever")
    assert fever.state == "on" and fever.attributes["threshold"] == 99.0


async def test_an_old_temperature_reading_no_longer_raises_the_fever_alert(hass, backend, freezer):
    freezer.move_to("2026-03-01 08:00:00+00:00")
    await setup(hass, make_entry(options={"fever_threshold": 99.0}))
    assert hass.states.get("binary_sensor.ava_fever").state == "on"

    # 24 hours after the 06:00 reading it stops counting, with no new refresh
    freezer.move_to("2026-03-02 06:01:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    fever = hass.states.get("binary_sensor.ava_fever")
    assert fever.state == "off" and fever.attributes["current_value"] is None


async def test_long_sleep_follows_the_clock_between_refreshes(hass, backend, freezer):
    # Ava fell asleep at 11:00; for a baby of unknown age the limit is 4 hours
    freezer.move_to("2026-03-01 12:00:00+00:00")
    await setup(hass, make_entry())
    sleep = hass.states.get("binary_sensor.ava_long_sleep")
    assert sleep.state == "off" and sleep.attributes["current_value"] == 1.0

    freezer.move_to("2026-03-01 15:30:00+00:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    sleep = hass.states.get("binary_sensor.ava_long_sleep")
    assert sleep.state == "on" and sleep.attributes["current_value"] == 4.5


async def test_fever_threshold_in_celsius(hass, backend, freezer):
    freezer.move_to("2026-03-01 08:00:00+00:00")
    await setup(hass, make_entry(unit_system="metric", options={"fever_threshold": 37.0}))
    fever = hass.states.get("binary_sensor.ava_fever")
    assert fever.state == "on" and fever.attributes["current_value"] == 37.3


async def test_the_default_fever_threshold_is_100_4_f_or_38_c(hass, backend):
    await setup(hass, make_entry())
    fever = hass.states.get("binary_sensor.ava_fever")
    assert fever.state == "off" and fever.attributes["threshold"] == 100.4


async def test_default_night_hours_are_7_pm_to_7_am(hass, backend, freezer):
    # Ava is asleep; it is noon
    freezer.move_to(datetime(2026, 3, 1, 12, 0, tzinfo=dt_util.get_default_time_zone()))
    await setup(hass, make_entry())
    night = hass.states.get("binary_sensor.ava_night_mode")
    assert night.state == "off"
    assert (night.attributes["night_start_hour"], night.attributes["night_end_hour"]) == (19, 7)


async def test_night_hours_set_in_the_options_apply(hass, backend, freezer):
    freezer.move_to(datetime(2026, 3, 1, 12, 0, tzinfo=dt_util.get_default_time_zone()))
    await setup(hass, make_entry(options={"night_start_hour": 10, "night_end_hour": 14}))
    night = hass.states.get("binary_sensor.ava_night_mode")
    assert night.state == "on"
    assert (night.attributes["night_start_hour"], night.attributes["night_end_hour"]) == (10, 14)


async def test_night_hours_can_wrap_midnight(hass, backend, freezer):
    freezer.move_to(datetime(2026, 3, 1, 12, 0, tzinfo=dt_util.get_default_time_zone()))
    await setup(hass, make_entry(options={"night_start_hour": 22, "night_end_hour": 13}))
    assert hass.states.get("binary_sensor.ava_night_mode").state == "on"


async def test_unsent_records_raise_a_repair_after_several_refreshes_and_clear_when_sent(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)
    registry = ir.async_get(hass)

    coordinator.pending_uploads = 2
    for _ in range(3):
        await coordinator.async_refresh()
    assert registry.async_get_issue(DOMAIN, "uploads_pending") is None  # it takes more than 3

    await coordinator.async_refresh()
    issue = registry.async_get_issue(DOMAIN, "uploads_pending")
    assert issue is not None and issue.severity is ir.IssueSeverity.WARNING and issue.is_fixable is False
    assert issue.translation_placeholders == {"count": "2"}

    coordinator.pending_uploads = 0
    await coordinator.async_refresh()
    assert registry.async_get_issue(DOMAIN, "uploads_pending") is None


async def test_a_reset_account_raises_a_repair_until_a_sync_succeeds(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "account_reset") is None

    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               side_effect=AccountResetError("account 1 is now 2")):
        await coordinator.async_refresh()
    issue = registry.async_get_issue(DOMAIN, "account_reset")
    assert issue is not None and issue.severity is ir.IssueSeverity.ERROR and issue.is_fixable is False
    assert not coordinator.last_update_success

    await coordinator.async_refresh()  # a sync that works again (the fixture's fetch)
    assert coordinator.last_update_success
    assert registry.async_get_issue(DOMAIN, "account_reset") is None


# ----- review fixes -----

async def test_a_running_nursing_timer_survives_a_reload(hass, backend, freezer):
    entry = make_entry()
    await setup(hass, entry)
    started = dt_util.utcnow()
    await press(hass, "button.ava_start_nursing_left")
    freezer.tick(timedelta(minutes=8))

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    timer = hass.states.get("binary_sensor.ava_nursing")
    assert timer.state == "on"
    assert timer.attributes["side"] == "left" and timer.attributes["started_at"] == started.isoformat()
    freezer.tick(timedelta(minutes=4))
    await press(hass, "button.ava_end_nursing")
    assert backend[-1] == ("add_nursing", "ID-AVA", started.strftime("%Y-%m-%d %H:%M:%S +0000"), 12, 0, 1)
    assert hass.states.get("binary_sensor.ava_nursing").state == "off"


async def test_an_ended_nursing_timer_does_not_come_back_after_a_reload(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    await press(hass, "button.ava_start_nursing_left")
    await press(hass, "button.ava_end_nursing")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.ava_nursing").state == "off"


async def test_a_forgotten_nursing_timer_is_dropped_when_loaded(hass, backend, hass_storage):
    entry = make_entry()
    entry.add_to_hass(hass)
    long_ago = (dt_util.utcnow() - timedelta(days=3)).isoformat()
    key = f"{DOMAIN}.{entry.entry_id}.nursing"
    hass_storage[key] = {
        "version": 1, "minor_version": 1, "key": key,
        "data": {"ID-AVA": {"side": "left", "started_at": long_ago, "segment_started_at": long_ago,
                               "seconds": {"left": 0.0, "right": 0.0}}},
    }
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.ava_nursing").state == "off"


async def test_a_failed_press_can_be_tried_again_at_once(hass, backend):
    await setup(hass, make_entry())
    with patch(f"{CORE}.add_diaper", return_value={"status": "error", "message": "offline"}), \
         pytest.raises(HomeAssistantError):
        await press(hass, "button.ava_add_wet_diaper")

    await press(hass, "button.ava_add_wet_diaper")  # not swallowed by the debounce
    assert backend[-1][:2] == ("add_diaper", "ID-AVA")

    # A press that worked is still debounced
    logged = len(backend)
    await press(hass, "button.ava_add_wet_diaper")
    assert len(backend) == logged


# ----- undo and delete -----

async def test_undo_button_deletes_the_newest_entry(hass, backend):
    await setup(hass, make_entry())
    bus_events = async_capture_events(hass, "baby_tracker_undo")

    await press(hass, "button.ava_undo_last_entry")
    await hass.async_block_till_done()

    assert backend[-1] == ("undo_last", "ID-AVA", 24.0)
    # It is announced like the other writes: on the bus and on the baby's Activity event
    assert len(bus_events) == 1 and bus_events[0].data["kind"] == "wet diaper"
    state = hass.states.get("event.ava_activity")
    assert state.attributes["event_type"] == "undo"
    assert state.attributes["object_type"] == "Diaper" and state.attributes["object_id"] == "DIAPER-1"
    assert hass.states.get("event.ann_marie_activity").state == "unknown"
    # Each baby has the button
    assert hass.states.get("button.ann_marie_undo_last_entry") is not None


async def test_undo_button_is_debounced_so_it_cannot_delete_two_entries(hass, backend):
    await setup(hass, make_entry())
    for _ in range(3):
        await press(hass, "button.ava_undo_last_entry")
    assert [call[0] for call in backend].count("undo_last") == 1


async def test_undo_with_nothing_to_undo_is_refused(hass, backend):
    await setup(hass, make_entry())
    nothing = {"status": "error", "message": "Nothing to undo"}
    with patch(f"{CORE}.undo_last", return_value=nothing), pytest.raises(ServiceValidationError) as err:
        await press(hass, "button.ava_undo_last_entry")
    assert err.value.translation_key == "nothing_to_undo"
    assert err.value.translation_placeholders == {"hours": "24"}

    # A refused press is not debounced, and fires no event
    assert hass.states.get("event.ava_activity").state == "unknown"
    await press(hass, "button.ava_undo_last_entry")
    assert backend[-1][0] == "undo_last"


async def test_undo_last_service(hass, backend):
    await setup(hass, make_entry())

    await hass.services.async_call(DOMAIN, "undo_last", {"baby_name": "Ava", "within_hours": 6}, blocking=True)
    assert backend[-1] == ("undo_last", "ID-AVA", 6.0)

    await hass.services.async_call(DOMAIN, "undo_last", {"baby_name": "Ann Marie"}, blocking=True)
    assert backend[-1] == ("undo_last", "ID-TWIN", 24.0)  # the default window

    with pytest.raises(ServiceValidationError):  # two babies and none chosen
        await hass.services.async_call(DOMAIN, "undo_last", {}, blocking=True)

    # Any other failure is an error, not a validation problem
    with patch(f"{CORE}.undo_last", return_value={"status": "error", "message": "Not authenticated"}), \
         pytest.raises(HomeAssistantError) as err:
        await hass.services.async_call(DOMAIN, "undo_last", {"baby_name": "Ava"}, blocking=True)
    assert not isinstance(err.value, ServiceValidationError)


async def test_delete_record_service(hass, backend):
    await setup(hass, make_entry())
    bus_events = async_capture_events(hass, "baby_tracker_undo")

    # No baby needed: a record's type and ID are enough
    await hass.services.async_call(
        DOMAIN, "delete_record", {"object_type": "Formula", "object_id": "FORMULA-1"}, blocking=True)
    assert backend[-1] == ("delete_record", "Formula", "FORMULA-1")
    assert not bus_events

    # With a baby, the deletion is reported on that baby's Activity event
    await hass.services.async_call(
        DOMAIN, "delete_record",
        {"baby_name": "Ava", "object_type": "Diaper", "object_id": "DIAPER-1"}, blocking=True)
    await hass.async_block_till_done()
    assert backend[-1] == ("delete_record", "Diaper", "DIAPER-1")
    assert len(bus_events) == 1 and bus_events[0].data["object_id"] == "DIAPER-1"
    assert hass.states.get("event.ava_activity").attributes["event_type"] == "undo"

    with pytest.raises(vol.Invalid):  # only the record types the app has
        await hass.services.async_call(
            DOMAIN, "delete_record", {"object_type": "Pizza", "object_id": "X"}, blocking=True)


async def test_delete_record_reports_what_the_client_refused(hass, backend):
    await setup(hass, make_entry())
    refused = {"status": "error", "message": "No Diaper record with ID NOPE"}
    with patch(f"{CORE}.delete_record", return_value=refused), pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "delete_record", {"object_type": "Diaper", "object_id": "NOPE"}, blocking=True)
    assert err.value.translation_key == "delete_failed"
    assert err.value.translation_placeholders == {
        "object_type": "Diaper", "object_id": "NOPE", "error": "No Diaper record with ID NOPE"}


# ----- photos on entries (log_joy, attach_photo) -----

@pytest.fixture
def photo_folder(hass):
    """The integration's private folder, with a photo in it, and www / media allowed as Home Assistant has them."""
    own = hass.config.path("baby_tracker")
    os.makedirs(own, exist_ok=True)
    path = os.path.join(own, "first-smile.jpg")
    with open(path, "wb") as handle:
        handle.write(b"jpeg bytes")
    allowed = set(hass.config.allowlist_external_dirs)
    hass.config.allowlist_external_dirs = {hass.config.path("www"), hass.config.path("media")}
    yield path
    hass.config.allowlist_external_dirs = allowed
    os.remove(path)


async def test_log_joy_service_without_a_photo(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)

    await hass.services.async_call(
        DOMAIN, "log_joy", {"baby_name": "Ava", "note": "giggles", "time": "2026-03-01 09:30:00"}, blocking=True)
    call = backend[-1]
    assert call[:3] == ("add_joy", "ID-AVA", "giggles")
    assert call[3].endswith("+0000") and call[4] is None  # a sync-format time, and no photo
    assert call[5] == coordinator.picture_dir  # where the client keeps the photos

    with patch(f"{CORE}.add_joy", return_value={"status": "error", "message": "Not authenticated"}), \
         pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "log_joy", {"baby_name": "Ava"}, blocking=True)


async def test_log_joy_service_with_a_photo_file(hass, backend, photo_folder):
    await setup(hass, make_entry())
    await hass.services.async_call(
        DOMAIN, "log_joy", {"baby_name": "Ava", "note": "smile", "photo": photo_folder}, blocking=True)
    assert backend[-1][:3] == ("add_joy", "ID-AVA", "smile")
    assert backend[-1][4] == os.path.realpath(photo_folder)

    # www and media work when Home Assistant allows them
    www = hass.config.path("www")
    os.makedirs(www, exist_ok=True)
    in_www = os.path.join(www, "snap.jpg")
    with open(in_www, "wb") as handle:
        handle.write(b"x")
    try:
        await hass.services.async_call(
            DOMAIN, "log_joy", {"baby_name": "Ava", "photo": in_www}, blocking=True)
        assert backend[-1][4] == os.path.realpath(in_www)
        hass.config.allowlist_external_dirs = set()  # no longer an allowed path
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(
                DOMAIN, "log_joy", {"baby_name": "Ava", "photo": in_www}, blocking=True)
        assert err.value.translation_key == "photo_path_not_allowed"
    finally:
        os.remove(in_www)


async def test_photo_paths_outside_the_allowed_folders_are_refused(hass, backend, photo_folder, tmp_path):
    await setup(hass, make_entry())
    outside = tmp_path / "elsewhere.jpg"
    outside.write_bytes(b"x")
    sneaky = os.path.join(os.path.dirname(photo_folder), "..", "secrets.yaml")
    calls_before = len(backend)
    for path in (str(outside), sneaky, "/etc/passwd"):
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(DOMAIN, "log_joy", {"baby_name": "Ava", "photo": path}, blocking=True)
        assert err.value.translation_key == "photo_path_not_allowed"
        assert err.value.translation_placeholders == {"path": path}
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(DOMAIN, "attach_photo", {
            "object_type": "Diaper", "object_id": "DIAPER-1", "photo": str(outside)}, blocking=True)
    assert err.value.translation_key == "photo_path_not_allowed"
    assert len(backend) == calls_before  # nothing reached the client

    with pytest.raises(ServiceValidationError) as err:  # allowed place, no such file
        await hass.services.async_call(DOMAIN, "log_joy", {
            "baby_name": "Ava", "photo": os.path.join(os.path.dirname(photo_folder), "nope.jpg")}, blocking=True)
    assert err.value.translation_key == "photo_not_found"


async def test_log_joy_takes_a_camera_snapshot_and_cleans_up(hass, backend):
    from homeassistant.components.camera import Image

    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)
    seen = {}

    def add_joy(baby_id, note, time_str, photo_path, picture_dir):
        seen["path"] = photo_path
        with open(photo_path, "rb") as handle:  # the client reads the file during the call
            seen["bytes"] = handle.read()
        return {"status": "success", "objectID": "JOY-1", "queued": False}

    with patch("homeassistant.components.camera.async_get_image",
               return_value=Image("image/jpeg", b"snapshot bytes")) as snapshot, \
         patch(f"{CORE}.add_joy", side_effect=add_joy):
        await hass.services.async_call(
            DOMAIN, "log_joy", {"baby_name": "Ava", "note": "front door", "camera_entity": "camera.nursery"},
            blocking=True)
    snapshot.assert_awaited_once_with(hass, "camera.nursery")
    assert seen["bytes"] == b"snapshot bytes"
    assert seen["path"].startswith(coordinator.photo_dir)  # the private folder, not a public one
    assert not os.path.exists(seen["path"])  # a snapshot is only needed while the entry is made

    # A camera that can't produce a picture is a clear error, and nothing is logged
    with patch("homeassistant.components.camera.async_get_image", side_effect=HomeAssistantError("offline")), \
         pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN, "log_joy", {"baby_name": "Ava", "camera_entity": "camera.nursery"}, blocking=True)
    assert err.value.translation_key == "photo_snapshot_failed"
    assert err.value.translation_placeholders["entity_id"] == "camera.nursery"


async def test_attach_photo_service_with_an_image_entity(hass, backend):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)
    entity = SimpleNamespace(async_image=AsyncMock(return_value=b"png bytes"))
    component = SimpleNamespace(get_entity=lambda entity_id: entity if entity_id == "image.doorbell" else None)
    seen = {}

    def attach(object_type, object_id, photo_path, picture_dir):
        with open(photo_path, "rb") as handle:
            seen["bytes"] = handle.read()
        seen["args"] = (object_type, object_id, picture_dir)
        return {"status": "success", "objectID": object_id, "pictureID": "PIC-1", "queued": False}

    with patch.dict(hass.data, {"image": component}), patch(f"{CORE}.attach_photo", side_effect=attach):
        await hass.services.async_call(DOMAIN, "attach_photo", {
            "object_type": "Diaper", "object_id": "DIAPER-1", "image_entity": "image.doorbell"}, blocking=True)
        assert seen == {"bytes": b"png bytes", "args": ("Diaper", "DIAPER-1", coordinator.picture_dir)}

        with pytest.raises(ServiceValidationError) as err:  # an image entity with nothing to show
            await hass.services.async_call(DOMAIN, "attach_photo", {
                "object_type": "Diaper", "object_id": "DIAPER-1", "image_entity": "image.other"}, blocking=True)
        assert err.value.translation_key == "photo_snapshot_failed"


async def test_attach_photo_service_arguments(hass, backend, photo_folder):
    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)

    await hass.services.async_call(DOMAIN, "attach_photo", {
        "object_type": "Diaper", "object_id": "DIAPER-1", "photo": photo_folder}, blocking=True)
    assert backend[-1] == ("attach_photo", "Diaper", "DIAPER-1", os.path.realpath(photo_folder),
                           coordinator.picture_dir)

    for data, key in (
        ({"object_type": "Diaper", "object_id": "D"}, "photo_required"),
        ({"object_type": "Diaper", "object_id": "D", "photo": photo_folder, "camera_entity": "camera.a"},
         "photo_one_source"),
    ):
        with pytest.raises(ServiceValidationError) as err:
            await hass.services.async_call(DOMAIN, "attach_photo", data, blocking=True)
        assert err.value.translation_key == key

    with pytest.raises(vol.Invalid):  # doctor visits are never synced, so they can't carry a photo
        await hass.services.async_call(DOMAIN, "attach_photo", {
            "object_type": "DoctorVisit", "object_id": "D", "photo": photo_folder}, blocking=True)

    with patch(f"{CORE}.attach_photo", return_value={"status": "error", "message": "Diaper X not found"}), \
         pytest.raises(HomeAssistantError, match="Diaper X not found"):
        await hass.services.async_call(DOMAIN, "attach_photo", {
            "object_type": "Diaper", "object_id": "X", "photo": photo_folder}, blocking=True)


async def test_photo_services_ask_for_a_debounced_refresh(hass, backend, photo_folder):
    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)
    with patch.object(coordinator, "async_request_refresh") as request, \
         patch.object(coordinator, "async_refresh") as refresh:
        await hass.services.async_call(DOMAIN, "log_joy", {"baby_name": "Ava", "photo": photo_folder}, blocking=True)
        await hass.services.async_call(DOMAIN, "attach_photo", {
            "object_type": "Diaper", "object_id": "DIAPER-1", "photo": photo_folder}, blocking=True)
    assert request.await_count == 2
    refresh.assert_not_called()


async def test_undo_and_delete_ask_for_a_debounced_refresh(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)
    with patch.object(coordinator, "async_request_refresh") as request, \
         patch.object(coordinator, "async_refresh") as refresh:
        await hass.services.async_call(DOMAIN, "undo_last", {"baby_name": "Ava"}, blocking=True)
        await hass.services.async_call(
            DOMAIN, "delete_record", {"object_type": "Diaper", "object_id": "DIAPER-1"}, blocking=True)
    assert request.call_count == 2
    refresh.assert_not_called()


async def test_recent_entries_sensor_lists_the_newest_records(hass, backend):
    await setup(hass, make_entry())

    recent = hass.states.get("sensor.ava_recent_entries")
    assert recent.state == "wet diaper"  # the newest
    # The type and ID are what delete_record takes
    assert recent.attributes["records"] == RECENT
    assert er.async_get(hass).async_get("sensor.ava_recent_entries").entity_category is EntityCategory.DIAGNOSTIC

    # Nothing logged for Ann Marie
    assert hass.states.get("sensor.ann_marie_recent_entries").state == "unknown"


async def test_recent_entries_follow_the_refresh(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    newer = [{"object_type": "Sleep", "object_id": "SLEEP-1", "time": "2026-03-01T11:00:00+00:00",
              "kind": "sleep 45 min", "note": ""}, *RECENT]

    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fetch_with(recent_records=newer)):
        await coordinator_for(hass, entry).async_refresh()
        await hass.async_block_till_done()

    recent = hass.states.get("sensor.ava_recent_entries")
    assert recent.state == "sleep 45 min" and len(recent.attributes["records"]) == 3


async def test_the_fetch_reads_each_babys_recent_records_in_the_same_job(hass, backend):
    from unittest.mock import MagicMock

    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)
    tracker = MagicMock()
    tracker.sync.return_value = {"status": "success"}
    tracker.get_all_babies.return_value = [AVA]
    tracker.get_baby_info.return_value = AVA
    tracker.get_events_between.return_value = []
    tracker.get_recent_records.return_value = RECENT
    coordinator.baby_tracker = tracker

    _, _, _, baby_data, _, _ = REAL_FETCH(coordinator, coordinator.photo_dir)
    assert baby_data["Ava"]["recent_records"] == RECENT
    tracker.get_recent_records.assert_called_once_with("ID-AVA", 10)

    # A record the database cannot read leaves the sensor empty rather than failing the refresh
    tracker.get_recent_records.side_effect = ValueError("bad row")
    _, _, _, baby_data, _, _ = REAL_FETCH(coordinator, coordinator.photo_dir)
    assert baby_data["Ava"]["recent_records"] == []


# ----- the Medicine Amount follows the selected medicine -----

# Tylenol has a usual dose, Gripe water has none, Iron has no unit either
MEDICINES_WITH_GAPS = [
    {"id": "MED-TYLENOL", "name": "Tylenol", "amount_per_time": 3.75, "unit": "ml"},
    {"id": "MED-GRIPE", "name": "Gripe water", "amount_per_time": 0, "unit": ""},
    {"id": "MED-IRON", "name": "Iron", "amount_per_time": None, "unit": None},
]


def fetch_with_medicines(medicines):
    def fetch(self, photo_dir):
        return (*fake_fetch(self, photo_dir)[:5], medicines)
    return fetch


async def test_selecting_a_medicine_sets_its_usual_amount(hass, backend):
    await setup(hass, make_entry())
    amount = "number.ava_medicine_amount"
    assert float(hass.states.get(amount).state) == 3.75 and hass.states.get(amount).attributes["unit"] == "ml"

    await select_option(hass, "select.ava_medicine", "Vitamin D")
    assert float(hass.states.get(amount).state) == 1.0  # the number's state moved with the select
    assert hass.states.get(amount).attributes["unit"] == "ml"

    # A dose set by hand stands until another medicine is chosen
    await set_number(hass, amount, 2.5)
    assert float(hass.states.get(amount).state) == 2.5
    await select_option(hass, "select.ava_medicine", "Tylenol")
    assert float(hass.states.get(amount).state) == 3.75

    # Each baby has their own
    assert float(hass.states.get("number.ann_marie_medicine_amount").state) == 3.75
    await select_option(hass, "select.ava_medicine", "Vitamin D")
    assert float(hass.states.get("number.ann_marie_medicine_amount").state) == 3.75


async def test_a_medicine_with_no_usual_amount_leaves_the_amount_alone(hass, backend):
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               fetch_with_medicines(MEDICINES_WITH_GAPS)):
        await setup(hass, make_entry())
        amount = "number.ava_medicine_amount"
        await set_number(hass, amount, 2.5)

        for name in ("Gripe water", "Iron"):
            await select_option(hass, "select.ava_medicine", name)
            assert float(hass.states.get(amount).state) == 2.5, name
            assert "unit" not in hass.states.get(amount).attributes  # the medicine has none to show


async def test_give_medicine_falls_back_to_the_usual_amount(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)

    for empty in (0, None):
        coordinator.set_control("ID-AVA", "medicine_amount", empty)
        allow_another_press(hass, entry)
        await press(hass, "button.ava_give_medicine")
        assert backend[-1] == ("add_medicine", "ID-AVA", "MED-TYLENOL", 3.75)

    await select_option(hass, "select.ava_medicine", "Vitamin D")
    coordinator.set_control("ID-AVA", "medicine_amount", 0)
    allow_another_press(hass, entry)
    await press(hass, "button.ava_give_medicine")
    assert backend[-1] == ("add_medicine", "ID-AVA", "MED-VITD", 1.0)

    # An amount that was set is used as it is
    await set_number(hass, "number.ava_medicine_amount", 2.5)
    allow_another_press(hass, entry)
    await press(hass, "button.ava_give_medicine")
    assert backend[-1] == ("add_medicine", "ID-AVA", "MED-VITD", 2.5)


async def test_give_medicine_with_no_amount_and_no_usual_dose_is_refused(hass, backend):
    entry = make_entry()
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               fetch_with_medicines(MEDICINES_WITH_GAPS)):
        await setup(hass, entry)
        await select_option(hass, "select.ava_medicine", "Gripe water")
        coordinator_for(hass, entry).set_control("ID-AVA", "medicine_amount", 0)
        with pytest.raises(ServiceValidationError) as err:
            await press(hass, "button.ava_give_medicine")
    assert err.value.translation_key == "no_medicine_amount"
    assert not [call for call in backend if call[0] == "add_medicine"]


async def test_an_amount_set_by_hand_is_restored_and_not_replaced_by_the_selection(hass, backend):
    mock_restore_cache_with_extra_data(hass, [
        (State("number.ava_medicine_amount", "2.5"),
         {"native_max_value": 100, "native_min_value": 0.1, "native_step": 0.1,
          "native_unit_of_measurement": None, "native_value": 2.5}),
        (State("select.ava_medicine", "Vitamin D"), {}),
    ])
    await setup(hass, make_entry())

    assert hass.states.get("select.ava_medicine").state == "Vitamin D"
    assert float(hass.states.get("number.ava_medicine_amount").state) == 2.5  # not Vitamin D's 1.0
    await press(hass, "button.ava_give_medicine")
    assert backend[-1] == ("add_medicine", "ID-AVA", "MED-VITD", 2.5)


# ----- landscape photo -----

PHOTO_BABY = Baby({"objectID": "ID-AVA", "name": "Ava", "dob": "", "dueDay": "", "pictureName": "ava.jpg"})


async def setup_with_photos(hass, portrait=True, landscape=True):
    """Set up with the real coordinator fetch, against a client that downloads these pictures (None: none)."""
    photo_dir = hass.config.path("baby_tracker")

    def saver(name, content, wanted):
        def download(self, picture_name, save_dir):
            assert save_dir == photo_dir
            if not wanted:
                return None
            os.makedirs(save_dir, exist_ok=True)
            path = os.path.join(save_dir, name)
            with open(path, "wb") as photo:
                photo.write(content)
            return path
        return download

    with patch(f"{CORE}.authenticate", return_value={"status": "success"}), \
         patch(f"{CORE}.sync", return_value={"status": "success"}), \
         patch(f"{CORE}.get_all_babies", return_value=[PHOTO_BABY]), \
         patch(f"{CORE}.get_baby_info", return_value=PHOTO_BABY), \
         patch(f"{CORE}.download_baby_picture", saver("ava.jpg", b"portrait-bytes", portrait)), \
         patch(f"{CORE}.download_baby_landscape_picture", saver("ava_l.jpg", b"landscape-bytes", landscape)):
        await setup(hass, make_entry())


async def test_a_landscape_photo_is_a_second_image_entity(hass, hass_client):
    await setup_with_photos(hass)

    landscape = hass.states.get("image.ava_photo_landscape")
    assert landscape is not None
    client = await hass_client()
    response = await client.get(landscape.attributes["entity_picture"])
    assert response.status == 200 and await response.read() == b"landscape-bytes"

    # The portrait is untouched
    portrait = hass.states.get("image.ava_photo")
    assert await (await client.get(portrait.attributes["entity_picture"])).read() == b"portrait-bytes"
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get("image.ava_photo_landscape").unique_id == f"{DOMAIN}_{EMAIL}_ID-AVA_photo_landscape"
    assert ent_reg.async_get("image.ava_photo").unique_id == f"{DOMAIN}_{EMAIL}_ID-AVA_photo"


async def test_no_landscape_photo_means_no_landscape_entity(hass, hass_client):
    await setup_with_photos(hass, landscape=False)

    assert hass.states.get("image.ava_photo") is not None
    assert hass.states.get("image.ava_photo_landscape") is None
    assert er.async_get(hass).async_get_entity_id("image", DOMAIN, f"{DOMAIN}_{EMAIL}_ID-AVA_photo_landscape") is None


async def test_a_landscape_photo_without_a_portrait(hass, hass_client):
    await setup_with_photos(hass, portrait=False)

    assert hass.states.get("image.ava_photo").state == "unknown"  # nothing to show, but the entity stays
    landscape = hass.states.get("image.ava_photo_landscape")
    response = await (await hass_client()).get(landscape.attributes["entity_picture"])
    assert response.status == 200 and await response.read() == b"landscape-bytes"


# ----- Assist: voice intents and the sentence file -----

async def start_assist(hass, freezer, tmp_path, unit_system="imperial"):
    """Set the integration up at 12:00 with the config directory in tmp_path, and register the intents."""
    freezer.move_to("2026-03-01 12:00:00+00:00")
    hass.config.config_dir = str(tmp_path)
    entry = make_entry(unit_system)
    await setup(hass, entry)
    await bt_intent.async_setup_intents(hass)
    return entry


@pytest.fixture
async def assist(hass, backend, freezer, tmp_path):
    return await start_assist(hass, freezer, tmp_path)


async def ask(hass, intent_type, **slots):
    return await intent.async_handle(hass, "test", intent_type, {name: {"value": value} for name, value in slots.items()})


def said(result):
    return result.speech["plain"]["speech"]


def at(hour, minute=0):
    """A time on the test day (in UTC) as Home Assistant says it, in its time zone."""
    return bt_intent.clock(datetime(2026, 3, 1, hour, minute, tzinfo=UTC))


@pytest.mark.parametrize(("kind", "pee", "poo", "spoken"), [
    ("wet", True, False, "wet"), ("dirty", False, True, "dirty"), ("poopy", False, True, "dirty"),
    ("mixed", True, True, "mixed"), ("dry", False, False, "dry"),
])
async def test_the_diaper_intent_logs_for_the_named_baby(hass, assist, kind, pee, poo, spoken):
    with patch(f"{CORE}.add_diaper", return_value={"status": "success"}) as add_diaper:
        result = await ask(hass, "BabyTrackerLogDiaper", baby="ava", kind=kind)  # any capitalisation
    add_diaper.assert_called_once_with("ID-AVA", None, pee, poo, 5, 5, 5, 2, "Added by voice")
    assert result.response_type is intent.IntentResponseType.ACTION_DONE
    assert said(result) == f"Logged a {spoken} diaper for Ava."


async def test_the_bottle_intent_uses_the_entrys_unit_and_the_babys_bottle_type(hass, assist, backend):
    result = await ask(hass, "BabyTrackerLogBottle", baby="Ava", amount=4.0)
    assert backend[-1] == ("add_formula", "ID-AVA", 4.0, True)  # an imperial entry: oz
    assert said(result) == "Logged a 4 oz formula bottle for Ava."

    result = await ask(hass, "BabyTrackerLogBottle", baby="Ava", amount=120.0, unit="ml", type="breast milk")
    assert backend[-1] == ("add_pumped", "ID-AVA", 120.0, False)
    assert said(result) == "Logged a 120 ml bottle of pumped milk for Ava."

    # No type said: the baby's Bottle Type control decides
    coordinator_for(hass, assist).set_control("ID-AVA", "bottle_type", "pumped")
    await ask(hass, "BabyTrackerLogBottle", baby="Ava", amount=3.0)
    assert backend[-1] == ("add_pumped", "ID-AVA", 3.0, True)


async def test_a_bottle_too_big_to_be_real_is_not_logged(hass, assist, backend):
    logged = len(backend)
    result = await ask(hass, "BabyTrackerLogBottle", baby="Ava", amount=1200.0, unit="oz")
    assert len(backend) == logged
    assert result.response_type is intent.IntentResponseType.ERROR
    assert "doesn't sound like a bottle" in said(result)


async def test_the_temperature_intent_tells_fahrenheit_from_celsius(hass, assist, backend):
    result = await ask(hass, "BabyTrackerLogTemperature", baby="Ava", temperature=98.6)
    assert backend[-1] == ("add_temperature", "ID-AVA", 98.6, True)
    assert said(result) == "Logged a temperature of 98.6 degrees Fahrenheit for Ava."

    await ask(hass, "BabyTrackerLogTemperature", baby="Ava", temperature=37.2)
    assert backend[-1] == ("add_temperature", "ID-AVA", 37.2, False)

    logged = len(backend)
    result = await ask(hass, "BabyTrackerLogTemperature", baby="Ava", temperature=60.0)
    assert len(backend) == logged and result.response_type is intent.IntentResponseType.ERROR


async def test_the_sleep_intents_log_the_start_and_end_of_a_sleep(hass, assist):
    with patch(f"{CORE}.log_sleep_event", return_value={"status": "success"}) as log_sleep:
        # The fixture's Ava has been asleep since 11:00
        result = await ask(hass, "BabyTrackerStartSleep", baby="Ava")
        log_sleep.assert_not_called()
        assert said(result) == "Ava is already asleep."

        result = await ask(hass, "BabyTrackerEndSleep", baby="Ava")
        log_sleep.assert_called_once_with("ID-AVA", False, "Added by voice", None)
        assert said(result) == "Logged that Ava woke up after 1 hour."

        log_sleep.reset_mock()
        coordinator_for(hass, assist).data["baby_data"]["Ava"]["last_sleep"] = {
            "time": "2026-03-01 10:00:00 +0000", "is_sleeping": False, "duration": 45, "current_duration": 45}
        result = await ask(hass, "BabyTrackerEndSleep", baby="Ava")
        log_sleep.assert_not_called()
        assert said(result) == "Ava isn't asleep, so there's no sleep to end."

        result = await ask(hass, "BabyTrackerStartSleep", baby="Ava")
        log_sleep.assert_called_once_with("ID-AVA", True, "Added by voice", None)
        assert said(result) == "Logged that Ava fell asleep."


async def test_the_nursing_intents_time_a_session_and_log_it(hass, assist, backend, freezer):
    result = await ask(hass, "BabyTrackerEndNursing", baby="Ava")
    assert said(result) == "No nursing session is running for Ava."

    result = await ask(hass, "BabyTrackerStartNursing", baby="Ava", side="left")
    assert said(result) == "Started timing Ava on the left."
    assert hass.states.get("binary_sensor.ava_nursing").state == "on"

    freezer.tick(timedelta(minutes=10))
    result = await ask(hass, "BabyTrackerEndNursing", baby="Ava")
    assert backend[-1] == ("add_nursing", "ID-AVA", "2026-03-01 12:00:00 +0000", 10, 0, 1)
    assert said(result) == "Logged Ava's nursing: 10 min on the left."
    assert hass.states.get("binary_sensor.ava_nursing").state == "off"


async def test_a_failed_write_is_spoken_not_raised(hass, assist):
    with patch(f"{CORE}.add_diaper", return_value={"status": "error", "message": "offline"}):
        result = await ask(hass, "BabyTrackerLogDiaper", baby="Ava", kind="wet")
    assert result.response_type is intent.IntentResponseType.ERROR
    assert result.error_code is intent.IntentResponseErrorCode.FAILED_TO_HANDLE
    assert said(result) == "Sorry, I couldn't do that in Baby Tracker."


async def test_the_question_intents_answer_from_the_babys_data(hass, assist):
    # It is 12:00; Ava last ate at 9:30 (a 4 oz bottle), had a wet diaper at 10:00 and fell asleep at 11:00
    assert said(await ask(hass, "BabyTrackerLastFeed", baby="Ava")) == "Ava last ate 2 h 30 min ago, a 4 oz bottle."
    assert said(await ask(hass, "BabyTrackerLastDiaper", baby="Ava")) == "Ava's last diaper was wet, 2 hours ago."
    assert said(await ask(hass, "BabyTrackerNextFeed", baby="Ava")) == (
        f"Ava's next feed is expected around {at(12, 30)}, in 30 minutes.")
    assert said(await ask(hass, "BabyTrackerSleepStatus", baby="Ava")) == (
        f"Ava has been asleep for 1 hour, since {at(11)}.")
    assert said(await ask(hass, "BabyTrackerLastFeed", baby="Ann Marie")) == "I don't have any feeds logged for Ann Marie."
    assert said(await ask(hass, "BabyTrackerNextFeed", baby="Ann Marie")) == (
        "I don't have enough feeds logged to predict Ann Marie's next feed yet.")


async def test_the_intake_intent_reports_in_the_entrys_unit(hass, backend, freezer, tmp_path):
    await start_assist(hass, freezer, tmp_path, unit_system="metric")
    assert said(await ask(hass, "BabyTrackerIntakeToday", baby="Ava")) == (
        "Ava has had 420 ml in the last 24 hours, which is low. Expected is 600 to 800 ml.")


async def test_the_next_sleep_question_answers_for_a_sleeping_and_an_awake_baby(hass, assist):
    # It is 12:00 and Ava fell asleep at 11:00
    assert said(await ask(hass, "BabyTrackerNextSleep", baby="Ava")) == (
        f"Ava has been asleep for 1 hour and is expected to wake around {at(12, 40)}.")

    ava = coordinator_for(hass, assist).data["baby_data"]["Ava"]
    ava["insights"] = insights = {**INSIGHTS}  # a copy: the shared fake stays as it was
    insights["next_sleep"] = {**AWAKE, "awake_since": "2026-03-01T10:40:00+00:00",
                              "next_sleep_at": "2026-03-01T12:25:00+00:00"}
    assert said(await ask(hass, "BabyTrackerNextSleep", baby="Ava")) == (
        f"Ava has been awake for 1 h 20 min; the next nap is expected around {at(12, 25)}, in 25 minutes.")

    insights["next_sleep"] = {**AWAKE, "next_sleep_at": "2026-03-01T11:45:00+00:00"}
    assert said(await ask(hass, "BabyTrackerNextSleep", baby="Ava")) == (
        f"Ava has been awake for 1 h 30 min; a nap is due. It was expected around {at(11, 45)}.")

    insights["next_sleep"] = {**INSIGHTS["next_sleep"], "expected_wake_at": "2026-03-01T11:50:00+00:00"}
    assert said(await ask(hass, "BabyTrackerNextSleep", baby="Ava")) == (
        f"Ava has been asleep for 1 hour and was expected to wake around {at(11, 50)}.")

    assert said(await ask(hass, "BabyTrackerNextSleep", baby="Ann Marie")) == (
        "I don't have enough sleep logged to predict Ann Marie's next nap yet.")


async def test_the_sleep_question_says_how_long_an_awake_baby_has_been_up(hass, assist):
    coordinator_for(hass, assist).data["baby_data"]["Ava"]["last_sleep"] = {
        "time": "2026-03-01 10:00:00 +0000", "is_sleeping": False, "duration": 45, "current_duration": 45}
    assert said(await ask(hass, "BabyTrackerSleepStatus", baby="Ava")) == (
        "Ava has been awake for 1 h 15 min. The last sleep lasted 45 minutes.")


async def test_the_summary_covers_every_baby_when_none_is_named(hass, assist):
    ava = (f"Ava last ate 2 h 30 min ago, a 4 oz bottle. Ava's last diaper was wet, 2 hours ago. "
              f"Ava has been asleep for 1 hour, since {at(11)}. "
              f"Ava's next feed is expected around {at(12, 30)}, in 30 minutes.")
    assert said(await ask(hass, "BabyTrackerSummary", baby="Ava")) == ava
    assert said(await ask(hass, "BabyTrackerSummary")) == f"I don't have anything logged for Ann Marie yet. {ava}"


async def test_with_two_babies_and_none_named_the_intent_asks_which(hass, assist, backend):
    logged = len(backend)
    result = await ask(hass, "BabyTrackerLogDiaper", kind="wet")
    assert len(backend) == logged
    assert result.response_type is intent.IntentResponseType.ERROR
    assert result.error_code is intent.IntentResponseErrorCode.NO_VALID_TARGETS
    assert said(result) == "Which baby? Ann Marie or Ava."

    result = await ask(hass, "BabyTrackerLastFeed", baby="Nobody")
    assert said(result) == "I don't know a baby called Nobody."


async def test_the_only_baby_is_used_when_none_is_named(hass, backend, freezer, tmp_path):
    def one_baby(self, photo_dir):
        return [AVA], AVA, {}, {"Ava": {"baby_info": AVA, **AVA_DATA}}, ACCOUNT, MEDICINES

    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", one_baby):
        await start_assist(hass, freezer, tmp_path)
        result = await ask(hass, "BabyTrackerLogDiaper", kind="wet")
    assert backend[-1][:2] == ("add_diaper", "ID-AVA")
    assert said(result) == "Logged a wet diaper for Ava."


async def test_the_intents_say_so_when_baby_tracker_is_not_set_up(hass):
    await bt_intent.async_setup_intents(hass)
    result = await ask(hass, "BabyTrackerLastFeed", baby="Ava")
    assert result.response_type is intent.IntentResponseType.ERROR
    assert said(result) == "Baby Tracker isn't set up."


async def test_the_intents_are_registered_once(hass):
    await bt_intent.async_setup_intents(hass)
    await bt_intent.async_setup_intents(hass)
    registered = [h.intent_type for h in intent.async_get(hass) if h.intent_type.startswith("BabyTracker")]
    assert sorted(registered) == sorted(h.intent_type for h in bt_intent.HANDLERS) and len(registered) == 14


def test_baby_names_become_list_values_without_template_syntax():
    from custom_components.baby_tracker.sentences import baby_values

    assert baby_values(["Ava", "ann marie", " Ava ", "Zoe (Z)", "", None]) == [
        "ann marie", "Ava", {"in": "Zoe Z", "out": "Zoe (Z)"}]


async def test_a_missing_sentence_file_raises_a_repair_and_nothing_is_written(hass, backend, tmp_path):
    hass.config.config_dir = str(tmp_path)
    await setup(hass, make_entry())

    issue = ir.async_get(hass).async_get_issue(DOMAIN, "custom_sentences")
    assert issue is not None
    assert issue.is_fixable is True and issue.severity is ir.IssueSeverity.WARNING
    assert issue.translation_key == "custom_sentences"
    assert issue.translation_placeholders == {"folder": str(tmp_path / "custom_sentences"), "baby": "Ann Marie"}
    assert not (tmp_path / "custom_sentences").exists()  # not without the confirmation


async def test_confirming_the_repair_writes_the_sentences_with_the_babys_names(hass, backend, tmp_path):
    import yaml

    from custom_components.baby_tracker.repairs import async_create_fix_flow
    from custom_components.baby_tracker.sentences import async_check_sentences

    hass.config.config_dir = str(tmp_path)
    entry = make_entry()
    await setup(hass, entry)
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "custom_sentences") is not None

    flow = await async_create_fix_flow(hass, "custom_sentences", None)
    flow.hass, flow.handler, flow.issue_id = hass, DOMAIN, "custom_sentences"
    form = await flow.async_step_init()
    assert form["type"] is FlowResultType.FORM and form["step_id"] == "confirm"
    assert form["description_placeholders"] == {"folder": str(tmp_path / "custom_sentences")}
    assert not (tmp_path / "custom_sentences").exists()  # showing the form writes nothing

    done = await flow.async_step_confirm({})
    assert done["type"] is FlowResultType.CREATE_ENTRY

    sentences_file = tmp_path / "custom_sentences" / "en" / "baby_tracker.yaml"
    written = yaml.safe_load(sentences_file.read_text(encoding="utf-8"))
    assert written["lists"]["baby"]["values"] == ["Ann Marie", "Ava"]
    assert "BabyTrackerLogDiaper" in written["intents"]

    # What is there now is what the integration wants: the repair clears
    await async_check_sentences(hass, coordinator_for(hass, entry))
    assert registry.async_get_issue(DOMAIN, "custom_sentences") is None

    # A hand-edited file is out of date again
    sentences_file.write_text("language: en\n", encoding="utf-8")
    await async_check_sentences(hass, coordinator_for(hass, entry))
    assert registry.async_get_issue(DOMAIN, "custom_sentences") is not None


async def test_the_repair_reports_a_folder_it_cannot_write(hass, backend, tmp_path):
    from custom_components.baby_tracker.repairs import async_create_fix_flow

    hass.config.config_dir = str(tmp_path)
    await setup(hass, make_entry())
    flow = await async_create_fix_flow(hass, "custom_sentences", None)
    flow.hass, flow.handler, flow.issue_id = hass, DOMAIN, "custom_sentences"

    with patch("custom_components.baby_tracker.sentences.write", side_effect=PermissionError("read-only")):
        result = await flow.async_step_confirm({})
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": "write_failed"}


def test_the_shipped_sentences_are_understood_by_assist():
    hassil = pytest.importorskip("hassil")
    import yaml

    from custom_components.baby_tracker.sentences import render, template_languages

    intents = hassil.Intents.from_dict(yaml.safe_load(render(template_languages()["en"], ["Ava", "Ann Marie"])))
    for text, intent_type, slots in (
        ("Ava had a wet diaper", "BabyTrackerLogDiaper", {"baby": "Ava", "kind": "wet"}),
        ("log a 120 ml bottle for ann marie", "BabyTrackerLogBottle", {"baby": "Ann Marie", "amount": 120, "unit": "ml"}),
        ("Ava is asleep", "BabyTrackerStartSleep", {"baby": "Ava"}),
        ("Ava woke up", "BabyTrackerEndSleep", {"baby": "Ava"}),
        ("start nursing Ava on the left", "BabyTrackerStartNursing", {"baby": "Ava", "side": "left"}),
        ("stop nursing Ava", "BabyTrackerEndNursing", {"baby": "Ava"}),
        ("when did Ava last eat", "BabyTrackerLastFeed", {"baby": "Ava"}),
        ("when was Ava's last diaper change", "BabyTrackerLastDiaper", {"baby": "Ava"}),
        ("when is Ava's next feed", "BabyTrackerNextFeed", {"baby": "Ava"}),
        ("how much has Ava eaten today", "BabyTrackerIntakeToday", {"baby": "Ava"}),
        ("is Ava sleeping", "BabyTrackerSleepStatus", {"baby": "Ava"}),
        ("when should Ava nap", "BabyTrackerNextSleep", {"baby": "Ava"}),
        ("when is Ava's next nap", "BabyTrackerNextSleep", {"baby": "Ava"}),
        ("when will Ava wake up", "BabyTrackerNextSleep", {"baby": "Ava"}),
        ("how is Ava doing", "BabyTrackerSummary", {"baby": "Ava"}),
    ):
        result = hassil.recognize(text, intents)
        assert result is not None, text
        assert result.intent.name == intent_type, text
        got = {name: entity.value for name, entity in result.entities.items()}
        assert got == slots, text  # 120.0 == 120


# ----- sleep taken from another entity -----

SNOO = "binary_sensor.snoo_asleep"
SNOO_SOURCES = {"sleep_sources": {"ID-AVA": {"sleep_source_entity": SNOO}}}
NIGHT = datetime(2026, 3, 1, 22, 0, tzinfo=UTC)
# Ava is awake as far as Baby Tracker knows (the shared test data has her asleep)
SOURCE_AWAKE = {  # Ava awake as far as Baby Tracker knows (the nap fixture above is AWAKE)
    "last_sleep": {"time": "2026-03-01 18:00:00 +0000", "is_sleeping": False, "duration": 60,
                        "current_duration": 0, "status": "awake"}}


@contextmanager
def logged_sleeps(**changes):
    """Ava's sleep as Baby Tracker has it (awake unless changed), with log_sleep_event recorded."""
    fetch = fetch_with(**{**SOURCE_AWAKE, **changes})
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fetch), \
         patch(f"{CORE}.log_sleep_event", return_value={"status": "success"}) as log_sleep:
        yield log_sleep


def set_snoo(hass, state):
    hass.states.async_set(SNOO, state, {"friendly_name": "Snoo"})


async def start_snoo(hass, freezer, state="off", options=None):
    """Set up the integration with a Snoo-like entity as Ava's sleep source, at 22:00."""
    freezer.move_to(NIGHT)
    set_snoo(hass, state)
    entry = make_entry(options=options or SNOO_SOURCES)
    await setup(hass, entry)
    return entry


async def advance(hass, freezer, **delta):
    freezer.tick(timedelta(**delta))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


def starts_and_ends(log_sleep):
    """The is_start flag of each sleep written, in order."""
    return [call.args[1] for call in log_sleep.call_args_list]


async def test_the_sleep_start_is_logged_after_the_minimum_back_dated(hass, backend, freezer):
    with logged_sleeps() as log_sleep:
        await start_snoo(hass, freezer)
        assert hass.states.get("binary_sensor.ava_sleep_source").state == "off"
        assert hass.states.get("binary_sensor.ann_marie_sleep_source") is None  # only babies with a source

        set_snoo(hass, "on")
        await advance(hass, freezer, minutes=4)
        log_sleep.assert_not_called()  # 5 minutes is the default minimum
        assert hass.states.get("binary_sensor.ava_sleep_source").state == "on"

        await advance(hass, freezer, minutes=1)
        log_sleep.assert_called_once_with("ID-AVA", True, "From Snoo", NIGHT)  # dated when she dropped off

        source = hass.states.get("binary_sensor.ava_sleep_source")
        assert source.attributes["source_entity"] == SNOO
        assert source.attributes["since"] == NIGHT.isoformat()
        assert source.attributes["pending_end"] is None


async def test_a_short_wake_inside_the_gap_does_not_end_the_sleep(hass, backend, freezer):
    with logged_sleeps() as log_sleep:
        await start_snoo(hass, freezer, state="on")
        await advance(hass, freezer, minutes=20)
        set_snoo(hass, "off")
        await advance(hass, freezer, minutes=5)
        assert hass.states.get("binary_sensor.ava_sleep_source").attributes["pending_end"]

        set_snoo(hass, "on")  # back down before the 10 minutes are up
        await advance(hass, freezer, minutes=30)

        assert starts_and_ends(log_sleep) == [True]  # no end
        source = hass.states.get("binary_sensor.ava_sleep_source")
        assert source.state == "on" and source.attributes["pending_end"] is None
        assert source.attributes["since"] == NIGHT.isoformat()


async def test_a_wake_longer_than_the_gap_ends_the_sleep_at_the_wake_time(hass, backend, freezer):
    with logged_sleeps() as log_sleep:
        await start_snoo(hass, freezer, state="on")
        await advance(hass, freezer, minutes=20)
        woke = dt_util.utcnow()
        set_snoo(hass, "off")
        await advance(hass, freezer, minutes=9)
        assert starts_and_ends(log_sleep) == [True]  # only the start so far

        await advance(hass, freezer, minutes=1)
        assert log_sleep.call_args_list[-1].args == ("ID-AVA", False, "From Snoo", woke)  # not 10 minutes later
        assert hass.states.get("binary_sensor.ava_sleep_source").state == "off"


async def test_a_sleep_shorter_than_the_minimum_is_never_logged(hass, backend, freezer):
    with logged_sleeps() as log_sleep:
        await start_snoo(hass, freezer, state="on")
        await advance(hass, freezer, minutes=3)
        set_snoo(hass, "off")
        await advance(hass, freezer, minutes=30)
        log_sleep.assert_not_called()
        assert hass.states.get("binary_sensor.ava_sleep_source").state == "off"


async def test_an_unavailable_source_is_neither_a_start_nor_an_end(hass, backend, freezer):
    with logged_sleeps() as log_sleep:
        await start_snoo(hass, freezer, state="on")
        await advance(hass, freezer, minutes=2)
        set_snoo(hass, "unavailable")
        await advance(hass, freezer, minutes=3)
        assert starts_and_ends(log_sleep) == [True]  # the minimum still counted

        await advance(hass, freezer, minutes=60)
        set_snoo(hass, "unknown")
        await advance(hass, freezer, minutes=60)
        assert starts_and_ends(log_sleep) == [True]  # never ended
        assert hass.states.get("binary_sensor.ava_sleep_source").state == "on"


async def test_a_sleep_started_by_hand_is_not_started_twice(hass, backend, freezer):
    sleeping = {"last_sleep": {"time": "2026-03-01 21:58:00 +0000", "is_sleeping": True, "duration": 0,
                               "current_duration": 2, "status": "sleeping"}}
    with logged_sleeps(**sleeping) as log_sleep:
        await start_snoo(hass, freezer, state="on")
        await advance(hass, freezer, minutes=6)
        log_sleep.assert_not_called()  # Baby Tracker already has one in progress

        set_snoo(hass, "off")
        await advance(hass, freezer, minutes=10)
        assert starts_and_ends(log_sleep) == [False]  # the end still goes to that sleep


async def test_a_failed_end_is_dropped_quietly(hass, backend, freezer):
    with logged_sleeps() as log_sleep:
        await start_snoo(hass, freezer, state="on")
        await advance(hass, freezer, minutes=10)
        log_sleep.return_value = {"status": "error", "message": "No active sleep session found"}  # ended by hand
        set_snoo(hass, "off")
        await advance(hass, freezer, minutes=10)
        assert hass.states.get("binary_sensor.ava_sleep_source").state == "off"


async def test_a_sleep_in_progress_survives_a_restart(hass, backend, freezer, hass_storage):
    with logged_sleeps() as log_sleep:
        entry = await start_snoo(hass, freezer, state="on")
        await advance(hass, freezer, minutes=10)
        assert starts_and_ends(log_sleep) == [True]

        await advance(hass, freezer, minutes=8)
        await hass.config_entries.async_reload(entry.entry_id)  # a restart: the entity is still asleep
        await hass.async_block_till_done()
        source = hass.states.get("binary_sensor.ava_sleep_source")
        assert source.state == "on"
        assert source.attributes["since"] == NIGHT.isoformat()  # not 22:18, when HA came back
        assert starts_and_ends(log_sleep) == [True]  # and not started a second time

        woke = dt_util.utcnow()
        set_snoo(hass, "off")
        await advance(hass, freezer, minutes=10)
        assert log_sleep.call_args_list[-1].args == ("ID-AVA", False, "From Snoo", woke)


async def test_a_wake_during_a_restart_ends_the_sleep_from_when_it_was_noticed(hass, backend, freezer, hass_storage):
    with logged_sleeps() as log_sleep:
        entry = await start_snoo(hass, freezer, state="on")
        await advance(hass, freezer, minutes=10)

        assert await hass.config_entries.async_unload(entry.entry_id)
        set_snoo(hass, "off")
        await advance(hass, freezer, minutes=20)
        noticed = dt_util.utcnow()
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        await advance(hass, freezer, minutes=10)

        assert log_sleep.call_args_list[-1].args == ("ID-AVA", False, "From Snoo", noticed)


async def test_no_sleep_source_means_no_sleep_source_entity(hass, backend):
    await setup(hass, make_entry())
    assert hass.states.get("binary_sensor.ava_sleep_source") is None


async def test_options_flow_saves_a_sleep_source_per_baby(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 15, "unit_system": "imperial"})
    assert result["step_id"] == "sleep_source"
    assert result["description_placeholders"] == {"baby": "Ann Marie"}

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})  # no source for her
    assert result["step_id"] == "sleep_source"
    assert result["description_placeholders"] == {"baby": "Ava"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"sleep_source_entity": SNOO, "sleep_source_asleep_states": []})
    assert result["errors"] == {"sleep_source_asleep_states": "no_asleep_states"}

    result = await hass.config_entries.options.async_configure(result["flow_id"], {
        "sleep_source_entity": SNOO, "sleep_source_asleep_states": ["asleep", "weaning"],
        "sleep_gap_minutes": 15, "sleep_min_minutes": 3})
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["sleep_sources"] == {"ID-AVA": {
        "sleep_source_entity": SNOO, "sleep_source_asleep_states": ["asleep", "weaning"],
        "sleep_gap_minutes": 15, "sleep_min_minutes": 3}}
    assert entry.options["unit_system"] == "imperial"
    assert hass.states.get("binary_sensor.ava_sleep_source")  # the reload created it


async def test_options_flow_offers_the_saved_sleep_source_and_can_clear_it(hass, backend):
    entry = make_entry(options=SNOO_SOURCES)
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 15, "unit_system": "imperial"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})  # Ann Marie
    entity_field = next(key for key in result["data_schema"].schema if key == "sleep_source_entity")
    assert entity_field.description == {"suggested_value": SNOO}

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})  # blank clears it
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "sleep_sources" not in entry.options
    assert hass.states.get("binary_sensor.ava_sleep_source") is None


# ----- Quiet mode: activities a baby is no longer logged for -----

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
ALL_TRACKED = dict.fromkeys(("feeds", "diapers", "sleep", "pumping", "medicine", "growth", "temperature"), True)


def long_ago(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S +0000")


def toddler_data():
    """A nearly-two-year-old who is only logged for sleep: the last feed and diaper are months old."""
    return {
        "last_feeding": {"time": long_ago(180), "type": "Formula"},
        "last_diaper": {"time": long_ago(170), "status": "Wet"},
        "last_sleep": {"time": long_ago(1), "is_sleeping": False},
        "last_growth": {"time": long_ago(400)},
    }


def test_a_newborn_tracks_everything_even_with_nothing_logged():
    from custom_components.baby_tracker.tracking import detect_tracking

    newborn = Baby({"objectID": "ID-NEW", "name": "New", "dob": long_ago(3), "dueDay": ""})
    assert detect_tracking(newborn, {}, NOW) == ALL_TRACKED


def test_a_baby_whose_last_feed_is_months_old_has_feeds_off_but_sleep_on():
    from custom_components.baby_tracker.tracking import detect_tracking

    toddler = Baby({"objectID": "ID-TOD", "name": "Tod", "dob": long_ago(700), "dueDay": ""})
    tracking = detect_tracking(toddler, toddler_data(), NOW)
    assert tracking["feeds"] is False and tracking["diapers"] is False and tracking["growth"] is False
    assert tracking["sleep"] is True
    assert tracking["pumping"] is False and tracking["medicine"] is False and tracking["temperature"] is False


def test_a_record_inside_the_window_counts_and_a_baby_asleep_counts():
    from custom_components.baby_tracker.tracking import detect_tracking

    toddler = Baby({"objectID": "ID-TOD", "name": "Tod", "dob": long_ago(700), "dueDay": ""})
    data = {"last_feeding": {"time": long_ago(13)}, "last_diaper": {"time": long_ago(15)},
            "last_sleep": {"time": long_ago(100), "is_sleeping": True}}
    tracking = detect_tracking(toddler, data, NOW)
    assert tracking["feeds"] is True and tracking["diapers"] is False and tracking["sleep"] is True


def test_the_override_replaces_detection_and_auto_defers_to_it():
    from custom_components.baby_tracker.tracking import resolve_tracking

    toddler = Baby({"objectID": "ID-TOD", "name": "Tod", "dob": long_ago(700), "dueDay": ""})
    detected, mode = resolve_tracking({}, toddler, toddler_data(), NOW)
    assert mode == "auto" and detected["feeds"] is False

    options = {"tracking": {"ID-TOD": ["feeds", "growth"]}}
    manual, mode = resolve_tracking(options, toddler, toddler_data(), NOW)
    assert mode == "manual"
    assert manual["feeds"] is True and manual["growth"] is True and manual["sleep"] is False  # not detection

    auto, mode = resolve_tracking({"tracking": {"ID-TOD": "auto"}}, toddler, toddler_data(), NOW)
    assert mode == "auto" and auto == detected


async def test_the_coordinator_works_out_tracking_for_each_baby(hass, backend):
    from unittest.mock import MagicMock

    toddler = Baby({"objectID": "ID-TOD", "name": "Tod", "dob": long_ago(700), "dueDay": ""})
    entry = make_entry(options={"tracking": {"ID-TOD": ["diapers"]}})
    await setup(hass, entry)
    coordinator = coordinator_for(hass, entry)
    tracker = MagicMock()
    tracker.sync.return_value = {"status": "success"}
    tracker.get_all_babies.return_value = [toddler]
    tracker.get_baby_info.return_value = toddler
    tracker.get_events_between.return_value = []
    tracker.get_last_feeding.return_value = toddler_data()["last_feeding"]
    tracker.get_last_sleep.return_value = toddler_data()["last_sleep"]
    coordinator.baby_tracker = tracker

    _, _, _, baby_data, _, _ = REAL_FETCH(coordinator, coordinator.photo_dir)
    assert baby_data["Tod"]["tracking_mode"] == "manual"
    assert baby_data["Tod"]["tracking"]["diapers"] is True and baby_data["Tod"]["tracking"]["sleep"] is False


def quiet_fetch(feeds=False, sleep=True, diapers=True):
    """Ann Marie is tracked and overdue for a feed; Ava is overdue too but her groups are as given."""
    def fetch(self, photo_dir):
        babies, info, pictures, data, account, medicines = fake_fetch(self, photo_dir)
        data["Ann Marie"] = {
            "baby_info": TWIN, "insights": {"next_feed": {"predicted_at": "2026-03-01T11:15:00+00:00"}},
            "time_since_last_feeding": {"hours_since_last_feeding": 5.0, "last_feeding_time": "2026-03-01T07:00:00+00:00"},
        }
        data["Ava"] = {
            **data["Ava"],
            "time_since_last_feeding": {"hours_since_last_feeding": 8.0, "last_feeding_time": "2026-03-01T04:00:00+00:00"},
            "tracking": {**ALL_TRACKED, "feeds": feeds, "sleep": sleep, "diapers": diapers},
            "tracking_mode": "auto",
        }
        return babies, info, pictures, data, account, medicines
    return fetch


async def test_alerts_of_an_untracked_group_are_off_with_a_reason(hass, backend, freezer):
    freezer.move_to("2026-03-01 12:40:00+00:00")  # Ava's predicted feed (12:30) has passed
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", quiet_fetch(feeds=False)):
        await setup(hass, make_entry())

    for alert in ("feeding_overdue", "feed_due", "intake_low", "wake_to_feed"):
        state = hass.states.get(f"binary_sensor.ava_{alert}")
        assert state.state == "off", alert
        assert state.attributes["reason"] == "not_tracked", alert
    assert hass.states.get("binary_sensor.ann_marie_feeding_overdue").state == "on"  # tracked, 5 h
    assert "reason" not in hass.states.get("binary_sensor.ann_marie_feeding_overdue").attributes


async def test_the_same_alerts_are_on_while_the_group_is_tracked(hass, backend, freezer):
    freezer.move_to("2026-03-01 12:40:00+00:00")
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", quiet_fetch(feeds=True)):
        await setup(hass, make_entry())
    assert hass.states.get("binary_sensor.ava_feeding_overdue").state == "on"
    assert hass.states.get("binary_sensor.ava_feed_due").state == "on"
    assert hass.states.get("binary_sensor.ava_intake_low").state == "on"
    assert "reason" not in hass.states.get("binary_sensor.ava_feeding_overdue").attributes


async def test_sleep_and_diaper_alerts_follow_their_own_groups(hass, backend, freezer):
    freezer.move_to("2026-03-01 14:00:00+00:00")  # Ava asleep since 11:00, expected awake at 12:40
    entry = make_entry()
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               quiet_fetch(feeds=True, sleep=True)):
        await setup(hass, entry)
    assert hass.states.get("binary_sensor.ava_nap_running_long").state == "on"

    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               quiet_fetch(feeds=True, sleep=False, diapers=False)):
        await coordinator_for(hass, entry).async_refresh()
        await hass.async_block_till_done()
    for alert in ("nap_running_long", "long_sleep", "sleep_due", "no_poop", "low_wet_diapers"):
        state = hass.states.get(f"binary_sensor.ava_{alert}")
        assert state.state == "off" and state.attributes["reason"] == "not_tracked", alert


async def test_derived_sensors_read_unknown_but_the_facts_stay(hass, backend):
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               quiet_fetch(feeds=False, sleep=False, diapers=False)):
        await setup(hass, make_entry())

    for sensor in ("next_feed", "feed_interval", "intake_24h", "intake_status", "time_since_last_feeding",
                   "diaper_adequacy", "next_sleep", "expected_wake", "wake_window"):
        state = hass.states.get(f"sensor.ava_{sensor}")
        assert state is not None, sensor
        assert state.state == "unknown", sensor
        assert state.attributes["reason"] == "not_tracked", sensor

    # What was logged stays, and so do the counts
    assert hass.states.get("sensor.ava_last_feeding").state != "unknown"
    assert hass.states.get("sensor.ava_last_feeding_time").state == "2026-03-01T09:30:00+00:00"
    assert hass.states.get("sensor.ava_last_diaper").state != "unknown"
    assert hass.states.get("sensor.ava_last_sleep").state != "unknown"
    assert hass.states.get("sensor.ava_wet_diapers").state != "unknown"


async def test_the_info_sensor_shows_what_is_tracked(hass, backend):
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", quiet_fetch(feeds=False)):
        await setup(hass, make_entry())
    info = hass.states.get("sensor.ava_info").attributes
    assert info["tracking"]["feeds"] is False and info["tracking"]["sleep"] is True
    assert info["tracking_mode"] == "auto"
    # Without a verdict in the data (as in the other tests' fake data), nothing is shown as off
    assert hass.states.get("sensor.ann_marie_info").attributes["tracking"] == {}


async def test_household_sensors_only_consider_babies_with_the_group_tracked(hass, backend):
    def fetch(self, photo_dir):
        babies, info, pictures, data, account, medicines = household_fetch(self, photo_dir)
        data["Ann Marie"]["tracking"] = {**ALL_TRACKED, "feeds": False, "sleep": False}  # due first, fed first
        return babies, info, pictures, data, account, medicines

    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fetch):
        await setup(hass, make_entry(unit_system="metric"))

    assert hass.states.get("sensor.baby_tracker_next_feed_baby").state == "Ava"
    assert hass.states.get("sensor.baby_tracker_next_feed_due").attributes["predictions"] == {
        "Ava": "2026-03-01T12:30:00+00:00"}
    assert hass.states.get("sensor.baby_tracker_last_fed_baby").state == "Ava"
    asleep = hass.states.get("sensor.baby_tracker_babies_asleep")
    assert asleep.state == "1" and asleep.attributes["babies"] == ["Ava"]
    feeds = hass.states.get("sensor.baby_tracker_feeds_today")
    assert feeds.state == "6" and feeds.attributes["per_baby"] == {"Ava": 6}


async def test_assist_says_an_untracked_activity_is_not_tracked(hass, backend, freezer, tmp_path):
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch",
               quiet_fetch(feeds=False, sleep=True, diapers=False)):
        await start_assist(hass, freezer, tmp_path)

        for intent_type in ("BabyTrackerLastFeed", "BabyTrackerNextFeed", "BabyTrackerIntakeToday"):
            result = await ask(hass, intent_type, baby="Ava")
            assert said(result) == "Feeds aren't being tracked for Ava", intent_type
        assert said(await ask(hass, "BabyTrackerLastDiaper", baby="Ava")) == (
            "Diapers aren't being tracked for Ava")
        # Sleep is still tracked, and the other baby is unaffected
        assert said(await ask(hass, "BabyTrackerSleepStatus", baby="Ava")).startswith("Ava has been asleep")
        assert said(await ask(hass, "BabyTrackerLastFeed", baby="Ann Marie")) == (
            "I don't have any feeds logged for Ann Marie.")
        # The summary leaves out what is not tracked; logging still works
        summary = said(await ask(hass, "BabyTrackerSummary", baby="Ava"))
        assert "ate" not in summary and "diaper" not in summary and "asleep" in summary
        result = await ask(hass, "BabyTrackerLogDiaper", baby="Ava", kind="wet")
        assert result.response_type is intent.IntentResponseType.ACTION_DONE


async def test_options_flow_saves_the_tracked_activities_per_baby(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 15, "unit_system": "imperial"})
    assert result["step_id"] == "sleep_source" and result["description_placeholders"] == {"baby": "Ann Marie"}
    field = next(key for key in result["data_schema"].schema if key == "tracked_activities")
    assert field.default() == ["auto"]  # offered as auto until set

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracked_activities": ["sleep", "feeds"]})  # Ann Marie: by hand
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})  # Ava: auto
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["tracking"] == {"ID-TWIN": ["feeds", "sleep"]}  # auto is simply absent
    assert "sleep_sources" not in entry.options  # the field is not part of a sleep source

    # Offered back on the next visit, and "auto" (with or without others) resets it
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 15, "unit_system": "imperial"})
    field = next(key for key in result["data_schema"].schema if key == "tracked_activities")
    assert field.default() == ["feeds", "sleep"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"tracked_activities": ["auto", "growth"]})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert "tracking" not in entry.options


# ----- creating medicines and foods -----

async def test_create_medicine_service_adds_it_to_the_medicine_select(hass, backend):
    medicines = [dict(m) for m in MEDICINES]
    calls = []

    def create_medicine(self, name, amount_per_time=0.0, unit="", interval_hours=0, prescription=False):
        calls.append((name, amount_per_time, unit, interval_hours, prescription))
        medicines.append({"id": "MED-NEW", "name": name, "amount_per_time": amount_per_time, "unit": unit})
        return {"status": "success", "objectID": "MED-NEW", "message": "Created the medicine"}

    with patch(f"{CORE}.create_medicine", create_medicine), \
         patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fetch_with_medicines(medicines)):
        await setup(hass, make_entry())
        assert "Zinc" not in hass.states.get("select.ava_medicine").attributes["options"]
        await hass.services.async_call(
            DOMAIN, "create_medicine",
            {"name": "Zinc", "amount": 2.5, "unit": "ml", "interval_hours": 8, "prescription": True}, blocking=True)
        await hass.async_block_till_done()
        assert calls == [("Zinc", 2.5, "ml", 8, True)]
        assert "Zinc" in hass.states.get("select.ava_medicine").attributes["options"]


async def test_create_food_service(hass, backend):
    calls = []

    def create_food(self, name, is_bottle=False):
        calls.append((name, is_bottle))
        return {"status": "success", "objectID": "FOOD-NEW", "message": "Created the food"}

    with patch(f"{CORE}.create_food", create_food):
        await setup(hass, make_entry())
        await hass.services.async_call(DOMAIN, "create_food", {"name": "Mango"}, blocking=True)
        await hass.services.async_call(DOMAIN, "create_food", {"name": "Oat milk", "is_bottle": True}, blocking=True)
    assert calls == [("Mango", False), ("Oat milk", True)]


async def test_create_services_report_failure(hass, backend):
    failed = {"status": "error", "message": "A medicine needs a name"}
    with patch(f"{CORE}.create_medicine", lambda self, *a, **k: failed), \
         patch(f"{CORE}.create_food", lambda self, *a, **k: failed):
        await setup(hass, make_entry())
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(DOMAIN, "create_medicine", {"name": " "}, blocking=True)
        with pytest.raises(HomeAssistantError):
            await hass.services.async_call(DOMAIN, "create_food", {"name": " "}, blocking=True)


async def test_log_medicine_and_add_solids_create_unknown_names_when_asked(hass, backend):
    created = []

    def create_medicine(self, name, amount_per_time=0.0, unit="", interval_hours=0, prescription=False):
        created.append(("medicine", name, amount_per_time))
        return {"status": "success", "objectID": "MED-NEW"}

    def create_food(self, name, is_bottle=False):
        created.append(("food", name))
        return {"status": "success", "objectID": "FOOD-NEW"}

    with patch(f"{CORE}.create_medicine", create_medicine), patch(f"{CORE}.create_food", create_food):
        await setup(hass, make_entry())

        # Without create, an unknown name is still refused
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                DOMAIN, "log_medicine", {"baby_name": "Ava", "medicine_name": "Zinc", "amount": 2}, blocking=True)
        assert created == []

        await hass.services.async_call(
            DOMAIN, "log_medicine",
            {"baby_name": "Ava", "medicine_name": "Zinc", "amount": 2, "create": True}, blocking=True)
        assert created[-1] == ("medicine", "Zinc", 2.0)
        assert backend[-1] == ("add_medicine", "ID-AVA", "MED-NEW", 2.0)

        await hass.services.async_call(
            DOMAIN, "add_solids", {"baby_name": "Ava", "food_name": "Mango", "amount": 1, "create": True},
            blocking=True)
        assert created[-1] == ("food", "Mango")
        assert backend[-1] == ("add_other_feed", "ID-AVA", "FOOD-NEW", 1.0, "", True)

        # A known name is not created again
        created.clear()
        await hass.services.async_call(
            DOMAIN, "add_solids", {"baby_name": "Ava", "food_name": "banana", "amount": 1, "create": True},
            blocking=True)
        assert created == []
