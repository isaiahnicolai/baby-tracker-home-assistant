"""
Assist (voice) intents for Baby Tracker: log a diaper, bottle, sleep, nursing session or temperature,
and ask when a baby last ate, what their next feed is, how much they have had, whether they are asleep.

Home Assistant's `intent` integration calls async_setup_intents for every integration that has this
file. The sentences that trigger the intents are in custom_sentences/ (see sentences.py for how they
reach the config directory). The writes are the ones the services use (services.py).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import voluptuous as vol
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import intent
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import VolumeConverter

from .const import BOTTLE_TYPE_PUMPED, UNIT_SYSTEM_IMPERIAL
from .sensor import parse_time
from .services import (
    async_end_nursing,
    async_log_bottle,
    async_log_diaper,
    async_log_sleep,
    async_log_temperature,
    get_coordinator,
)

_LOGGER = logging.getLogger(__name__)

# What a diaper kind said aloud means, as (pee, poo); neither is a dry diaper
DIAPER_KINDS = {
    "wet": (True, False),
    "dirty": (False, True),
    "poopy": (False, True),
    "mixed": (True, True),
    "dry": (False, False),
}
BOTTLE_TYPES = ("formula", "pumped", "breast milk")
# A bottle larger than this is more likely a misheard number than a feed
MAX_BOTTLE_ML = 1200
MAX_BOTTLE_OZ = 40
# Body temperatures, which tell Fahrenheit and Celsius apart whatever the entry's units are
FAHRENHEIT_RANGE = (90.0, 110.0)
CELSIUS_RANGE = (34.0, 43.0)


class Spoken(Exception):
    """Something to tell the person instead of doing what they asked (a missing baby, a number too big)."""


# ----- speech -----

def english_join(names, conjunction="and"):
    names = list(names)
    if len(names) <= 2:
        return f" {conjunction} ".join(names)
    return ", ".join(names[:-1]) + f", {conjunction} " + names[-1]


def number(value) -> str:
    """120.0 as "120", 4.5 as "4.5"."""
    return f"{value:g}" if isinstance(value, float) else str(value)


def duration(minutes) -> str:
    """A span of time: "45 minutes", "2 hours", "2 h 15 min", "1 day 3 h"."""
    minutes = max(0, int(minutes))
    if minutes < 1:
        return "less than a minute"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours, rest = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''}" if not rest else f"{hours} h {rest} min"
    days, hours = divmod(hours, 24)
    day = f"{days} day{'s' if days != 1 else ''}"
    return day if not hours else f"{day} {hours} h"


def ago(moment: datetime, now: datetime) -> str:
    """How long before now a moment was: "45 minutes ago", "2 h 15 min ago", "just now"."""
    minutes = (now - moment).total_seconds() // 60
    return "just now" if minutes < 1 else f"{duration(minutes)} ago"


def clock(moment: datetime) -> str:
    """The time of day in Home Assistant's time zone, "4:30 PM"."""
    return dt_util.as_local(moment).strftime("%I:%M %p").lstrip("0")


def volume(coordinator, ml=None, oz=None, with_unit=True) -> str:
    """A volume in the entry's unit, from whichever of mL and oz is known: "118 ml" or "4 oz"."""
    if coordinator.unit_system == UNIT_SYSTEM_IMPERIAL:
        if oz is None and ml is not None:
            oz = VolumeConverter.convert(ml, UnitOfVolume.MILLILITERS, UnitOfVolume.FLUID_OUNCES)
        text, unit = number(round(oz, 1)), "oz"
    else:
        if ml is None and oz is not None:
            ml = VolumeConverter.convert(oz, UnitOfVolume.FLUID_OUNCES, UnitOfVolume.MILLILITERS)
        text, unit = number(int(round(ml))), "ml"
    return f"{text} {unit}" if with_unit else text


def _unit_name(coordinator) -> str:
    return "oz" if coordinator.unit_system == UNIT_SYSTEM_IMPERIAL else "ml"


def last_feed_speech(coordinator, name, data, now):
    feed = data.get("last_feeding") or {}
    moment = parse_time(feed.get("time"))
    if not moment:
        return None
    kind = feed.get("type")
    if kind == "Nursing":
        minutes = feed.get("total_duration")
        what = f", nursing for {duration(minutes)}" if minutes else ", nursing"
    elif kind in ("Formula", "Pumped"):
        known = feed.get("amount_ml") is not None or feed.get("amount_oz") is not None
        bottle = f"a {volume(coordinator, feed.get('amount_ml'), feed.get('amount_oz'))} bottle" if known else "a bottle"
        what = ", " + bottle + (" of pumped milk" if kind == "Pumped" else "")
    elif kind == "Supplement":
        what = f", {feed['feed_type'].lower()}" if feed.get("feed_type") else ", a supplement"
    else:
        what = ""
    return f"{name} last ate {ago(moment, now)}{what}."


def last_diaper_speech(name, data, now):
    diaper = data.get("last_diaper") or {}
    moment = parse_time(diaper.get("time"))
    if not moment:
        return None
    status = (diaper.get("status") or "").lower()
    if status and status != "unknown":
        return f"{name}'s last diaper was {status}, {ago(moment, now)}."
    return f"{name}'s last diaper was {ago(moment, now)}."


def next_feed_speech(name, data, now):
    moment = parse_time((((data.get("insights") or {}).get("next_feed")) or {}).get("predicted_at"))
    if not moment:
        return None
    if moment - now > timedelta(minutes=1):
        return f"{name}'s next feed is expected around {clock(moment)}, in {duration((moment - now).total_seconds() // 60)}."
    return f"{name} is due for a feed. It was expected around {clock(moment)}."


def next_sleep_speech(name, data, now):
    sleep = (data.get("insights") or {}).get("next_sleep") or {}
    if sleep.get("is_asleep"):
        wake = parse_time(sleep.get("expected_wake_at"))
        if not wake:
            return None
        since = parse_time(sleep.get("asleep_since"))
        lead = f"{name} has been asleep for {duration((now - since).total_seconds() // 60)}" if since else f"{name} is asleep"
        if wake - now > timedelta(minutes=1):
            return f"{lead} and is expected to wake around {clock(wake)}."
        return f"{lead} and was expected to wake around {clock(wake)}."
    moment = parse_time(sleep.get("next_sleep_at"))
    if not moment:
        return None
    since = parse_time(sleep.get("awake_since"))
    lead = f"{name} has been awake for {duration((now - since).total_seconds() // 60)}; " if since else f"{name} is awake; "
    if moment - now > timedelta(minutes=1):
        return f"{lead}the next nap is expected around {clock(moment)}, in {duration((moment - now).total_seconds() // 60)}."
    return f"{lead}a nap is due. It was expected around {clock(moment)}."


def intake_speech(coordinator, name, data):
    intake = (data.get("insights") or {}).get("intake") or {}
    if intake.get("actual_ml") is None:
        return None
    speech = f"{name} has had {volume(coordinator, intake['actual_ml'])} in the last 24 hours"
    status = intake.get("status")
    if status in ("low", "high"):
        speech += f", which is {status}"
    elif status == "ok":
        speech += ", which is within the expected range"
    speech += "."
    low, high = intake.get("expected_min_ml"), intake.get("expected_max_ml")
    if low and high and status in ("low", "high", "ok"):
        speech += (f" Expected is {volume(coordinator, low, with_unit=False)} to "
                   f"{volume(coordinator, high, with_unit=False)} {_unit_name(coordinator)}.")
    return speech


def sleep_speech(name, data, now):
    sleep = data.get("last_sleep") or {}
    start = parse_time(sleep.get("time"))
    if not sleep:
        return None
    if sleep.get("is_sleeping"):
        minutes = (now - start).total_seconds() // 60 if start else sleep.get("current_duration") or 0
        since = f", since {clock(start)}" if start else ""
        return f"{name} has been asleep for {duration(minutes)}{since}."
    slept = sleep.get("duration") or 0
    if not start:
        return f"{name} is awake."
    woke = start + timedelta(minutes=slept)
    speech = f"{name} has been awake for {duration((now - woke).total_seconds() // 60)}."
    return speech + (f" The last sleep lasted {duration(slept)}." if slept else "")


def summary_speech(coordinator, name, data, now):
    parts = (
        last_feed_speech(coordinator, name, data, now),
        last_diaper_speech(name, data, now),
        sleep_speech(name, data, now),
        next_feed_speech(name, data, now),
    )
    return " ".join(part for part in parts if part) or f"I don't have anything logged for {name} yet."


# ----- handlers -----

def _babies(coordinator):
    return (coordinator.data or {}).get("babies") or []


class BabyIntent(intent.IntentHandler):
    """
    Base for the intents. A subclass sets the slots and does its work in async_answer, which returns the
    speech; it raises Spoken to say something instead (a failed write is spoken too).
    """

    #: False for an intent that works with no baby named when there are several (it answers for them all)
    baby_required = True

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        try:
            slots = self.async_validate_slots(intent_obj.slots)
            coordinator = self._coordinator(intent_obj.hass)
            speech = await self.async_answer(intent_obj.hass, coordinator, slots)
        except vol.Invalid as err:
            _LOGGER.warning("Invalid slots for %s: %s", self.intent_type, err)
            response.async_set_error(intent.IntentResponseErrorCode.NO_VALID_TARGETS, "Sorry, I didn't understand that.")
            return response
        except Spoken as err:
            response.async_set_error(intent.IntentResponseErrorCode.NO_VALID_TARGETS, str(err))
            return response
        except HomeAssistantError as err:
            _LOGGER.warning("Could not handle %s: %s", self.intent_type, err)
            response.async_set_error(
                intent.IntentResponseErrorCode.FAILED_TO_HANDLE, "Sorry, I couldn't do that in Baby Tracker.")
            return response
        response.async_set_speech(speech)
        return response

    @staticmethod
    def _coordinator(hass):
        try:
            return get_coordinator(hass)
        except ServiceValidationError as err:
            raise Spoken("Baby Tracker isn't set up.") from err

    async def async_answer(self, hass, coordinator, slots) -> str:
        raise NotImplementedError

    @staticmethod
    def baby(coordinator, slots):
        """
        The baby the person named (any capitalisation), else the only baby. With several babies and no
        name, asks which one.
        """
        babies = _babies(coordinator)
        if not babies:
            raise Spoken("There are no babies in Baby Tracker yet.")
        named = (slots.get("baby") or {}).get("value")
        if named:
            for baby in babies:
                if baby.name.strip().casefold() == named.strip().casefold():
                    return baby
            raise Spoken(f"I don't know a baby called {named}.")
        if len(babies) == 1:
            return babies[0]
        raise Spoken(f"Which baby? {english_join((b.name for b in babies), 'or')}.")

    @staticmethod
    def data(coordinator, baby):
        """What the coordinator keeps for a baby."""
        return ((coordinator.data or {}).get("baby_data") or {}).get(baby.name) or {}


BABY = {vol.Optional("baby"): cv.string}


class LogDiaperIntent(BabyIntent):
    intent_type = "BabyTrackerLogDiaper"
    description = "Logs a diaper change (wet, dirty, mixed or dry) for a baby in Baby Tracker"
    slot_schema = {**BABY, vol.Required("kind"): vol.In(list(DIAPER_KINDS))}

    async def async_answer(self, hass, coordinator, slots):
        kind = slots["kind"]["value"]
        baby = self.baby(coordinator, slots)
        pee, poo = DIAPER_KINDS[kind]
        await async_log_diaper(hass, coordinator, baby.object_id, pee, poo, note="Added by voice")
        return f"Logged a {'dirty' if kind == 'poopy' else kind} diaper for {baby.name}."


class LogBottleIntent(BabyIntent):
    intent_type = "BabyTrackerLogBottle"
    description = "Logs a bottle of formula or pumped milk for a baby in Baby Tracker"
    slot_schema = {
        **BABY,
        vol.Required("amount"): vol.Coerce(float),
        vol.Optional("unit"): vol.In(["ml", "oz"]),
        vol.Optional("type"): vol.In(list(BOTTLE_TYPES)),
    }

    async def async_answer(self, hass, coordinator, slots):
        amount = slots["amount"]["value"]
        unit = (slots.get("unit") or {}).get("value") or _unit_name(coordinator)
        kind = (slots.get("type") or {}).get("value")
        baby = self.baby(coordinator, slots)
        if amount <= 0 or amount > (MAX_BOTTLE_OZ if unit == "oz" else MAX_BOTTLE_ML):
            raise Spoken(f"{number(amount)} {unit} doesn't sound like a bottle, so I haven't logged it.")
        pumped = (coordinator.control(baby.object_id, "bottle_type") == BOTTLE_TYPE_PUMPED) if kind is None \
            else kind != "formula"

        await async_log_bottle(
            hass, coordinator, baby.object_id, amount, unit == "oz", pumped=pumped, note="Added by voice")
        if pumped:
            return f"Logged a {number(amount)} {unit} bottle of pumped milk for {baby.name}."
        return f"Logged a {number(amount)} {unit} formula bottle for {baby.name}."


class StartSleepIntent(BabyIntent):
    intent_type = "BabyTrackerStartSleep"
    description = "Logs that a baby has fallen asleep in Baby Tracker"
    slot_schema = BABY

    async def async_answer(self, hass, coordinator, slots):
        baby = self.baby(coordinator, slots)
        if (self.data(coordinator, baby).get("last_sleep") or {}).get("is_sleeping"):
            return f"{baby.name} is already asleep."
        await async_log_sleep(hass, coordinator, baby.object_id, True, note="Added by voice")
        return f"Logged that {baby.name} fell asleep."


class EndSleepIntent(BabyIntent):
    intent_type = "BabyTrackerEndSleep"
    description = "Logs that a baby has woken up in Baby Tracker"
    slot_schema = BABY

    async def async_answer(self, hass, coordinator, slots):
        baby = self.baby(coordinator, slots)
        sleep = self.data(coordinator, baby).get("last_sleep") or {}
        if not sleep.get("is_sleeping"):
            return f"{baby.name} isn't asleep, so there's no sleep to end."
        started = parse_time(sleep.get("time"))
        await async_log_sleep(hass, coordinator, baby.object_id, False, note="Added by voice")
        slept = f" after {duration((dt_util.utcnow() - started).total_seconds() // 60)}" if started else ""
        return f"Logged that {baby.name} woke up{slept}."


class StartNursingIntent(BabyIntent):
    intent_type = "BabyTrackerStartNursing"
    description = "Starts timing a nursing session on the left or right side for a baby in Baby Tracker"
    slot_schema = {**BABY, vol.Required("side"): vol.In(["left", "right"])}

    async def async_answer(self, hass, coordinator, slots):
        side = slots["side"]["value"]
        baby = self.baby(coordinator, slots)
        coordinator.start_nursing(baby.object_id, side)
        return f"Started timing {baby.name} on the {side}."


class EndNursingIntent(BabyIntent):
    intent_type = "BabyTrackerEndNursing"
    description = "Ends a baby's running nursing session and logs it in Baby Tracker"
    slot_schema = BABY

    async def async_answer(self, hass, coordinator, slots):
        baby = self.baby(coordinator, slots)
        if coordinator.nursing_totals(baby.object_id) is None:
            return f"No nursing session is running for {baby.name}."
        totals = await async_end_nursing(hass, coordinator, baby.object_id, note="Added by voice")
        sides = [f"{totals[side]} min on the {side}" for side in ("left", "right") if totals[side]]
        return f"Logged {baby.name}'s nursing: {english_join(sides)}."


class LogTemperatureIntent(BabyIntent):
    intent_type = "BabyTrackerLogTemperature"
    description = "Logs a baby's temperature in Baby Tracker"
    slot_schema = {**BABY, vol.Required("temperature"): vol.Coerce(float)}

    async def async_answer(self, hass, coordinator, slots):
        temperature = slots["temperature"]["value"]
        # 37.2 can only be Celsius and 98.6 only Fahrenheit, so the entry's units are not needed to tell
        if FAHRENHEIT_RANGE[0] <= temperature <= FAHRENHEIT_RANGE[1]:
            fahrenheit = True
        elif CELSIUS_RANGE[0] <= temperature <= CELSIUS_RANGE[1]:
            fahrenheit = False
        else:
            raise Spoken(f"{number(temperature)} degrees doesn't sound like a body temperature, so I haven't logged it.")
        baby = self.baby(coordinator, slots)
        await async_log_temperature(
            hass, coordinator, baby.object_id, temperature, fahrenheit, note="Added by voice")
        return f"Logged a temperature of {number(temperature)} degrees {'Fahrenheit' if fahrenheit else 'Celsius'} for {baby.name}."


class LastFeedIntent(BabyIntent):
    intent_type = "BabyTrackerLastFeed"
    description = "Says when a baby last ate and what it was"
    slot_schema = BABY

    async def async_answer(self, hass, coordinator, slots):
        baby = self.baby(coordinator, slots)
        return last_feed_speech(coordinator, baby.name, self.data(coordinator, baby), dt_util.utcnow()) \
            or f"I don't have any feeds logged for {baby.name}."


class LastDiaperIntent(BabyIntent):
    intent_type = "BabyTrackerLastDiaper"
    description = "Says when a baby's diaper was last changed and what it was"
    slot_schema = BABY

    async def async_answer(self, hass, coordinator, slots):
        baby = self.baby(coordinator, slots)
        return last_diaper_speech(baby.name, self.data(coordinator, baby), dt_util.utcnow()) \
            or f"I don't have any diaper changes logged for {baby.name}."


class NextFeedIntent(BabyIntent):
    intent_type = "BabyTrackerNextFeed"
    description = "Says when a baby's next feed is expected"
    slot_schema = BABY

    async def async_answer(self, hass, coordinator, slots):
        baby = self.baby(coordinator, slots)
        return next_feed_speech(baby.name, self.data(coordinator, baby), dt_util.utcnow()) \
            or f"I don't have enough feeds logged to predict {baby.name}'s next feed yet."


class NextSleepIntent(BabyIntent):
    intent_type = "BabyTrackerNextSleep"
    description = "Says when a baby is likely to need a nap next, or when a sleeping baby is expected to wake"
    slot_schema = BABY

    async def async_answer(self, hass, coordinator, slots):
        baby = self.baby(coordinator, slots)
        return next_sleep_speech(baby.name, self.data(coordinator, baby), dt_util.utcnow())             or f"I don't have enough sleep logged to predict {baby.name}'s next nap yet."


class IntakeTodayIntent(BabyIntent):
    intent_type = "BabyTrackerIntakeToday"
    description = "Says how much a baby has eaten in the last 24 hours and whether that is enough"
    slot_schema = BABY

    async def async_answer(self, hass, coordinator, slots):
        baby = self.baby(coordinator, slots)
        return intake_speech(coordinator, baby.name, self.data(coordinator, baby)) \
            or f"I don't have enough feeds logged to say how much {baby.name} has had."


class SleepStatusIntent(BabyIntent):
    intent_type = "BabyTrackerSleepStatus"
    description = "Says whether a baby is asleep or awake and for how long"
    slot_schema = BABY

    async def async_answer(self, hass, coordinator, slots):
        baby = self.baby(coordinator, slots)
        return sleep_speech(baby.name, self.data(coordinator, baby), dt_util.utcnow()) \
            or f"I don't have any sleep logged for {baby.name}."


class SummaryIntent(BabyIntent):
    intent_type = "BabyTrackerSummary"
    description = "Gives a short status of a baby, or of every baby: last feed, last diaper, sleep and next feed"
    slot_schema = BABY

    async def async_answer(self, hass, coordinator, slots):
        now = dt_util.utcnow()
        if not (slots.get("baby") or {}).get("value") and len(_babies(coordinator)) > 1:
            babies = _babies(coordinator)  # no one named: everyone
        else:
            babies = [self.baby(coordinator, slots)]
        return " ".join(summary_speech(coordinator, baby.name, self.data(coordinator, baby), now) for baby in babies)


HANDLERS = (
    LogDiaperIntent, LogBottleIntent, StartSleepIntent, EndSleepIntent, StartNursingIntent, EndNursingIntent,
    LogTemperatureIntent, LastFeedIntent, LastDiaperIntent, NextFeedIntent, IntakeTodayIntent,
    NextSleepIntent, SleepStatusIntent, SummaryIntent,
)


async def async_setup_intents(hass: HomeAssistant) -> None:
    """Register the Baby Tracker intents (called by Home Assistant's intent integration)."""
    registered = {handler.intent_type for handler in intent.async_get(hass)}
    for handler in HANDLERS:
        if handler.intent_type not in registered:
            intent.async_register(hass, handler())
