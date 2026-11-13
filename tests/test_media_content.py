"""Tests for browsing media with MusicCastMediaContent."""

import logging
from typing import Any

import pytest

from aiomusiccast_co.musiccast_device import MusicCastDevice
from aiomusiccast_co.musiccast_media_content import MusicCastMediaContent
from aiomusiccast_co.pyamaha import NetUSB

from .common import FakeYxc, Write

BROWSE = 0b10
PLAY = 0b100
SEARCH = 0b1000


class ListBrowser:
    """Plays the device's NET RADIO list navigation: a list per menu layer, entered by select and left by return."""

    def __init__(self, yxc: FakeYxc, layers: list[list[dict[str, Any]]], layer: int = 0) -> None:
        self.layers = layers
        self.layer = layer
        # Replace the captured per-input lists, which FakeYxc would otherwise prefer.
        for path in [path for path in yxc.responses if path.startswith("netusb/getListInfo_")]:
            del yxc.responses[path]
        yxc.set("netusb/getListInfo", self.list_info)
        yxc.on_write = self.on_write

    def list_info(self, query: dict[str, str]) -> dict[str, Any]:
        items = self.layers[self.layer]
        index = int(query["index"])
        return {
            "response_code": 0,
            "input": query["input"],
            "menu_layer": self.layer,
            "max_line": len(items),
            "index": index,
            "menu_name": f"Layer {self.layer}",
            "list_info": items[index : index + int(query["size"])],
        }

    async def on_write(self, write: Write) -> None:
        if isinstance(write, str) and "type=select" in write:
            self.layer += 1
        elif isinstance(write, str) and "type=return" in write:
            self.layer -= 1


def items(count: int, attribute: int, prefix: str = "Item") -> list[dict[str, Any]]:
    return [{"text": f"{prefix} {i}", "thumbnail": "", "attribute": attribute} for i in range(count)]


def titles(content: MusicCastMediaContent) -> list[str | None]:
    return [child.title for child in content.children]


def test_categories(device: MusicCastDevice) -> None:
    library = MusicCastMediaContent.categories(device, "main")

    assert (library.title, library.content_type, library.can_browse) == ("Library", "categories", True)
    assert [child.content_id for child in library.children] == [
        "presets",
        "input:amazon_music",
        "input:deezer",
        "input:napster",
        "input:net_radio",
        "input:pandora",
        "input:qobuz",
        "input:server",
        "input:siriusxm",
        "input:usb",
    ]
    assert library.children[4].title == "NET RADIO"


async def test_browse_presets(device: MusicCastDevice) -> None:
    device.data.netusb_preset_list = {1: ("net_radio", "Jazz FM"), 4: ("server", "Album")}

    presets = await MusicCastMediaContent.browse_media(device, "main", ["presets"])

    assert (presets.title, presets.content_type) == ("Presets", "directory")
    assert [(c.content_id, c.title, c.can_play) for c in presets.children] == [
        ("presets:1", "net_radio - Jazz FM", True),
        ("presets:4", "server - Album", True),
    ]


async def test_browse_input_returns_to_the_top_of_the_list(device: MusicCastDevice, yxc: FakeYxc) -> None:
    browser = ListBrowser(yxc, [items(3, BROWSE), items(2, BROWSE), items(5, PLAY)], layer=2)

    content = await MusicCastMediaContent.browse_media(device, "main", ["input", "net_radio"])

    assert browser.layer == 0
    assert yxc.writes == [NetUSB.set_list_control("main", "return", "", "main")] * 2
    assert (content.title, content.menu_layer, content.content_id) == ("Layer 0", 0, "list:net_radio:0:<>0")
    assert titles(content) == ["Item 0", "Item 1", "Item 2"]
    assert (content.content_type, content.can_play, content.has_next_page) == ("directory", False, False)


async def test_browse_selects_an_item(device: MusicCastDevice, yxc: FakeYxc) -> None:
    browser = ListBrowser(yxc, [items(3, BROWSE), items(4, PLAY, "Station")])

    content = await MusicCastMediaContent.browse_media(device, "main", ["list", "net_radio", "1", "2"])

    assert browser.layer == 1
    assert yxc.writes == [NetUSB.set_list_control("main", "select", "2", "main")]
    assert titles(content) == ["Station 0", "Station 1", "Station 2", "Station 3"]
    assert [child.content_id for child in content.children][:2] == ["list:net_radio:2:0", "list:net_radio:2:1"]
    assert (content.content_type, content.can_play) == ("track", True)


async def test_browse_back_to_an_upper_layer(device: MusicCastDevice, yxc: FakeYxc) -> None:
    browser = ListBrowser(yxc, [items(3, BROWSE), items(2, BROWSE), items(5, PLAY)], layer=2)

    content = await MusicCastMediaContent.browse_media(device, "main", ["list", "net_radio", "0", "<>0"])

    assert browser.layer == 0
    assert content.menu_layer == 0


async def test_browse_unexpected_layer_is_logged(
    device: MusicCastDevice, yxc: FakeYxc, caplog: pytest.LogCaptureFixture
) -> None:
    ListBrowser(yxc, [items(3, BROWSE), items(2, BROWSE)], layer=1)

    with caplog.at_level(logging.WARNING):
        content = await MusicCastMediaContent.browse_media(device, "main", ["list", "net_radio", "3", "<>0"])

    assert "Unexpected menu layer. Expected 3, found 1" in caplog.text
    assert content.menu_layer == 1


async def test_browse_pages(device: MusicCastDevice, yxc: FakeYxc) -> None:
    ListBrowser(yxc, [items(20, PLAY)])

    first = await MusicCastMediaContent.browse_media(device, "main", ["input", "net_radio"])
    second = await MusicCastMediaContent.browse_media(device, "main", ["list", "net_radio", "0", "<>8"])

    assert titles(first)[-1] == "Next Page"
    assert first.children[-1].content_id == "list:net_radio:0:<>8"
    assert (first.has_previous_page, first.has_next_page) == (False, True)
    assert titles(second)[:-1] == [f"Item {i}" for i in range(8, 16)]
    assert second.children[-1].content_id == "list:net_radio:0:<>16"
    assert (second.has_previous_page, second.has_next_page) == (True, True)


async def test_browse_last_page(device: MusicCastDevice, yxc: FakeYxc) -> None:
    ListBrowser(yxc, [items(20, PLAY)])

    last = await MusicCastMediaContent.browse_media(device, "main", ["list", "net_radio", "0", "<>16"])

    assert titles(last) == ["Item 16", "Item 17", "Item 18", "Item 19"]
    assert (last.has_previous_page, last.has_next_page) == (True, False)


async def test_browse_page_that_ends_exactly_at_the_list_end(device: MusicCastDevice, yxc: FakeYxc) -> None:
    ListBrowser(yxc, [items(16, PLAY)])

    last = await MusicCastMediaContent.browse_media(device, "main", ["list", "net_radio", "0", "<>8"])

    assert titles(last) == [f"Item {i}" for i in range(8, 16)]
    assert last.has_next_page is False


async def test_browse_longer_pages_read_several_batches(device: MusicCastDevice, yxc: FakeYxc) -> None:
    ListBrowser(yxc, [items(20, PLAY)])

    content = await MusicCastMediaContent.browse_media(device, "main", ["input", "net_radio"], list_len=16)

    assert titles(content)[:-1] == [f"Item {i}" for i in range(16)]
    assert content.children[-1].content_id == "list:net_radio:0:<>16"
    assert [read for read in yxc.reads if "index=8" in read]


async def test_browse_unknown_method_raises(device: MusicCastDevice) -> None:
    with pytest.raises(ValueError, match="unknown browse method"):
        await MusicCastMediaContent.browse_media(device, "main", ["albums"])


@pytest.mark.parametrize(
    ("attribute", "can_browse", "can_play", "can_search", "content_type"),
    [
        (BROWSE, True, False, False, "directory"),
        (PLAY, False, True, False, "track"),
        (BROWSE | SEARCH, True, False, True, "directory"),
        (None, False, False, False, "track"),
    ],
)
def test_from_info(
    attribute: int | None, can_browse: bool, can_play: bool, can_search: bool, content_type: str
) -> None:
    info = {"text": "Jazz", "thumbnail": "http://192.0.2.9/jazz.png", "attribute": attribute}

    content = MusicCastMediaContent.from_info("net_radio", info, 2, 5)

    assert (content.can_browse, content.can_play, content.can_search) == (can_browse, can_play, can_search)
    assert (content.title, content.thumbnail, content.content_type) == (
        "Jazz",
        "http://192.0.2.9/jazz.png",
        content_type,
    )
    assert (content.content_id, content.menu_layer) == ("list:net_radio:2:5", 2)


def test_device_needs_a_zone(device: MusicCastDevice) -> None:
    with pytest.raises(ValueError, match="Zone id must be provided"):
        MusicCastMediaContent(musiccast=device)


async def test_operations_need_device_and_zone(device: MusicCastDevice) -> None:
    with pytest.raises(ValueError, match="MusicCast device must be provided"):
        await MusicCastMediaContent(zone_id="main").load_list("net_radio")
    content = MusicCastMediaContent(musiccast=device, zone_id="main")
    content.zone_id = None
    with pytest.raises(ValueError, match="Zone id is required"):
        # The captured list is on layer 0, so reaching layer 5 needs a return command for the zone.
        await content.return_in_list_info("net_radio", until_layer=5)
