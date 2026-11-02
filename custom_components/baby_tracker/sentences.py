"""
The Assist sentence files.

Home Assistant reads custom sentences only from <config>/custom_sentences/<language>/, not from an
integration's folder, and a list of the babies' names has to be in them. So the integration ships a
template (custom_sentences/<language>/baby_tracker.yaml), renders it with the real baby names, and
compares the result with the file in the config directory. When it differs, a repair offers to write it
(repairs.py); nothing is written to the config directory without that confirmation.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import yaml
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN, ISSUE_CUSTOM_SENTENCES

_LOGGER = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "custom_sentences"
FILE_NAME = "baby_tracker.yaml"
HEADER = (
    "# Written by the Baby Tracker integration from the names of your babies (Settings > Repairs offers to\n"
    "# update it when they change). Changes made here are replaced then.\n"
)

_TEMPLATE_SYNTAX = re.compile(r"[\[\]\(\)\{\}<>|]")


def baby_values(names):
    """
    The entries of the sentences' baby list: each name, matched as it is spoken and answered with the
    name itself. Characters that mean something in a sentence template are left out of what is matched.
    """
    values, seen = [], set()
    for name in sorted({n.strip() for n in names if n and n.strip()}, key=str.casefold):
        spoken = " ".join(_TEMPLATE_SYNTAX.sub(" ", name).split())
        if not spoken or spoken.casefold() in seen:
            continue
        seen.add(spoken.casefold())
        values.append(name if spoken == name else {"in": spoken, "out": name})
    return values


def render(template: str, names) -> str:
    """The template with the babies' names in its baby list, as the text of the file to install."""
    data = yaml.safe_load(template)
    data["lists"]["baby"]["values"] = baby_values(names)
    return HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=10000)


def template_languages():
    """{language: template text} for every language the integration has sentences in."""
    return {
        path.parent.name: path.read_text(encoding="utf-8")
        for path in sorted(TEMPLATE_DIR.glob(f"*/{FILE_NAME}"))
    }


def installed_path(hass: HomeAssistant, language: str) -> str:
    return hass.config.path("custom_sentences", language, FILE_NAME)


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return None


def out_of_date(config_path, names):
    """The languages whose sentence file in the config directory is missing or differs (blocking)."""
    stale = []
    for language, template in template_languages().items():
        wanted = render(template, names)
        path = os.path.join(config_path, "custom_sentences", language, FILE_NAME)
        if _read(path) != wanted:
            stale.append(language)
    return stale


def write(config_path, names):
    """Write the rendered sentence files into the config directory (blocking). Returns the paths."""
    written = []
    for language, template in template_languages().items():
        folder = os.path.join(config_path, "custom_sentences", language)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, FILE_NAME)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(render(template, names))
        os.replace(temporary, path)
        written.append(path)
    return written


def baby_names(coordinator):
    return [baby.name for baby in (coordinator.data or {}).get("babies") or []]


async def async_check_sentences(hass: HomeAssistant, coordinator) -> None:
    """Raise the repair to install the sentences when they are missing or out of date, else clear it."""
    names = baby_names(coordinator)
    try:
        stale = await hass.async_add_executor_job(out_of_date, hass.config.path(), names) if names else []
    except (OSError, ValueError, yaml.YAMLError) as err:
        _LOGGER.debug("Could not check the Assist sentences: %s", err)
        return
    if not stale:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_CUSTOM_SENTENCES)
        return
    ir.async_create_issue(
        hass, DOMAIN, ISSUE_CUSTOM_SENTENCES,
        is_fixable=True, severity=ir.IssueSeverity.WARNING, translation_key=ISSUE_CUSTOM_SENTENCES,
        # The example commands use one of the account's own babies
        translation_placeholders={"folder": hass.config.path("custom_sentences"), "baby": names[0]},
    )


async def async_install_sentences(hass: HomeAssistant, coordinator) -> list[str]:
    """Write the sentence files and ask the conversation agent to read them. Raises OSError."""
    written = await hass.async_add_executor_job(write, hass.config.path(), baby_names(coordinator))
    _LOGGER.info("Wrote the Baby Tracker Assist sentences: %s", ", ".join(written))
    if hass.services.has_service("conversation", "reload"):
        try:
            await hass.services.async_call("conversation", "reload", {}, blocking=False)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not reload the conversation agent: %s", err)
    return written
