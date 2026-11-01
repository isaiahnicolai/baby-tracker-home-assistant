"""Record a baby's sleep from another Home Assistant entity (a Snoo, an Owlet, a bed sensor...)."""
import asyncio
import logging
from datetime import timedelta

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_SLEEP_GAP_MINUTES,
    CONF_SLEEP_MIN_MINUTES,
    CONF_SLEEP_SOURCE_ASLEEP_STATES,
    CONF_SLEEP_SOURCE_ENTITY,
    CONF_SLEEP_SOURCES,
    DEFAULT_SLEEP_ASLEEP_STATES,
    DEFAULT_SLEEP_GAP_MINUTES,
    DEFAULT_SLEEP_MIN_MINUTES,
    DOMAIN,
    SLEEP_SOURCE_STORE_VERSION,
)
from .services import async_log_sleep

_LOGGER = logging.getLogger(__name__)


def configured_sources(options):
    """The valid per-baby settings from the options, {baby_id: settings with defaults filled in}."""
    sources = {}
    for baby_id, settings in (options.get(CONF_SLEEP_SOURCES) or {}).items():
        entity_id = (settings or {}).get(CONF_SLEEP_SOURCE_ENTITY)
        if not entity_id:
            continue
        states = settings.get(CONF_SLEEP_SOURCE_ASLEEP_STATES) or DEFAULT_SLEEP_ASLEEP_STATES
        sources[baby_id] = {
            CONF_SLEEP_SOURCE_ENTITY: entity_id,
            CONF_SLEEP_SOURCE_ASLEEP_STATES: [str(state).lower() for state in states],
            CONF_SLEEP_GAP_MINUTES: settings.get(CONF_SLEEP_GAP_MINUTES, DEFAULT_SLEEP_GAP_MINUTES),
            CONF_SLEEP_MIN_MINUTES: settings.get(CONF_SLEEP_MIN_MINUTES, DEFAULT_SLEEP_MIN_MINUTES),
        }
    return sources


class SleepSource:
    """
    Follows one entity for one baby and logs its sleep.

    candidate_start: when the entity last entered an asleep state (None = the baby is awake).
    logging: the sleep START has been written to Baby Tracker.
    pending_end: when the entity left the asleep state, while the gap timer decides whether
                 that is a real wake (None = still asleep).
    """

    def __init__(self, manager, baby_id, settings):
        self.manager = manager
        self.baby_id = baby_id
        self.entity_id = settings[CONF_SLEEP_SOURCE_ENTITY]
        self.asleep_states = settings[CONF_SLEEP_SOURCE_ASLEEP_STATES]
        self.gap = timedelta(minutes=settings[CONF_SLEEP_GAP_MINUTES])
        self.minimum = timedelta(minutes=settings[CONF_SLEEP_MIN_MINUTES])
        self.candidate_start = None
        self.logging = False
        self.pending_end = None
        self._min_timer = None
        self._gap_timer = None
        self._lock = asyncio.Lock()

    # ----- state -----

    @property
    def active(self):
        """Whether the baby counts as asleep through the source (a short wake still counts)."""
        return self.candidate_start is not None

    def payload(self):
        return {
            "candidate_start": self.candidate_start.isoformat() if self.candidate_start else None,
            "logging": self.logging,
            "pending_end": self.pending_end.isoformat() if self.pending_end else None,
        }

    def restore(self, stored):
        """Take back what was saved before a restart; anything unreadable is dropped."""
        try:
            start, end = stored.get("candidate_start"), stored.get("pending_end")
            self.candidate_start = dt_util.parse_datetime(start) if start else None
            self.pending_end = dt_util.parse_datetime(end) if end else None
            self.logging = bool(stored.get("logging"))
        except (AttributeError, TypeError, ValueError):
            self.reset()
        if self.candidate_start is None:
            self.reset()

    def reset(self):
        self.candidate_start = None
        self.pending_end = None
        self.logging = False

    # ----- timers -----

    def _cancel(self, name):
        cancel = getattr(self, name)
        if cancel:
            cancel()
            setattr(self, name, None)

    def cancel_timers(self):
        self._cancel("_min_timer")
        self._cancel("_gap_timer")

    def _schedule(self, name, due, handler):
        """Run handler at `due` (straight away when that has passed), replacing any timer of this kind."""
        self._cancel(name)
        delay = max(0.0, (due - dt_util.utcnow()).total_seconds())

        @callback
        def fire(_now):
            setattr(self, name, None)
            self.manager.hass.async_create_task(handler())

        setattr(self, name, async_call_later(self.manager.hass, delay, fire))

    def arm(self):
        """Start whatever timer the current state is waiting on."""
        if self.candidate_start is None:
            return
        if self.pending_end is not None:
            self._schedule("_gap_timer", self.pending_end + self.gap, self._async_gap_elapsed)
        elif not self.logging:
            self._schedule("_min_timer", self.candidate_start + self.minimum, self._async_min_elapsed)

    # ----- the entity changed -----

    def evaluate(self, state, when):
        """Take the source entity's state (as it was at `when`) into the state machine."""
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.debug("%s is %s; ignoring it", self.entity_id, state.state if state else "missing")
            return
        if state.state.lower() in self.asleep_states:
            if self.pending_end is not None:
                # Back to sleep inside the gap: it is the same sleep
                self.pending_end = None
                self._cancel("_gap_timer")
                self.arm()
            elif self.candidate_start is None:
                self.candidate_start = when
                self.logging = False
                self.arm()
            else:
                return
        elif self.candidate_start is not None and self.pending_end is None:
            self.pending_end = when
            self._cancel("_min_timer")
            self.arm()
        else:
            return
        self.manager.changed()

    # ----- timers fired -----

    async def _async_min_elapsed(self):
        async with self._lock:
            if self.candidate_start is None or self.logging or self.pending_end is not None:
                return
            await self._async_start()

    async def _async_gap_elapsed(self):
        async with self._lock:
            if self.candidate_start is None or self.pending_end is None:
                return
            if not self.logging:
                if self.pending_end - self.candidate_start < self.minimum:
                    _LOGGER.debug("The sleep seen on %s was too short to log", self.entity_id)
                    self.reset()
                    self.manager.changed()
                    return
                if not await self._async_start():
                    return
            await self._async_end()

    def _note(self):
        state = self.manager.hass.states.get(self.entity_id)
        return f"From {state.name if state else self.entity_id}"

    def _already_sleeping(self):
        """Whether Baby Tracker already shows a sleep in progress for this baby (e.g. started by hand)."""
        coordinator = self.manager.coordinator
        baby_data = ((coordinator.data or {}).get("baby_data") or {}).get(coordinator.baby_name_for(self.baby_id)) or {}
        return bool((baby_data.get("last_sleep") or {}).get("is_sleeping"))

    async def _async_start(self):
        """Write the sleep start, back-dated to when the entity went to sleep. True when the sleep is on record."""
        if self._already_sleeping():
            _LOGGER.info("A sleep is already in progress for %s; not starting a second one", self.baby_id)
            self.logging = True
            self.manager.changed()
            return True
        try:
            await async_log_sleep(
                self.manager.hass, self.manager.coordinator, self.baby_id, True,
                note=self._note(), moment=self.candidate_start)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not log the sleep start from %s: %s", self.entity_id, err)
            return False
        self.logging = True
        self.manager.changed()
        return True

    async def _async_end(self):
        """Write the sleep end at the moment the entity left the asleep state."""
        try:
            await async_log_sleep(
                self.manager.hass, self.manager.coordinator, self.baby_id, False,
                note=self._note(), moment=self.pending_end)
        except HomeAssistantError as err:
            # Most likely there is no sleep to end (it was ended by hand): nothing more to do
            _LOGGER.info("Could not log the sleep end from %s: %s", self.entity_id, err)
        self.reset()
        self.manager.changed()


class SleepSourceManager:
    """The sleep sources of one config entry."""

    def __init__(self, hass: HomeAssistant, coordinator, entry):
        self.hass = hass
        self.coordinator = coordinator
        self.sources = {
            baby_id: SleepSource(self, baby_id, settings)
            for baby_id, settings in configured_sources(entry.options).items()
        }
        self._store = Store(hass, SLEEP_SOURCE_STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.sleep_source")
        self._unsubscribe = None

    def changed(self):
        """A source's state changed: save it and let the entities update."""
        self._store.async_delay_save(self._payload, 0)
        self.coordinator.async_update_listeners()

    def _payload(self):
        return {baby_id: source.payload() for baby_id, source in self.sources.items() if source.active}

    async def async_start(self):
        """Pick up what was saved, reconcile with the entities as they are now, and start listening."""
        try:
            stored = await self._store.async_load() or {}
        except (OSError, TypeError, ValueError) as err:
            _LOGGER.warning("Ignoring the saved sleep state, which could not be read: %s", err)
            stored = {}
        now = dt_util.utcnow()
        for baby_id, source in self.sources.items():
            if isinstance(stored.get(baby_id), dict):
                source.restore(stored[baby_id])
            # What happened while Home Assistant was down is only known from now on
            source.evaluate(self.hass.states.get(source.entity_id), now)
            source.arm()
        entity_ids = [source.entity_id for source in self.sources.values()]
        if entity_ids:
            self._unsubscribe = async_track_state_change_event(self.hass, entity_ids, self._async_state_changed)

    @callback
    def _async_state_changed(self, event: Event):
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        for source in self.sources.values():
            if source.entity_id == event.data["entity_id"]:
                source.evaluate(new_state, new_state.last_changed)

    async def async_stop(self):
        """Stop listening and save the state now (before an unload or reload)."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        for source in self.sources.values():
            source.cancel_timers()
        await self._store.async_save(self._payload())
