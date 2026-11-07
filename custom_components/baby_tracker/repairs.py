"""Repairs that fix themselves when confirmed."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.exceptions import ServiceValidationError

from .sentences import async_install_sentences, baby_names
from .services import get_coordinator

_LOGGER = logging.getLogger(__name__)


class SentencesRepairFlow(RepairsFlow):
    """Write the Assist sentence file (with the babies' names) into the config directory."""

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> FlowResult:
        try:
            coordinator = get_coordinator(self.hass)
        except ServiceValidationError:
            return self.async_abort(reason="no_entry")

        errors = {}
        if user_input is not None:
            try:
                await async_install_sentences(self.hass, coordinator)
            except OSError as err:
                _LOGGER.error("Could not write the Baby Tracker Assist sentences: %s", err)
                errors["base"] = "write_failed"
            else:
                return self.async_create_entry(data={})

        names = baby_names(coordinator)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            errors=errors,
            # The form's text is filled from these, not from the issue's placeholders
            description_placeholders={
                "folder": self.hass.config.path("custom_sentences"),
                "baby": names[0] if names else "Ava",
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Create the flow that fixes a fixable Baby Tracker issue."""
    return SentencesRepairFlow()
