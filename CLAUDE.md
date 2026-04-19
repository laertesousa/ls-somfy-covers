# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant custom integration (`custom_components/ls_somfy_covers`) that controls Somfy PoE shades over the LAN. The HA `domain` is `ls_somfy_covers` and it registers two platforms: `cover` and `sensor`.

The repo lives inside a Home Assistant config tree, so there is no separate build step — HA loads the integration directly from this directory and re-loads it via the integration's options flow (`reload()` schedules `hass.config_entries.async_reload`).

## Running / testing

- No test suite. `test_scanner.py` is a standalone script for exercising the network scanner outside HA: `python test_scanner.py` (run from the integration root, requires the deps in `somfy/requirements.txt`).
- To exercise integration changes, restart Home Assistant (or reload the integration from the UI). The options flow's `reload()` helper handles re-loading after device edits.
- `somfy/requirements.txt` lists the runtime deps (`requests`, `urllib3`, `aiohttp` is via HA). Note the `manifest.json` declares no requirements — HA-bundled deps are assumed.

## Architecture

### Entry points and lifecycle

- `__init__.py:async_setup_entry` stores merged `entry.data + entry.options` under `hass.data[DOMAIN][entry_id]` and forwards setup to `cover` + `sensor` platforms (listed in `const.PLATFORMS`).
- `cover.async_setup_entry` iterates devices from the HA device registry that belong to this config entry, builds a `SomfyPoeBlindClient` per device, and registers a 2-minute `async_track_time_interval` refresh. Cancellation handles are appended to `hass.data[DOMAIN][entry_id]["task_removers"]` and torn down in `async_unload_entry` — when adding new periodic tasks, register their removers there too.
- All Somfy HTTP I/O is blocking `requests`, so callers wrap it with `hass.async_add_executor_job(...)`. Don't `await` `client.*` directly.

### Config flow (`config_flow.py`)

There are two flows:

1. **Initial setup** (`SomfyIntegrationConfigFlow`) — captures `subnet` and `enable_mac_discovery`, stored in `entry.data`.
2. **Options flow** (`DeviceOptionsFlowHandler`) — menu-driven (`async_step_init`) with: discovery, add/edit/remove device, edit settings, clear.

Per-device config is stored in `entry.options` keyed by HA device-registry ID (not MAC). The shape per device is roughly `{"ip", "pin", "mac", "name", "model", "firmware", "hardware", "hostname"}`. `helpers/devices.get_device_options(entry, device_id)` is the canonical accessor.

**Draft devices**: discovery creates devices in the registry with `name="Draft <ip> - <mac>"` and **no `pin`** in options. `cover.py` skips them (no PIN → no entity). They become real shades when the user runs Edit Device, which calls `_create_device` to log in, fetch metadata via `client.get_info`, and re-create the registry entry keyed on the real MAC. When touching device-options shape, preserve this draft → real transition (see `async_step_edit_device_details`).

### Somfy client (`somfy/`)

- `SomfyPoeBlindClient` — login via form POST, then JSON-RPC-ish commands to `/req` (e.g. `move.up`, `move.down`, `move.to`, `move.stop`, `status.position`, `status.info`). Sessions are cookie-based (`sessionId`).
- `utils/session.get_legacy_session` builds a `requests.Session` with a permissive SSL context (`OP_LEGACY_SERVER_CONNECT`, no cert verify) — the Somfy firmware needs this; do not "fix" it by tightening TLS.
- `Scanner` — iterates a subnet, pings each host, then resolves MAC. Two MAC paths:
  - Local `arp -n` (when HA is on the host network).
  - HTTP fallback to `http://host.docker.internal:5001/arp/<ip>` (when HA runs in Docker and the ARP table isn't visible). Toggled by the `enable_mac_discovery` option — `False` ⇒ use the HTTP mock endpoint.
  - Devices are matched by MAC prefix (`SOMFY_MAC_PREFIXES = ["4C:C2:06"]`, defined in both `Scanner.py` and `SomfyPoeBlindClient.py`).

### Cover position semantics

Somfy reports `0 = fully open`, `100 = fully closed`. Home Assistant uses the opposite. The integration converts with `100 - status.position.value` in `async_update` and `100 - position` in `async_set_cover_position`. Preserve this inversion when editing position logic.

### Sensors

`sensor.py` exposes diagnostic sensors: a global `Subnet` sensor under a synthetic "Configuration" device, plus per-device sensors for every key in the device's options dict (ip, mac, pin, etc.) and a derived `available` sensor (true iff `pin` is set). Adding new device-options keys automatically surfaces them as sensors.

### Blueprints

`blueprints/automation/zooz_scene_controller.yaml` is a user-facing HA automation blueprint for binding a Zooz ZEN32 scene controller to a cover entity (open / close / 2x-press to stop). Not loaded by the Python integration.
