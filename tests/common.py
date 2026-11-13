"""Shared helpers for the aiomusiccast_co tests."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qsl

from aiomusiccast_co.musiccast_device import MusicCastDevice

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "http://{host}/YamahaExtendedControl/v1"

Response = dict[str, Any] | Callable[[dict[str, str]], dict[str, Any]]
Write = str | tuple[str, Any]


def load_fixture(path: str) -> Any:
    """Return the parsed JSON of ``fixtures/<path>.json``."""
    return json.loads((FIXTURES / f"{path}.json").read_text())


def load_device_fixtures(model: str) -> dict[str, dict[str, Any]]:
    """Return every captured response of ``model``, keyed by YXC path such as ``main/getStatus``."""
    root = FIXTURES / model
    return {
        file.relative_to(root).with_suffix("").as_posix(): json.loads(file.read_text())
        for file in sorted(root.rglob("*.json"))
    }


class FakeYxc:
    """Stands in for the HTTP calls of ``AsyncDevice``.

    Reads (``request_json``) are answered from captured responses keyed by YXC path, ignoring the query string except
    for ``netusb/getListInfo``, which is looked up as ``netusb/getListInfo_<input>``. Writes (``request``, ``get`` and
    ``post``) are recorded in ``writes``: GET URLs as strings and POSTs as ``(url, body)`` tuples, both still holding
    the ``{host}`` placeholder, so tests can compare them with the ``pyamaha`` URL builders. ``on_write`` lets a test
    play the device's reaction to a write, such as pushing a UDP event.
    """

    def __init__(self, responses: dict[str, Response]) -> None:
        self.responses = responses
        self.reads: list[str] = []
        self.writes: list[Write] = []
        self.on_write: Callable[[Write], Awaitable[None]] | None = None
        self.dlna = AsyncMock()

    def install(self, device: MusicCastDevice) -> None:
        """Route the device's requests through this fake."""
        device.device.request_json = AsyncMock(side_effect=self.request_json)  # type: ignore[method-assign]
        device.device.request = AsyncMock(side_effect=self.request)  # type: ignore[method-assign]
        device.device.get = AsyncMock(side_effect=self.get)  # type: ignore[method-assign]
        device.device.post = AsyncMock(side_effect=self.post)  # type: ignore[method-assign]
        device.device.dlna_avt_request = self.dlna  # type: ignore[method-assign]

    def set(self, path: str, response: Response) -> None:
        """Answer ``path`` with ``response``, a dict or a callable taking the query parameters."""
        self.responses[path] = response

    def update(self, path: str, **fields: Any) -> None:
        """Change fields of the current response for ``path``."""
        current = self.responses[path]
        assert isinstance(current, dict)
        self.responses[path] = {**current, **fields}

    def fail(self, path: str, code: int = 5) -> None:
        """Answer ``path`` with an error response_code and nothing else."""
        self.responses[path] = {"response_code": code}

    def read_count(self, path: str) -> int:
        """Return how often ``path`` was read."""
        return sum(1 for url in self.reads if _split(url)[0] == path)

    async def request_json(self, url: str) -> dict[str, Any]:
        # Yield like real I/O, so a runaway request loop can be cancelled by a timeout in the test.
        await asyncio.sleep(0)
        self.reads.append(url)
        path, query = _split(url)
        if path == "netusb/getListInfo" and f"{path}_{query.get('input')}" in self.responses:
            path = f"{path}_{query['input']}"
        if path not in self.responses:
            raise AssertionError(f"Unexpected YXC read: {url}")
        response = self.responses[path]
        # A fresh copy per read, like JSON decoded from an HTTP response; callers may modify it.
        return copy.deepcopy(response(query) if callable(response) else response)

    async def request(self, url: str | tuple[str, Any]) -> MagicMock:
        if isinstance(url, tuple):
            return await self.post(*url)
        return await self.get(url)

    async def get(self, url: str) -> MagicMock:
        return await self._write(url)

    async def post(self, url: str, data: Any) -> MagicMock:
        return await self._write((url, data))

    async def _write(self, write: Write) -> MagicMock:
        await asyncio.sleep(0)
        self.writes.append(write)
        if self.on_write is not None:
            await self.on_write(write)
        return MagicMock()


async def create_device(yxc: FakeYxc, host: str = "192.0.2.1") -> MusicCastDevice:
    """Return a device served by ``yxc`` that has been fetched once, with the requests of that fetch cleared."""
    device = MusicCastDevice(host, MagicMock())
    yxc.install(device)
    await device.fetch()
    yxc.reads.clear()
    yxc.writes.clear()
    return device


CLOCK_FEATURES = {
    "func_list": ["date_and_time", "alarm"],
    "alarm_mode_list": ["oneday", "weekly"],
    "range_step": [
        {"id": "alarm_volume", "min": 0, "max": 60, "step": 2},
        {"id": "alarm_fade", "min": 1, "max": 30, "step": 1},
    ],
    "alarm_input_list": ["tuner", "audio1"],
    "alarm_preset_list": ["netusb", "tuner"],
}

CLOCK_SETTINGS = {
    "response_code": 0,
    "alarm": {
        "alarm_on": True,
        "volume": 30,
        "mode": "weekly",
        "oneday": {
            "enable": False,
            "time": "0630",
            "beep": False,
            "playback_type": "resume",
            "resume": {"input": "tuner"},
        },
        "monday": {
            "enable": True,
            "time": "0700",
            "beep": True,
            "playback_type": "preset",
            "preset": {"type": "netusb", "num": 2, "netusb_info": {"input": "net_radio", "text": "Jazz"}},
        },
        "tuesday": {
            "enable": True,
            "time": "0715",
            "playback_type": "preset",
            "preset": {"type": "tuner", "num": 1, "tuner_info": {"band": "fm", "number": 98100}},
        },
    },
}


def add_missing_features(yxc: FakeYxc) -> None:
    """Add the features the RX-A4A lacks to its captured responses, so every capability can be tested.

    These additions are hand-written after the YXC specification, not captured: a dimmer, speaker A/B, a clock with
    alarms, and the soundbar-style sound features (equalizer, clear voice, 3D surround, bass extension, link audio
    quality) on the main zone.
    """
    features = yxc.responses["system/getFeatures"]
    assert isinstance(features, dict)
    system = features["system"]
    system["func_list"] += ["dimmer", "speaker_a", "speaker_b"]
    system["range_step"] = [*system.get("range_step", []), {"id": "dimmer", "min": -1, "max": 15, "step": 1}]
    features["clock"] = CLOCK_FEATURES

    main = next(zone for zone in features["zone"] if zone["id"] == "main")
    main["func_list"] += ["equalizer", "clear_voice", "surround_3d", "bass_extension", "link_audio_quality"]
    main["range_step"].append({"id": "equalizer", "min": -10, "max": 10, "step": 1})
    main["equalizer_mode_list"] = ["manual", "auto", "bypass"]
    main["link_audio_quality_list"] = ["compressed", "uncompressed"]

    yxc.update(
        "main/getStatus",
        equalizer={"mode": "manual", "low": 0, "mid": 1, "high": -1},
        clear_voice=False,
        surround_3d=True,
        bass_extension=True,
        link_audio_quality="uncompressed",
    )
    yxc.update("system/getFuncStatus", speaker_a=True, speaker_b=False, dimmer=5)
    yxc.set("clock/getSettings", CLOCK_SETTINGS)


def _split(url: str) -> tuple[str, dict[str, str]]:
    """Split a YXC URL template into its path below ``v1/`` and its query parameters."""
    path, _, query = url.removeprefix(f"{BASE}/").partition("?")
    return path, dict(parse_qsl(query))
