"""The integration inside Home Assistant: setup, entity migration, services, and config flows."""
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import EntityCategory, UnitOfLength, UnitOfMass, UnitOfTemperature, UnitOfVolume
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events, async_fire_time_changed
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry

from custom_components.baby_tracker.client import AuthenticationError
from custom_components.baby_tracker.client.models import Baby
from custom_components.baby_tracker.const import DOMAIN

EMAIL = "me@example.com"
EVERLY = Baby({"objectID": "ID-EVERLY", "name": "Everly", "dob": "", "dueDay": ""})
TWIN = Baby({"objectID": "ID-TWIN", "name": "Ann Marie", "dob": "", "dueDay": ""})
CORE = "custom_components.baby_tracker.client.core.BabyTracker"


def make_entry(unit_system="imperial"):
    return MockConfigEntry(
        domain=DOMAIN, unique_id=EMAIL, title="Baby Tracker", version=2,
        data={"email": EMAIL, "password": "pw", "scan_interval": 15, "unit_system": unit_system,
              "device_uuid": "ha-uuid"},
    )


# What BabyTracker.get_insights returns (datetimes as ISO strings)
INSIGHTS = {
    "baby_id": "ID-EVERLY",
    "name": "Everly",
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


# What the coordinator keeps for Everly besides the insights (client values: UTC times as text)
EVERLY_DATA = {
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
}

# What the coordinator keeps for the account as a whole
ACCOUNT = {"pumped_milk_inventory": {"ml": 479.1, "pumped_ml": 588.3, "fed_ml": 109.2}, "pending_uploads": 2}


def fake_fetch(self, photo_dir):
    babies = [TWIN, EVERLY]
    data = {b.name: {"baby_info": b, **(EVERLY_DATA if b is EVERLY else {"insights": {}})} for b in babies}
    return babies, EVERLY, {}, data, ACCOUNT


def fetch_with(**changes):
    """A fetch like fake_fetch, but with Everly's data changed (as after something new is logged)."""
    def fetch(self, photo_dir):
        babies, info, pictures, data, account = fake_fetch(self, photo_dir)
        data["Everly"] = {**data["Everly"], **changes}
        return babies, info, pictures, data, account
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

    with patch(f"{CORE}.authenticate", return_value={"status": "success"}), \
         patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fake_fetch), \
         patch(f"{CORE}.add_diaper", add_diaper), \
         patch(f"{CORE}.add_temperature", add_temperature), \
         patch(f"{CORE}.log_growth", log_growth), \
         patch(f"{CORE}.get_baby_by_name", lambda self, name: next((b for b in (TWIN, EVERLY) if b.name == name), None)):
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
    for baby_id, slug in (("ID-TWIN", "ann_marie"), ("ID-EVERLY", "everly")):
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

    await hass.services.async_call(DOMAIN, "add_diaper", {"baby_name": "Everly"}, blocking=True)
    assert backend[-1][:2] == ("add_diaper", "ID-EVERLY")

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
    with patch("custom_components.baby_tracker.config_flow.validate_input",
               return_value={"title": "Baby Tracker (Everly & Ann Marie)"}), \
         patch("custom_components.baby_tracker.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"email": EMAIL, "password": "pw", "scan_interval": 15, "unit_system": "metric"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["device_uuid"]


async def test_options_flow(hass):
    entry = make_entry()
    entry.add_to_hass(hass)
    with patch("custom_components.baby_tracker.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"scan_interval": 5, "unit_system": "metric"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {"scan_interval": 5, "unit_system": "metric"}


async def test_insight_entities(hass, backend):
    await setup(hass, make_entry(unit_system="metric"))

    assert hass.states.get("sensor.everly_next_feed").state == "2026-03-01T12:30:00+00:00"
    next_feed = hass.states.get("sensor.everly_next_feed").attributes
    assert next_feed["basis"] == "history" and next_feed["wake_by"] == "2026-03-01T14:30:00+00:00"

    intake = hass.states.get("sensor.everly_intake_24h")
    assert float(intake.state) == 420.0
    assert intake.attributes["unit_of_measurement"] == "mL"
    assert intake.attributes["status"] == "low"
    assert intake.attributes["expected_min_ml"] == 600
    assert intake.attributes["bottle_feeds"] == 6

    assert hass.states.get("sensor.everly_intake_status").state == "low"
    assert hass.states.get("sensor.everly_diaper_adequacy").state == "ok"
    assert float(hass.states.get("sensor.everly_weight_percentile").state) == 30.9
    assert hass.states.get("sensor.everly_weight_percentile").attributes["p50"] == 4.5
    assert hass.states.get("sensor.everly_head_percentile").state == "unknown"  # no head measurement
    assert float(hass.states.get("sensor.everly_weight_gain").state) == 27.5
    assert hass.states.get("sensor.everly_corrected_age").state == "46"

    assert hass.states.get("binary_sensor.everly_intake_low").state == "on"
    assert hass.states.get("binary_sensor.everly_feed_due").state == "on"  # the prediction is in the past
    assert hass.states.get("binary_sensor.everly_wake_to_feed").state == "on"

    # A baby with no insights has unknown values rather than errors
    assert hass.states.get("sensor.ann_marie_next_feed").state == "unknown"
    assert hass.states.get("binary_sensor.ann_marie_intake_low").state == "off"


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

    attrs = check("sensor.everly_time_since_last_feeding", "150", "min", "duration", "measurement")
    assert attrs["feeding_status"] == "Due for feeding soon" and attrs["needs_feeding"] is False
    attrs = check("sensor.everly_last_sleep", "45", "min", "duration", "measurement")
    assert attrs["sleeping"] is True
    check("sensor.everly_last_nursing", "12", "min", "duration", "measurement")
    check("sensor.everly_nursing_minutes", "90", "min", "duration", "measurement")
    check("sensor.everly_last_pump", "118.3", "mL", "volume", "measurement")  # recorded as 4 oz
    check("sensor.everly_pump_summary", "354.9", "mL", "volume", "measurement")
    check("sensor.everly_bottle_volume", "500.0", "mL", "volume", "measurement")
    check("sensor.everly_weight", "4.536", "kg", "weight", "measurement")  # recorded as 10 lb
    check("sensor.everly_length", "50.8", "cm", "distance", "measurement")  # recorded as 20 in
    check("sensor.everly_head_circumference", "35.6", "cm", "distance", "measurement")
    check("sensor.everly_temperature", "37.3", "°C", "temperature", "measurement")
    attrs = check("sensor.everly_feedings", "20", "feedings", None, "measurement")
    assert attrs["window_days"] == 7
    check("sensor.everly_diapers", "30", "diapers", None, "measurement")
    check("sensor.everly_poopy_diapers", "7", "diapers", None, "measurement")  # mixed ones count
    check("sensor.everly_wet_diapers", "22", "diapers", None, "measurement")
    check("sensor.everly_daily_summary", "6", "feedings", None, "measurement")

    # Times are real timestamps; the kinds of feeding and diaper are enum states
    check("sensor.everly_last_feeding_time", "2026-03-01T09:30:00+00:00", device_class="timestamp")
    check("sensor.everly_last_diaper_time", "2026-03-01T10:00:00+00:00", device_class="timestamp")
    check("sensor.everly_last_sleep_time", "2026-03-01T11:00:00+00:00", device_class="timestamp")
    check("sensor.everly_last_doctor_visit", "2026-02-20T15:00:00+00:00", device_class="timestamp")
    check("sensor.everly_last_feeding", "formula", device_class="enum")
    check("sensor.everly_last_diaper", "wet", device_class="enum")
    check("sensor.everly_average_bedtime", "unknown")  # nothing to average yet

    # The oz half of Bottle Volume is gone; the ml half kept its ID
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{EMAIL}_ID-EVERLY_bottle_ml")
    assert not ent_reg.async_get_entity_id("sensor", DOMAIN, f"{DOMAIN}_{EMAIL}_ID-EVERLY_bottle_oz")
    assert hass.states.get("sensor.everly_bottle_oz") is None

    # Housekeeping entities are kept out of the way
    assert ent_reg.async_get("sensor.everly_info").entity_category is EntityCategory.DIAGNOSTIC
    assert ent_reg.async_get("sensor.everly_pump_summary").entity_category is EntityCategory.DIAGNOSTIC
    for key in ("sync_now", "force_resync"):
        entity_id = ent_reg.async_get_entity_id("button", DOMAIN, f"{DOMAIN}_{EMAIL}_{key}")
        assert ent_reg.async_get(entity_id).entity_category is EntityCategory.CONFIG


async def test_imperial_entry_shows_imperial_units(hass, backend):
    await setup(hass, make_entry(unit_system="imperial"))

    weight = hass.states.get("sensor.everly_weight")
    assert weight.attributes["unit_of_measurement"] == UnitOfMass.POUNDS
    assert float(weight.state) == pytest.approx(10, abs=0.05)
    length = hass.states.get("sensor.everly_length")
    assert length.attributes["unit_of_measurement"] == UnitOfLength.INCHES
    assert float(length.state) == pytest.approx(20, abs=0.05)
    pump = hass.states.get("sensor.everly_last_pump")
    assert pump.attributes["unit_of_measurement"] == UnitOfVolume.FLUID_OUNCES
    assert float(pump.state) == pytest.approx(4, abs=0.05)
    bottles = hass.states.get("sensor.everly_bottle_volume")
    assert bottles.attributes["unit_of_measurement"] == UnitOfVolume.FLUID_OUNCES
    assert float(bottles.state) == pytest.approx(16.9, abs=0.05)
    temperature = hass.states.get("sensor.everly_temperature")
    assert temperature.attributes["unit_of_measurement"] == UnitOfTemperature.FAHRENHEIT
    assert float(temperature.state) == 99.1


async def test_retired_bottle_oz_sensor_is_removed(hass, backend):
    entry = make_entry()
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    old = ent_reg.async_get_or_create("sensor", DOMAIN, f"{DOMAIN}_{EMAIL}_ID-EVERLY_bottle_oz",
                                      config_entry=entry, suggested_object_id="everly_bottle_oz")

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert ent_reg.async_get(old.entity_id) is None


async def test_services_date_the_record_at_the_time_given(hass, backend):
    await setup(hass, make_entry())

    await hass.services.async_call(
        DOMAIN, "add_diaper", {"baby_name": "Everly", "time": "2026-03-01T09:30:00+00:00"}, blocking=True)
    assert backend[-1] == ("add_diaper", "ID-EVERLY", "2026-03-01 09:30:00 +0000")

    # A time with no zone is in Home Assistant's time zone
    await hass.services.async_call(
        DOMAIN, "add_diaper", {"baby_name": "Everly", "time": "2026-03-01 09:30:00"}, blocking=True)
    local = datetime(2026, 3, 1, 9, 30, tzinfo=dt_util.get_default_time_zone())
    assert backend[-1][2] == dt_util.as_utc(local).strftime("%Y-%m-%d %H:%M:%S +0000")

    # With no time the client dates it now
    await hass.services.async_call(DOMAIN, "add_diaper", {"baby_name": "Everly"}, blocking=True)
    assert backend[-1][2] is None


@pytest.mark.parametrize(("unit_system", "imperial"), [("imperial", True), ("metric", False)])
async def test_service_units_follow_the_entry_unless_given(hass, backend, unit_system, imperial):
    await setup(hass, make_entry(unit_system=unit_system))
    base = {"baby_name": "Everly"}

    await hass.services.async_call(DOMAIN, "add_temperature", {**base, "temperature": 37.0}, blocking=True)
    assert backend[-1] == ("add_temperature", "ID-EVERLY", 37.0, imperial)
    await hass.services.async_call(DOMAIN, "log_growth", {**base, "weight": 4.0}, blocking=True)
    assert backend[-1] == ("log_growth", "ID-EVERLY", imperial, imperial)

    # What the call says wins
    await hass.services.async_call(
        DOMAIN, "add_temperature", {**base, "temperature": 37.0, "is_fahrenheit": not imperial}, blocking=True)
    assert backend[-1] == ("add_temperature", "ID-EVERLY", 37.0, not imperial)
    await hass.services.async_call(
        DOMAIN, "log_growth", {**base, "weight": 4.0, "is_english_length_scale": not imperial}, blocking=True)
    assert backend[-1] == ("log_growth", "ID-EVERLY", imperial, not imperial)


async def test_dismiss_alert_takes_the_insight_alert_types(hass, backend):
    await setup(hass, make_entry())
    for alert_type in ("intake_low", "feed_due", "wake_to_feed"):
        await hass.services.async_call(
            DOMAIN, "dismiss_alert", {"baby_name": "Everly", "alert_type": alert_type}, blocking=True)
    assert hass.states.get("binary_sensor.everly_feed_due").state == "off"  # dismissed while still true
    assert hass.states.get("binary_sensor.everly_intake_low").state == "off"


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
        {"id": "ID-EVERLY", "name": "Everly", "dob": ""},
    ]
    assert diagnostics["insights"]["ID-EVERLY"]["intake"]["status"] == "low"
    assert "pending_uploads" in diagnostics and "last_sync" in diagnostics


async def test_baby_photo_is_an_image_entity_in_a_private_folder(hass, hass_client):
    baby = Baby({"objectID": "ID-EVERLY", "name": "Everly", "dob": "", "dueDay": "", "pictureName": "everly.jpg"})
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
    state = hass.states.get("image.everly_photo")
    assert state is not None
    assert "/local/" not in str(state.attributes)

    response = await (await hass_client()).get(state.attributes["entity_picture"])
    assert response.status == 200
    assert await response.read() == b"photo-bytes"
    assert hass.states.get("sensor.everly_info").attributes.get("entity_picture") is None


async def test_baby_without_a_photo_still_has_an_image_entity(hass, backend):
    await setup(hass, make_entry())
    assert hass.states.get("image.everly_photo").state == "unknown"
    assert hass.states.get("image.ann_marie_photo") is not None


def household_fetch(self, photo_dir):
    """Two babies with data: Ann Marie is due to feed first, Everly was fed last, both are asleep."""
    twin = {
        "baby_info": TWIN,
        "insights": {"next_feed": {"predicted_at": "2026-03-01T11:15:00+00:00"}},
        "last_feeding": {"time": "2026-03-01 08:00:00 +0000", "type": "Nursing"},
        "last_sleep": {"time": "2026-03-01 10:45:00 +0000", "is_sleeping": True, "duration": 0},
        "daily_summary": {"total_feedings": 4},
    }
    return [TWIN, EVERLY], EVERLY, {}, {"Ann Marie": twin, "Everly": {"baby_info": EVERLY, **EVERLY_DATA}}, ACCOUNT


async def test_household_sensors_look_across_the_babies(hass, backend):
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", household_fetch):
        await setup(hass, make_entry(unit_system="metric"))

    due = hass.states.get("sensor.baby_tracker_next_feed_due")
    assert due.state == "2026-03-01T11:15:00+00:00"  # the earlier of 11:15 and Everly's 12:30
    assert due.attributes["device_class"] == "timestamp"
    assert due.attributes["baby"] == "Ann Marie"
    assert due.attributes["predictions"] == {
        "Ann Marie": "2026-03-01T11:15:00+00:00", "Everly": "2026-03-01T12:30:00+00:00"}
    assert hass.states.get("sensor.baby_tracker_next_feed_baby").state == "Ann Marie"

    last_fed = hass.states.get("sensor.baby_tracker_last_fed_baby")
    assert last_fed.state == "Everly"  # fed at 09:30, after Ann Marie's 08:00
    assert last_fed.attributes["time"] == "2026-03-01T09:30:00+00:00"

    asleep = hass.states.get("sensor.baby_tracker_babies_asleep")
    assert asleep.state == "2" and sorted(asleep.attributes["babies"]) == ["Ann Marie", "Everly"]

    feeds = hass.states.get("sensor.baby_tracker_feeds_today")
    assert feeds.state == "10"  # 4 + 6
    assert feeds.attributes["per_baby"] == {"Ann Marie": 4, "Everly": 6}

    pending = hass.states.get("sensor.baby_tracker_pending_uploads")
    assert pending.state == "2"
    ent_reg = er.async_get(hass)
    assert ent_reg.async_get("sensor.baby_tracker_pending_uploads").entity_category is EntityCategory.DIAGNOSTIC

    # They live on the account's own device, not a baby's
    device = dr.async_get(hass).async_get(ent_reg.async_get("sensor.baby_tracker_next_feed_due").device_id)
    assert device.identifiers == {(DOMAIN, f"{EMAIL}_system")}


async def test_household_sensors_skip_a_baby_with_no_data(hass, backend):
    await setup(hass, make_entry())  # fake_fetch: Ann Marie has nothing, Everly's feed is the only prediction
    assert hass.states.get("sensor.baby_tracker_next_feed_baby").state == "Everly"
    assert hass.states.get("sensor.baby_tracker_babies_asleep").state == "1"
    assert hass.states.get("sensor.baby_tracker_feeds_today").state == "6"


async def test_pumped_milk_inventory_follows_the_unit_setting(hass, backend):
    await setup(hass, make_entry(unit_system="metric"))
    inventory = hass.states.get("sensor.baby_tracker_pumped_milk_inventory")
    assert inventory.state == "479.1"
    assert inventory.attributes["unit_of_measurement"] == UnitOfVolume.MILLILITERS
    assert inventory.attributes["device_class"] == "volume"
    assert inventory.attributes["pumped_ml"] == 588.3 and inventory.attributes["fed_ml"] == 109.2


async def test_pumped_milk_inventory_is_shown_in_ounces_for_imperial(hass, backend):
    await setup(hass, make_entry(unit_system="imperial"))
    inventory = hass.states.get("sensor.baby_tracker_pumped_milk_inventory")
    assert inventory.attributes["unit_of_measurement"] == UnitOfVolume.FLUID_OUNCES
    assert float(inventory.state) == pytest.approx(16.2, abs=0.05)


async def test_derived_sensors(hass, backend):
    await setup(hass, make_entry())

    breast = hass.states.get("sensor.everly_which_breast_next")
    assert breast.state == "right" and breast.attributes["device_class"] == "enum"
    assert breast.attributes["last_side"] == "left" and breast.attributes["last_type"] == "nursing"
    assert breast.attributes["last_time"] == "2026-03-01T08:00:00+00:00"

    dose = hass.states.get("sensor.everly_next_medicine_dose")
    assert dose.state == "2026-03-01T10:00:00+00:00" and dose.attributes["device_class"] == "timestamp"
    assert dose.attributes["medicine_name"] == "Tylenol" and dose.attributes["amount"] == 2.5
    assert dose.attributes["unit"] == "ml" and dose.attributes["last_given"] == "2026-03-01T06:00:00+00:00"

    milestones = hass.states.get("sensor.everly_upcoming_milestones")
    assert milestones.state == "First smile"
    assert milestones.attributes["count"] == 2
    assert milestones.attributes["upcoming"] == [
        {"name": "First smile", "for_age_months": 2}, {"name": "Rolls over", "for_age_months": 5}]
    assert hass.states.get("sensor.everly_upcoming_vaccines").state == "HepB"

    # Nothing known for Ann Marie
    for entity_id in ("which_breast_next", "next_medicine_dose", "upcoming_milestones", "upcoming_vaccines"):
        assert hass.states.get(f"sensor.ann_marie_{entity_id}").state == "unknown", entity_id


async def test_medicine_without_an_interval_has_no_next_dose(hass, backend):
    dose = {"medicine_name": "Vitamin D", "amount": 1.0, "unit": "ml", "last_given": "2026-03-01 06:00:00 +0000",
            "interval_minutes": 0, "next_dose_at": None}
    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fetch_with(next_medicine_dose=dose)):
        await setup(hass, make_entry())
    state = hass.states.get("sensor.everly_next_medicine_dose")
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
        assert hass.states.get("binary_sensor.everly_feed_due").state == "off"  # predicted for 12:30
        assert hass.states.get("binary_sensor.everly_wake_to_feed").state == "off"  # wake by 14:30
        assert hass.states.get("binary_sensor.everly_feeding_overdue").state == "off"  # 3.4 h, over at 3.5
        assert hass.states.get("sensor.everly_time_since_last_feeding").state == "204"

        # 11 minutes pass; the 15-minute refresh is not due yet
        freezer.tick(timedelta(minutes=11))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert len(fetches) == 1  # no refresh, yet the alerts and the sensor moved on
        assert hass.states.get("binary_sensor.everly_feed_due").state == "on"
        assert hass.states.get("binary_sensor.everly_feeding_overdue").state == "on"
        assert hass.states.get("binary_sensor.everly_wake_to_feed").state == "off"
        assert hass.states.get("sensor.everly_time_since_last_feeding").state == "215"


async def test_night_mode_turns_on_when_night_falls(hass, backend, freezer):
    local = dt_util.get_default_time_zone()
    freezer.move_to(dt_util.as_utc(datetime(2026, 3, 1, 18, 59, tzinfo=local)))
    await setup(hass, make_entry())
    assert hass.states.get("binary_sensor.everly_night_mode").state == "off"  # asleep, but it is still day

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.everly_night_mode").state == "on"


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
    assert hass.states.get("event.everly_activity").state == "unknown"  # nothing has happened yet
    bus_events = async_capture_events(hass, f"baby_tracker_{event_type.split('_')[0]}")

    with patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fetch_with(**changes)):
        await hass.data[DOMAIN][entry.entry_id].async_refresh()
        await hass.async_block_till_done()

    state = hass.states.get("event.everly_activity")
    assert state.attributes["event_type"] == event_type
    assert state.attributes["event_types"] == ["feeding", "diaper", "sleep_start", "sleep_end", "bath", "medicine"]
    assert state.attributes["baby_name"] == "Everly"
    assert state.attributes["time"] == next(iter(changes.values()))["time"]
    assert hass.states.get("event.ann_marie_activity").state == "unknown"  # only Everly's changed

    # The bus events are still fired for feedings, diapers and sleeps
    assert len(bus_events) == (0 if event_type in ("bath", "medicine") else 1)


async def test_unchanged_data_fires_no_activity_event(hass, backend):
    entry = make_entry()
    await setup(hass, entry)
    await hass.data[DOMAIN][entry.entry_id].async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("event.everly_activity").state == "unknown"


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
            {"entity_id": "calendar.everly_calendar",
             "start_date_time": "2026-03-01T00:00:00+00:00", "end_date_time": "2026-03-02T00:00:00+00:00"},
            blocking=True, return_response=True)

    assert asked == ["ID-EVERLY"]
    events = result["calendar.everly_calendar"]["events"]
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

    calendar = hass.states.get("calendar.everly_calendar")
    assert calendar.state == "on"  # the nap runs until 12:20
    assert calendar.attributes["message"] == "Sleep (1h 20m)"
    assert hass.states.get("calendar.ann_marie_calendar").state == "off"
