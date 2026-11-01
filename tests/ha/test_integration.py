"""The integration inside Home Assistant: setup, entity migration, services, and config flows."""
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.baby_tracker.client import AuthenticationError
from custom_components.baby_tracker.client.models import Baby
from custom_components.baby_tracker.const import DOMAIN

EMAIL = "me@example.com"
EVERLY = Baby({"objectID": "ID-EVERLY", "name": "Everly", "dob": "", "dueDay": ""})
TWIN = Baby({"objectID": "ID-TWIN", "name": "Ann Marie", "dob": "", "dueDay": ""})
CORE = "custom_components.baby_tracker.client.core.BabyTracker"


def make_entry(unit_system="imperial"):
    return MockConfigEntry(
        domain=DOMAIN, unique_id=EMAIL, title="Baby Tracker",
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


def fake_fetch(self, www_dir):
    babies = [TWIN, EVERLY]
    return babies, EVERLY, {}, {b.name: {"baby_info": b, "insights": INSIGHTS if b is EVERLY else {}} for b in babies}


@pytest.fixture
def backend():
    """Stand in for the Baby Tracker client; records write calls."""
    calls = []

    def add_diaper(self, baby_id, *args):
        calls.append(("add_diaper", baby_id))
        return {"status": "success", "objectID": "new"}

    with patch(f"{CORE}.authenticate", return_value={"status": "success"}), \
         patch("custom_components.baby_tracker.BabyTrackerDataCoordinator._fetch", fake_fetch), \
         patch(f"{CORE}.add_diaper", add_diaper), \
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
            assert backend[-1] == ("add_diaper", baby_id)


async def test_services_target_a_baby_by_device(hass, backend):
    await setup(hass, make_entry())
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    device = next(d for d in dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
                  if (DOMAIN, f"{EMAIL}_ID-TWIN") in d.identifiers)
    await hass.services.async_call(DOMAIN, "add_diaper", {"device_id": device.id, "pee": True}, blocking=True)
    assert backend[-1] == ("add_diaper", "ID-TWIN")

    await hass.services.async_call(DOMAIN, "add_diaper", {"baby_name": "Everly"}, blocking=True)
    assert backend[-1] == ("add_diaper", "ID-EVERLY")

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
