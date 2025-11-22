import logging
from datetime import timedelta
from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from .const import DOMAIN, PLATFORMS

from .somfy.classes.SomfyPoeBlindClient import SomfyPoeBlindClient
from .somfy.dtos.somfy_objects import Direction
from .helpers.devices import get_devices_for_entry, get_device_options, build_device_info

logger = logging.getLogger("Cover")

async def async_setup_entry(hass, entry, async_add_entities):
    devices = await get_devices_for_entry(hass, entry)
    logger.info(f"Found {len(devices)} devices")
    for device in devices:
        await _load_device(hass, entry, device, async_add_entities)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Attempt to unload platforms (e.g., cover)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Cancel periodic task if it was registered
        task_removers = hass.data[DOMAIN][entry.entry_id].get("task_removers")
        logger.info(f"Removing {len(task_removers)} tasks.")
        for task_remover in task_removers:
            task_remover() # This cancels the timer

        # Clean up stored data
        # hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def _load_device(hass, entry, device, async_add_entities):
    entry_id = entry.entry_id
    device_options = get_device_options(entry, device.id)

    if not device_options:
        logger.info(f"{device.identifiers} has no options")
        return

    if not device_options.get("pin"):
        logger.info(f"{device.identifiers} pin not set.")
        return

    logger.info(f"{device.identifiers} has options: {device_options}")
    async def on_failure(e):
        logger.error('Somfy callback error: %s', e)
        await hass.async_create_task(
            hass.config_entries.async_reload(entry_id)
        )

    client = SomfyPoeBlindClient.init_with_device(device_options, on_failure)
    cover_entity = SomfyCover(device, device_options, client)

    await hass.async_add_executor_job(client.login)

    hass.data.setdefault(DOMAIN, {}).setdefault(entry.entry_id, {})
    async_add_entities([cover_entity])

    async def periodic_refresh(now):
        logger.debug("Refreshing cover for device: %s - %s", client.ip, device.id)
        await hass.async_add_executor_job(client.login)
        await cover_entity.async_update()

    # ⏱ Set interval to 2 minutes
    task_remover = async_track_time_interval(hass, periodic_refresh, timedelta(minutes=2))
    hass.data[DOMAIN][entry.entry_id].setdefault("task_removers", []).append(task_remover)


class SomfyCover(CoverEntity):
    supported_features = (
        CoverEntityFeature.OPEN |
        CoverEntityFeature.CLOSE |
        CoverEntityFeature.STOP |
        CoverEntityFeature.SET_POSITION
    )

    def __init__(self, device, data, client):
        self.device = device
        self._client = client
        self._name = data["name"]
        self._ip = data["ip"]
        self._pin = data["pin"]
        self._attr_unique_id = f"{self.device.id}_cover"
        self._position = None
        self._previous_position = None
        self._is_closing = None
        self._is_opening = None

    @property
    def device_info(self):
        return build_device_info(self.device, self._ip)
    
    @property
    def extra_state_attributes(self):
        """Return additional info about the cover."""
        return {
            "ip": self._ip,
            "position_raw": self._position,
            "is_opening": self._is_opening,
            "is_closing": self._is_closing,
        }

    @property
    def available(self) -> bool:
        return True

    @property
    def current_cover_position(self):
        """Return the current position of the cover."""
        return self._position

    @property
    def is_closed(self) -> bool:
        """Return if the cover is closed, same as position 0."""
        return self._position == 0

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing or not."""
        return self._is_closing

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening or not."""
        return self._is_opening

    async def async_open_cover(self, **kwargs):
        await self.hass.async_add_executor_job(self._client.up)
        self._is_closing = False
        self._is_opening = True
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs):
        await self.hass.async_add_executor_job(self._client.down)
        self._is_closing = True
        self._is_opening = False
        self.async_write_ha_state()

    async def async_stop_cover(self, **kwargs):
        await self.hass.async_add_executor_job(self._client.stop)
        self._is_closing = False
        self._is_opening = False
        self.async_write_ha_state()

    async def async_update(self):
        logger.debug("update triggered - closing/opening: %s:%s", self._is_closing, self._is_opening)
        logger.debug("update triggered - position: %s:%s", self._previous_position, self._position)
        status = await self.hass.async_add_executor_job(self._client.get_status)
        logger.debug(f"Shade status - {status}")
        if status is not None and status.error is None:
            # Store previous position and movement state before updating
            self._previous_position = self._position
            was_moving = self._is_closing or self._is_opening
            
            # Update position
            self._position = 100 - status.position.value
            
            # Determine if cover is no longer moving
            if self._previous_position is not None and self._position == self._previous_position:
                self._is_closing = False
                self._is_opening = False
                self._previous_position = None
            
            self.async_write_ha_state()
        else:
            logger.warning("Unable to retrieve shade status")

    async def async_set_cover_position(self, **kwargs):
        """Move the cover to a specific position."""
        logger.debug(f"setting position {kwargs}")
        position = kwargs.get("position")
        current_position = self._position or 0
        
        await self.hass.async_add_executor_job(self._client.move, 100 - position)
        
        # Set movement flags based on direction
        if position > current_position:
            self._is_opening = True
            self._is_closing = False
        elif position < current_position:
            self._is_opening = False
            self._is_closing = True
        else:
            self._is_opening = False
            self._is_closing = False
        
        self.async_write_ha_state()