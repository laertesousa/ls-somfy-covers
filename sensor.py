import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .helpers.devices import get_devices_for_entry, get_device_options, build_device_info
# from .somfy.classes.SomfyPoeBlindClient import SomfyPoeBlindClient

logger = logging.getLogger("Sensor")

async def async_setup_entry(hass, config_entry, async_add_entities):
    devices = await get_devices_for_entry(hass, config_entry)
    entities = []
    logger.info(f"Found {len(devices)} devices")
    config_entry.data.get("subnet")
    entities.append(ReadOnlyValueSensor("Subnet", config_entry.data.get("subnet")))

    for device in devices:
        device_options = get_device_options(config_entry, device.id)

        if not device_options:
            logger.info(f"{device.identifiers} has no options")
            continue

        logger.info(f"Creating sensors for {device.identifiers}")
        # client = SomfyPoeBlindClient.init_with_device(device_options)
        # await hass.async_add_executor_job(client.login)
        # device_info = await hass.async_add_executor_job(client.get_info)
        for key in device_options:
            logger.info(f"{key}: {device_options[key]}")
            entities.append(DeviceDetailsSensor(device, key, device_options[key]))

        is_available = device_options.get("pin") is not None
        entities.append(DeviceDetailsSensor(device, "available", is_available, "mdi:check-network" if is_available else "mdi:close-network"))

    async_add_entities(entities)

class DeviceDetailsSensor(SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    def __init__(self, device, label, value, icon = None):
        self._device = device
        self._attr_name = label
        self._attr_unique_id = f"{device.id}_{label}"
        self._attr_native_value = value
        self._attr_icon = icon

    @property
    def device_info(self) -> DeviceInfo:
        return build_device_info(self._device)

    @property
    def native_value(self):
        return self._attr_native_value

class ReadOnlyValueSensor(SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    def __init__(self, label, value, icon = None):
        self._attr_name = label
        self._attr_unique_id = label
        self._attr_native_value = value
        self._attr_icon = icon

    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, "global")},
            "name": "Configuration",
        }

    @property
    def native_value(self):
        return self._attr_native_value
