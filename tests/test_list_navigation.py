"""Tests for browsing, playing and searching netusb lists by their full path from the input's root menu."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl

import pytest

from aiomusiccast_co.exceptions import MusicCastException, MusicCastResponseException
from aiomusiccast_co.list_navigation import LIST_BLOCK_SIZE, ListNavigator, decode_steps, encode_steps
from aiomusiccast_co.musiccast_device import MusicCastDevice
from aiomusiccast_co.musiccast_media_content import (
    MusicCastMediaContent,
    entry_content_id,
    page_content_id,
    parse_path_content_id,
)
from aiomusiccast_co.pyamaha import NetUSB

from .common import FakeYxc, Write

SELECT = 0b10
PLAY = 0b100
SEARCH = 0b1000

ALBUMS_ALPHABETICAL = ["Abbey Road", "Blue Train", "Kind of Blue", "Revolver"]
ALBUMS_BY_DATE = ["Revolver", "Kind of Blue", "Blue Train", "Abbey Road"]

# Paths in the menu built by build_menu()
MY_MUSIC = (1,)
PLAYLISTS = (1, 0)
ALBUMS = (1, 1)
BY_DATE = (1, 1, 1)
FIRST_ALBUM = 2  # entries 0 and 1 of an album list are its sort entries
SEARCH_ENTRY = 2

RETURN = NetUSB.set_list_control("main", "return", "", "main")


def select(index: int) -> str:
    return NetUSB.set_list_control("main", "select", index, "main")


@dataclass
class Node:
    """A list in the menu."""

    name: str
    items: list[Item] = field(default_factory=list)


@dataclass
class Item:
    """An entry of a list."""

    text: str
    attribute: int
    child: Node | None = None


def _album(title: str) -> Item:
    return Item(title, SELECT | PLAY, Node(title, [Item(f"{title} - track {n}", PLAY) for n in (1, 2)]))


def _albums(name: str, titles: list[str], depth: int) -> Node:
    """Return an album list that offers both sort orders again, one level deeper, ``depth`` times."""
    sort_entries = [Item("Sort by alphabet", SELECT), Item("Sort by date added", SELECT)]
    if depth:
        sort_entries[0].child = _albums("Sort by alphabet", ALBUMS_ALPHABETICAL, depth - 1)
        sort_entries[1].child = _albums("Sort by date added", ALBUMS_BY_DATE, depth - 1)
    return Node(name, sort_entries + [_album(title) for title in titles])


def build_menu() -> Node:
    """Return a menu modelled on TIDAL's: sort variants of the album list, a long list and a search entry."""
    my_music = Node(
        "My music",
        [
            Item("Playlists", SELECT, Node("Playlists", [Item("Chill", PLAY), Item("Focus", PLAY)])),
            Item("Albums", SELECT, _albums("Albums", ALBUMS_ALPHABETICAL, 2)),
        ],
    )
    new = Node("New", [Item(f"Track {n:02}", PLAY) for n in range(30)])
    return Node(
        "TIDAL", [Item("New", SELECT, new), Item("My music", SELECT, my_music), Item("Search", SELECT | SEARCH)]
    )


class Menu:
    """Plays a device's netusb list cursor over a menu tree, answering getListInfo and reacting to list commands.

    Parameters
    ----------
    stale_reads
        After each command, this many list info reads still report the previous layer together with the new list,
        like real devices sometimes do.
    """

    def __init__(self, yxc: FakeYxc, stale_reads: int = 0) -> None:
        self.yxc = yxc
        self.root = build_menu()
        self.stack = [self.root]
        self.stale_reads = stale_reads
        self._stale_left = 0
        self._stale_layer = 0
        self.played: list[str] = []
        self.searches: list[str] = []
        self.error_reads = 0
        # Drop the captured per-input lists, which FakeYxc would otherwise prefer.
        for path in [path for path in yxc.responses if path.startswith("netusb/getListInfo_")]:
            del yxc.responses[path]
        yxc.set("netusb/getListInfo", self.list_info)
        yxc.on_write = self.on_write

    @property
    def current(self) -> Node:
        return self.stack[-1]

    def move_cursor(self, *selections: int) -> None:
        """Play another client moving the cursor: back to the root, then into ``selections``."""
        self.stack = [self.root]
        for index in selections:
            child = self.current.items[index].child
            assert child is not None
            self.stack.append(child)

    def list_info(self, query: dict[str, str]) -> dict[str, Any]:
        index = int(query["index"])
        assert index % LIST_BLOCK_SIZE == 0, f"getListInfo index {index} is not a multiple of {LIST_BLOCK_SIZE}"
        if self.error_reads:
            self.error_reads -= 1
            return {"response_code": 100}
        layer = len(self.stack) - 1
        if self._stale_left:
            self._stale_left -= 1
            layer = self._stale_layer
        return {
            "response_code": 0,
            "input": query["input"],
            "menu_layer": layer,
            "menu_name": self.current.name,
            "max_line": len(self.current.items),
            "index": index,
            "list_info": [
                {"text": item.text, "attribute": item.attribute, "thumbnail": ""}
                for item in self.current.items[index : index + int(query["size"])]
            ],
        }

    async def on_write(self, write: Write) -> None:
        previous = len(self.stack) - 1
        if isinstance(write, tuple):
            url, body = write
            assert url.endswith("/netusb/setSearchString")
            entry = self.current.items[body["index"]]
            assert entry.attribute & SEARCH, f"{entry.text} is not capable of search"
            self.searches.append(body["string"])
            self.stack.append(self._results(body["string"]))
        else:
            query = dict(parse_qsl(write.partition("?")[2]))
            if query["type"] == "return":
                if len(self.stack) > 1:
                    self.stack.pop()
            elif query["type"] == "select":
                entry = self.current.items[int(query["index"])]
                if entry.attribute & SEARCH:
                    # Like an RX-A4A: one error response, then the list is back at the root.
                    self.error_reads = 1
                    self.stack = [self.root]
                    return
                assert entry.child is not None, "selected an entry without a list"
                self.stack.append(entry.child)
            else:
                self.played.append(self.current.items[int(query["index"])].text)
                return
        self._stale_left = self.stale_reads
        self._stale_layer = previous

    @staticmethod
    def _results(text: str) -> Node:
        return Node("Search", [Item("Albums", 0)] + [_album(f"{text} album {n}") for n in (1, 2)])


@pytest.fixture
def menu(yxc: FakeYxc) -> Menu:
    return Menu(yxc)


async def browse(device: MusicCastDevice, content_id: str, list_len: int = 8) -> MusicCastMediaContent:
    return await MusicCastMediaContent.browse_media(device, "main", content_id.split(":"), list_len)


async def play(device: MusicCastDevice, content_id: str | None) -> None:
    assert content_id is not None
    await MusicCastMediaContent.play_list_entry(device, "main", content_id)


async def search(device: MusicCastDevice, content_id: str | None, text: str) -> MusicCastMediaContent:
    assert content_id is not None
    return await MusicCastMediaContent.search(device, "main", content_id, text)


def child_id(content: MusicCastMediaContent, index: int) -> str:
    content_id = content.children[index].content_id
    assert content_id is not None
    return content_id


def titles(content: MusicCastMediaContent) -> list[str | None]:
    return [child.title for child in content.children]


# -- content ids ------------------------------------------------------------------------------------------------------


def test_entry_ids_keep_the_older_fields_first() -> None:
    content_id = entry_content_id("tidal", (*BY_DATE, 4))

    # Clients that play "index <index> of the current list" read the first four fields.
    assert content_id == "list:tidal:4:4:1.1.1.4"
    assert parse_path_content_id(content_id) == ("tidal", (*BY_DATE, 4), None, None)


def test_page_ids() -> None:
    assert page_content_id("tidal", BY_DATE, 24) == "list:tidal:3:<>24:1.1.1"
    assert parse_path_content_id("list:tidal:3:<>24:1.1.1") == ("tidal", BY_DATE, 24, None)
    assert parse_path_content_id(page_content_id("tidal", ())) == ("tidal", (), 0, None)


def test_search_text_survives_encoding() -> None:
    query = "AC/DC: Back in Black / ünïcödé"
    content_id = entry_content_id("tidal", ("s2", 1), query)

    assert content_id.count(":") == 5
    assert parse_path_content_id(content_id) == ("tidal", ("s2", 1), None, query)


def test_steps_round_trip() -> None:
    assert decode_steps(encode_steps((1, "s7", 12))) == (1, "s7", 12)
    assert decode_steps("") == ()


@pytest.mark.parametrize(
    "content_id",
    [
        "list:tidal:1:6",
        "input:tidal:0:0:1",
        "list:tidal:1:x:1.y",
        "list:tidal:1:1:sx",
        "list:tidal:2:1:s7",
        "list:tidal:0:0:",
    ],
)
def test_invalid_path_ids_raise(content_id: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - the message differs per case
        parse_path_content_id(content_id)


# -- browsing ---------------------------------------------------------------------------------------------------------


async def test_input_root_from_anywhere(device: MusicCastDevice, menu: Menu) -> None:
    menu.move_cursor(*BY_DATE)

    root = await browse(device, "input:tidal")

    assert (root.title, root.menu_layer, root.content_id) == ("TIDAL", 0, "list:tidal:0:<>0:")
    assert titles(root) == ["New", "My music", "Search"]
    assert child_id(root, 1) == entry_content_id("tidal", MY_MUSIC)
    assert [child.can_search for child in root.children] == [False, False, True]


async def test_entry_opens_the_list_it_was_listed_in(device: MusicCastDevice, menu: Menu) -> None:
    """Browsing the parent level (as the HA frontend does) leaves the cursor on the alphabetical album list.

    A layer/index content id then opened the album at that index of the alphabetical list.
    """
    by_date = await browse(device, page_content_id("tidal", BY_DATE))
    await browse(device, page_content_id("tidal", ALBUMS))
    assert menu.current.name == "Albums"

    album = await browse(device, child_id(by_date, FIRST_ALBUM))

    assert album.title == ALBUMS_BY_DATE[0] != ALBUMS_ALPHABETICAL[0]
    assert titles(album) == [f"{ALBUMS_BY_DATE[0]} - track {n}" for n in (1, 2)]
    assert (album.can_play, album.content_type) == (True, "track")


async def test_cursor_moved_by_another_client(device: MusicCastDevice, menu: Menu) -> None:
    by_date = await browse(device, page_content_id("tidal", BY_DATE))
    menu.move_cursor(0)  # someone opened "New" in the MusicCast app

    album = await browse(device, child_id(by_date, FIRST_ALBUM + 1))

    assert album.title == ALBUMS_BY_DATE[1]


async def test_cursor_moved_to_a_list_with_the_same_name_and_layer(device: MusicCastDevice, menu: Menu) -> None:
    await browse(device, page_content_id("tidal", ALBUMS))
    # Another client opened a different list that is also called "Albums" on layer 2, e.g. an artist's albums.
    menu.move_cursor(*MY_MUSIC)
    menu.stack.append(Node("Albums", [Item("Other album", SELECT | PLAY)]))

    albums = await browse(device, page_content_id("tidal", ALBUMS))

    # The list length differs, so the navigator doesn't trust where it left the cursor and walks from the root.
    assert titles(albums)[FIRST_ALBUM:] == ALBUMS_ALPHABETICAL
    assert (menu.current.name, len(menu.stack)) == ("Albums", 3)
    assert len(menu.current.items) == FIRST_ALBUM + len(ALBUMS_ALPHABETICAL)


async def test_device_reporting_stale_layers(device: MusicCastDevice, yxc: FakeYxc) -> None:
    menu = Menu(yxc, stale_reads=2)

    album = await browse(device, entry_content_id("tidal", (*BY_DATE, FIRST_ALBUM)))

    assert album.title == ALBUMS_BY_DATE[0]
    assert len(menu.stack) == 5


@pytest.mark.usefixtures("menu")
async def test_nested_sort_lists(device: MusicCastDevice) -> None:
    nested = await browse(device, page_content_id("tidal", (*BY_DATE, 0)))

    assert nested.title == "Sort by alphabet"
    assert titles(nested)[FIRST_ALBUM:] == ALBUMS_ALPHABETICAL


async def test_walks_only_from_the_common_part_of_the_paths(device: MusicCastDevice, yxc: FakeYxc, menu: Menu) -> None:
    await browse(device, page_content_id("tidal", BY_DATE))
    yxc.writes.clear()

    await browse(device, page_content_id("tidal", PLAYLISTS))

    # From My music > Albums > Sort by date added up to My music, then into Playlists.
    assert yxc.writes == [RETURN, RETURN, select(0)]
    assert menu.current.name == "Playlists"


@pytest.mark.usefixtures("menu")
async def test_concurrent_browsing_does_not_interleave(device: MusicCastDevice) -> None:
    by_date, playlists = await asyncio.gather(
        browse(device, page_content_id("tidal", BY_DATE)), browse(device, page_content_id("tidal", PLAYLISTS))
    )

    assert titles(by_date)[FIRST_ALBUM:] == ALBUMS_BY_DATE
    assert titles(playlists) == ["Chill", "Focus"]


@pytest.mark.usefixtures("menu")
async def test_pages(device: MusicCastDevice) -> None:
    first = await browse(device, page_content_id("tidal", (0,)), list_len=24)
    second = await browse(device, child_id(first, -1), list_len=24)

    assert len(first.children) == 25
    assert (first.children[-1].title, first.has_next_page, first.has_previous_page) == ("Next Page", True, False)
    assert child_id(first, -1) == "list:tidal:1:<>24:0"
    assert titles(second) == [f"Track {n:02}" for n in range(24, 30)]
    assert (second.has_next_page, second.has_previous_page) == (False, True)
    assert child_id(second, 0) == entry_content_id("tidal", (0, 24))


@pytest.mark.usefixtures("menu")
async def test_pages_that_start_inside_a_block(device: MusicCastDevice) -> None:
    first = await browse(device, page_content_id("tidal", (0,)), list_len=10)
    second = await browse(device, child_id(first, -1), list_len=10)

    # Page two starts at entry 10, but getListInfo is only asked from multiples of 8 (Menu asserts that).
    assert child_id(first, -1) == "list:tidal:1:<>10:0"
    assert titles(second)[:-1] == [f"Track {n:02}" for n in range(10, 20)]
    assert child_id(second, 0) == entry_content_id("tidal", (0, 10))


async def test_empty_list(device: MusicCastDevice, menu: Menu) -> None:
    menu.root.items[0].child = Node("New")

    empty = await browse(device, page_content_id("tidal", (0,)))

    assert (empty.title, empty.children, empty.has_next_page) == ("New", [], False)


@pytest.mark.usefixtures("menu")
async def test_ids_without_a_path_still_browse_by_layer(device: MusicCastDevice) -> None:
    my_music = await browse(device, "list:tidal:1:1")

    assert my_music.title == "My music"
    assert child_id(my_music, 1) == "list:tidal:2:1"


async def test_opening_a_searchable_entry_does_not_select_it(device: MusicCastDevice, yxc: FakeYxc, menu: Menu) -> None:
    root = await browse(device, "input:tidal")
    yxc.writes.clear()

    folder = await browse(device, child_id(root, SEARCH_ENTRY))

    assert (folder.title, folder.can_search, folder.can_browse, folder.children) == ("Search", True, True, [])
    assert (folder.content_id, folder.menu_layer) == (entry_content_id("tidal", (SEARCH_ENTRY,)), 1)
    assert yxc.writes == []
    assert menu.stack == [menu.root]


async def test_selecting_a_searchable_entry_resets_the_device_list(device: MusicCastDevice, menu: Menu) -> None:
    # What the fake device does when a client selects a search entry without search text, as an RX-A4A does.
    await device.select_list_item(SEARCH_ENTRY, "main")

    with pytest.raises(MusicCastResponseException):
        await browse(device, "input:tidal")
    root = await browse(device, "input:tidal")

    assert root.title == "TIDAL"
    assert menu.stack == [menu.root]


# -- failing walks ----------------------------------------------------------------------------------------------------


@pytest.mark.usefixtures("menu")
async def test_failed_walk_is_retried_from_the_root(device: MusicCastDevice, yxc: FakeYxc) -> None:
    on_write = yxc.on_write
    assert on_write is not None
    ignored: list[Write] = []

    async def ignore_first_select(write: Write) -> None:
        if not ignored and isinstance(write, str) and "type=select" in write:
            ignored.append(write)
            return
        await on_write(write)

    yxc.on_write = ignore_first_select

    albums = await browse(device, page_content_id("tidal", ALBUMS))

    assert ignored == [select(1)]
    assert titles(albums)[FIRST_ALBUM:] == ALBUMS_ALPHABETICAL


@pytest.mark.usefixtures("menu")
async def test_walk_gives_up_when_the_device_ignores_commands(device: MusicCastDevice, yxc: FakeYxc) -> None:
    yxc.on_write = None

    async with asyncio.timeout(2):
        with pytest.raises(MusicCastException, match="did not reach menu layer 1"):
            await browse(device, page_content_id("tidal", MY_MUSIC))
    # One walk and its retry.
    assert yxc.writes == [select(1), select(1)]


async def test_cursor_is_forgotten_after_a_failed_walk(device: MusicCastDevice, yxc: FakeYxc, menu: Menu) -> None:
    await browse(device, page_content_id("tidal", ALBUMS))
    on_write, yxc.on_write = yxc.on_write, None
    with pytest.raises(MusicCastException):
        await browse(device, page_content_id("tidal", PLAYLISTS))
    yxc.on_write = on_write
    menu.move_cursor()
    yxc.writes.clear()

    await browse(device, page_content_id("tidal", ALBUMS))

    assert yxc.writes == [select(1), select(1)]


@pytest.mark.usefixtures("menu")
async def test_unreadable_list_is_not_retried(device: MusicCastDevice, yxc: FakeYxc) -> None:
    yxc.fail("netusb/getListInfo")

    with pytest.raises(MusicCastResponseException, match="Could not read the tidal list"):
        await browse(device, page_content_id("tidal", ALBUMS))
    assert (yxc.read_count("netusb/getListInfo"), yxc.writes) == (1, [])


async def test_navigators_share_state_per_device(device: MusicCastDevice) -> None:
    other = MusicCastDevice("192.0.2.2", device.device.client)

    assert ListNavigator(device, "main", "tidal").lock is ListNavigator(device, "zone2", "tidal").lock
    assert ListNavigator(device, "main", "tidal").lock is not ListNavigator(other, "main", "tidal").lock


# -- playing ----------------------------------------------------------------------------------------------------------


async def test_plays_from_the_list_it_was_listed_in(device: MusicCastDevice, menu: Menu) -> None:
    by_date = await browse(device, page_content_id("tidal", BY_DATE))
    await browse(device, page_content_id("tidal", ALBUMS))

    await play(device, child_id(by_date, FIRST_ALBUM))

    assert menu.played == [ALBUMS_BY_DATE[0]]


async def test_plays_a_track_of_an_album(device: MusicCastDevice, yxc: FakeYxc, menu: Menu) -> None:
    await play(device, entry_content_id("tidal", (*BY_DATE, FIRST_ALBUM, 1)))

    assert menu.played == [f"{ALBUMS_BY_DATE[0]} - track 2"]
    assert yxc.writes[-1] == NetUSB.set_list_control("main", "play", 1, "main")


@pytest.mark.parametrize(("index", "played"), [(str(FIRST_ALBUM), ALBUMS_ALPHABETICAL[0]), ("-1", "Sort by alphabet")])
async def test_ids_without_a_path_play_the_current_list(
    device: MusicCastDevice, menu: Menu, index: str, played: str
) -> None:
    menu.move_cursor(*ALBUMS)

    await play(device, f"list:tidal:3:{index}")

    assert menu.played == [played]


@pytest.mark.parametrize(
    "content_id",
    ["presets:1", "list:tidal", page_content_id("tidal", BY_DATE), entry_content_id("tidal", ("s2",), "x")],
)
async def test_only_list_entries_play(device: MusicCastDevice, menu: Menu, content_id: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - the message differs per case
        await play(device, content_id)
    assert menu.played == []


# -- searching --------------------------------------------------------------------------------------------------------


@pytest.mark.usefixtures("menu")
async def test_search_from_the_input(device: MusicCastDevice, yxc: FakeYxc) -> None:
    results = await search(device, "input:tidal", "Coltrane")

    assert yxc.writes[-1] == NetUSB.set_search_string("Coltrane", "main", SEARCH_ENTRY)
    assert (results.title, titles(results)) == ("Search", ["Albums", "Coltrane album 1", "Coltrane album 2"])
    assert results.content_id == "list:tidal:1:<>0:s2:Coltrane"
    assert parse_path_content_id(child_id(results, 1)) == ("tidal", ("s2", 1), None, "Coltrane")


@pytest.mark.usefixtures("menu")
async def test_search_with_a_searchable_entry(device: MusicCastDevice) -> None:
    root = await browse(device, "input:tidal")

    results = await search(device, child_id(root, SEARCH_ENTRY), "Miles")

    assert titles(results)[1:] == ["Miles album 1", "Miles album 2"]


async def test_search_from_a_searchable_entry_folder(device: MusicCastDevice, yxc: FakeYxc, menu: Menu) -> None:
    root = await browse(device, "input:tidal")
    folder = await browse(device, child_id(root, SEARCH_ENTRY))
    yxc.writes.clear()

    results = await search(device, folder.content_id, "Miles")

    assert yxc.writes == [NetUSB.set_search_string("Miles", "main", SEARCH_ENTRY)]
    assert titles(results)[1:] == ["Miles album 1", "Miles album 2"]
    assert menu.searches == ["Miles"]


async def test_search_results_stay_valid_after_another_search(device: MusicCastDevice, menu: Menu) -> None:
    results = await search(device, "input:tidal", "Coltrane")
    await search(device, "input:tidal", "Miles")

    await play(device, child_id(results, 2))
    album = await browse(device, child_id(results, 1))

    assert menu.played == ["Coltrane album 2"]
    assert album.title == "Coltrane album 1"
    # Playing searched again for Coltrane; browsing found the cursor already in those results.
    assert menu.searches == ["Coltrane", "Miles", "Coltrane"]


async def test_same_search_is_not_repeated(device: MusicCastDevice, menu: Menu) -> None:
    results = await search(device, "input:tidal", "Coltrane")

    await browse(device, child_id(results, 1))
    await browse(device, child_id(results, 2))

    assert menu.searches == ["Coltrane"]


@pytest.mark.parametrize(
    ("content_id", "message"),
    [
        (entry_content_id("tidal", MY_MUSIC), "not capable of search"),
        (entry_content_id("tidal", (7,)), "not capable of search"),
        (page_content_id("tidal", MY_MUSIC), "Not a list entry"),
        (entry_content_id("tidal", ("s2", 1), "x"), "within search results"),
    ],
)
async def test_search_needs_a_searchable_entry(
    device: MusicCastDevice, menu: Menu, content_id: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        await search(device, content_id, "Miles")
    assert menu.searches == []


async def test_search_needs_an_input_with_a_search_entry(device: MusicCastDevice, menu: Menu) -> None:
    menu.root.items.pop()

    with pytest.raises(ValueError, match="no search-capable entry"):
        await search(device, "input:tidal", "Miles")
