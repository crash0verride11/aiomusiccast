#!/usr/bin/env python
"""Capture YXC responses from a MusicCast device as test fixtures.

Only read-only GET endpoints are called. Network identifiers (MAC/IP addresses, device and group ids, SSIDs, Wi-Fi
key, AirPlay PIN, network name) are replaced with placeholders, and user-given or user-specific names (inputs, zones,
scenes, group, presets, list entries, now playing) with generic ones, before anything is written, so the output can be
committed. Check the output anyway before committing it.

Usage::

    python scripts/capture_fixtures.py 192.0.2.20 rx_a4a
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = "http://{host}/YamahaExtendedControl/v1"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

SYSTEM = ["getDeviceInfo", "getFeatures", "getNetworkStatus", "getFuncStatus", "getNameText"]
ZONE = ["getStatus", "getSceneInfo"]
LIST_INPUTS = ["net_radio", "server", "usb"]

# Keys whose values identify the device or the network it is on.
REDACT: dict[str, Any] = {
    "device_id": "00A0DE000000",
    "serial_number": "Y000000XX",
    "system_id": "00000000",
    "ip_address": "192.0.2.1",
    "subnet_mask": "255.255.255.0",
    "default_gateway": "192.0.2.254",
    "dns_server_1": "192.0.2.254",
    "dns_server_2": "0.0.0.0",
    "ssid": "redacted",
    "location_id": "00000000000000000000000000000000",
    "uuid": "00000000-0000-0000-0000-000000000000",
    "key": "redacted",
    "airplay_pin": "0000",
}
REDACT_MAC = "00A0DE000000"
# An all-zero group id means "not grouped" and is kept; any other group id is replaced.
NULL_GROUP = "00000000000000000000000000000000"
REDACT_GROUP = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


def redact_ip(value: str) -> str:
    """Return a documentation address in place of an IPv4/IPv6 address, else ``value`` unchanged."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return value
    if address.is_unspecified:
        return value
    return "192.0.2.1" if address.version == 4 else "fe80::1"


def sanitize(value: Any, network_name: str) -> Any:
    """Return ``value`` with identifying fields replaced."""
    if isinstance(value, str):
        return redact_ip(value)
    if isinstance(value, list):
        return [sanitize(item, network_name) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == "mac_address" and isinstance(item, dict):
            result[key] = dict.fromkeys(item, REDACT_MAC)
        elif key == "mac_address":
            result[key] = REDACT_MAC
        elif key == "network_name":
            result[key] = network_name
        elif key == "group_id" and item not in ("", None, NULL_GROUP):
            result[key] = REDACT_GROUP
        elif key in REDACT and item not in ("", None):
            result[key] = REDACT[key]
        else:
            result[key] = sanitize(item, network_name)
    return result


def input_name(input_id: str) -> str:
    """Return the generic name of an input, e.g. ``NET RADIO`` for ``net_radio``."""
    return input_id.upper().replace("_", " ")


def zone_name(zone_id: str) -> str:
    """Return the generic name of a zone, e.g. ``Main`` or ``Zone2``."""
    return zone_id.capitalize()


def genericize_names(path: str, data: dict[str, Any]) -> dict[str, Any]:
    """Replace user-given or user-specific names in the response for ``path``.

    Covers inputs, zones, scenes, groups, presets, list entries and what is playing.
    """
    if path == "system/getNameText":
        for zone in data.get("zone_list", []):
            zone["text"] = zone_name(zone["id"])
        for source in data.get("input_list", []):
            source["text"] = input_name(source["id"])
    elif path.endswith("/getStatus") and "input_text" in data:
        data["input_text"] = input_name(data["input"])
    elif path.endswith("/getSceneInfo"):
        for scene in data.get("scene_list", []):
            scene["text"] = f"SCENE{scene['num']}"
    elif path == "dist/getDistributionInfo" and data.get("group_name"):
        data["group_name"] = f"(Linked) {zone_name(data.get('server_zone') or 'main')}"
    elif path == "netusb/getPresetInfo":
        for num, preset in enumerate(data.get("preset_info", []), start=1):
            if preset.get("text"):
                preset["text"] = f"Preset {num}"
    elif path == "netusb/getPlayInfo":
        for key, generic in (("artist", "Artist"), ("album", "Album"), ("track", "Track")):
            if data.get(key):
                data[key] = generic
        if data.get("albumart_url"):
            data["albumart_url"] = "/YamahaRemoteControl/AlbumART/AlbumART0.jpg"
    elif path.startswith("netusb/getListInfo"):
        # Entries can be DLNA server names, folders or stations; thumbnails can be URLs with host names.
        for index, entry in enumerate(data.get("list_info", []), start=data.get("index", 0) + 1):
            if entry.get("text"):
                entry["text"] = f"Item {index}"
            if entry.get("thumbnail"):
                entry["thumbnail"] = ""
    return data


def fetch(host: str, path: str) -> dict[str, Any] | None:
    """GET ``path`` from the device and return its JSON, or None on failure."""
    url = f"{BASE.format(host=host)}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            return json.loads(response.read().decode("utf-8", errors="ignore"))
    except (urllib.error.URLError, TimeoutError, ValueError) as err:
        print(f"  ! {path}: {err}", file=sys.stderr)
        return None


def main() -> None:
    """Capture fixtures from the device given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("host", help="device IP address")
    parser.add_argument("name", help="fixture folder name, e.g. rx_a4a")
    args = parser.parse_args()

    out = FIXTURES / args.name
    captured: dict[str, dict[str, Any]] = {}

    def capture(path: str, file: str | None = None) -> dict[str, Any] | None:
        data = fetch(args.host, path)
        if data is not None:
            captured[file or path] = data
            print(f"  {path}: response_code={data.get('response_code')}")
        return data

    for endpoint in SYSTEM:
        capture(f"system/{endpoint}")

    features = captured.get("system/getFeatures", {})
    model = captured.get("system/getDeviceInfo", {}).get("model_name", args.name)
    network_name = f"Yamaha {model}"

    for zone in features.get("zone", []):
        for endpoint in ZONE:
            capture(f"{zone['id']}/{endpoint}")

    if "netusb" in features:
        capture("netusb/getPlayInfo")
        capture("netusb/getPresetInfo")
        inputs = {i["id"] for i in features.get("system", {}).get("input_list", [])}
        for source in LIST_INPUTS:
            if source in inputs:
                capture(
                    f"netusb/getListInfo?input={source}&index=0&size=8&lang=en",
                    f"netusb/getListInfo_{source}",
                )
    if "tuner" in features:
        capture("tuner/getPlayInfo")
    capture("dist/getDistributionInfo")
    if "clock" in features:
        capture("clock/getSettings")

    for path, data in captured.items():
        target = out / f"{path}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        cleaned = genericize_names(path, sanitize(data, network_name))
        target.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(captured)} fixtures to {out}")


if __name__ == "__main__":
    main()
