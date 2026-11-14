from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from .exceptions import MusicCastException, MusicCastResponseException
from .list_navigation import ListNavigator, Step, decode_steps, encode_steps, is_search_step, search_step, step_index
from .musiccast_device import MusicCastDevice

Logger = logging.getLogger(__name__)

# Upper bound for return commands when going back up a list; YXC menus are far shallower than this.
MAX_LIST_RETURNS = 20

# List entry attribute bits (getListInfo).
ATTRIBUTE_SELECTABLE = 0b10
ATTRIBUTE_PLAYABLE = 0b100
ATTRIBUTE_SEARCHABLE = 0b1000

# Hosts that serve the artwork devices report over http:// over HTTPS as well. Browsers block http:// images as mixed
# content when the frontend is served over HTTPS; devices report e.g. http://resources.tidal.com:80/images/...
HTTPS_THUMBNAIL_HOSTS = ("resources.tidal.com",)


def secure_thumbnail(url: str | None) -> str | None:
    """Return the HTTPS URL of artwork from :data:`HTTPS_THUMBNAIL_HOSTS`, and any other URL unchanged."""
    if not url or not url.startswith("http://"):
        return url
    parts = urlsplit(url)
    if parts.hostname not in HTTPS_THUMBNAIL_HOSTS or parts.port not in (None, 80) or parts.username is not None:
        return url
    return urlunsplit(("https", parts.hostname, parts.path, parts.query, parts.fragment))


def _attribute(info: dict[str, Any]) -> int:
    return int(info.get("attribute") or 0)


# Content ids of list entries carry the full path from the input's root menu after the fields older ids have:
#
#   entry: list:<source>:<layer>:<index>:<steps>[:<search text>]
#   page:  list:<source>:<layer>:<><start>:<steps>[:<search text>]
#
# <steps> is "." separated (an index, or "s<index>" for a search) and the search text is URL quoted, so it holds no
# ":". <layer> and <index> keep their old meaning, so clients that play "index <index> of the current list" keep
# working. The format matches upstream aiomusiccast's (vigonotion/aiomusiccast#57).


def _path_suffix(steps: tuple[Step, ...], query: str | None) -> str:
    suffix = f":{encode_steps(steps)}"
    if query is not None and any(is_search_step(step) for step in steps):
        suffix += f":{quote(query, safe='')}"
    return suffix


def entry_content_id(source: str, steps: tuple[Step, ...], query: str | None = None) -> str:
    """Return the content id of the list entry reached by ``steps``."""
    return f"list:{source}:{len(steps)}:{step_index(steps[-1])}{_path_suffix(steps, query)}"


def page_content_id(source: str, steps: tuple[Step, ...], start_index: int = 0, query: str | None = None) -> str:
    """Return the content id of the page from ``start_index`` of the list at ``steps``."""
    return f"list:{source}:{len(steps)}:<>{start_index}{_path_suffix(steps, query)}"


def parse_path_content_id(content_id: str | Sequence[str]) -> tuple[str, tuple[Step, ...], int | None, str | None]:
    """Parse a path-based list content id.

    Parameters
    ----------
    content_id
        The content id, or its ``:`` separated parts.

    Returns
    -------
    tuple[str, tuple[Step, ...], int | None, str | None]
        Source, steps, page start (``None`` for an entry) and search text.

    Raises
    ------
    ValueError
        If ``content_id`` is not a valid path-based list content id.
    """
    parts = content_id.split(":") if isinstance(content_id, str) else list(content_id)
    joined = ":".join(parts)
    if len(parts) not in (5, 6) or parts[0] != "list":
        raise ValueError(f"Not a path-based list content id: {joined}")
    steps = decode_steps(parts[4])
    query = unquote(parts[5]) if len(parts) == 6 else None
    if any(is_search_step(step) for step in steps) and query is None:
        raise ValueError(f"Search text missing in content id: {joined}")
    start = int(parts[3][2:]) if parts[3].startswith("<>") else None
    if start is None and not steps:
        raise ValueError(f"Entry content id without a path: {joined}")
    return parts[1], steps, start, query


@dataclass(slots=True)
class MusicCastMediaContent:
    """Container for browsable MusicCast media entries."""

    BROWSABLE_INPUTS: ClassVar[tuple[str, ...]] = (
        "usb",
        "server",
        "net_radio",
        "rhapsody",
        "napster",
        "pandora",
        "siriusxm",
        "juke",
        "radiko",
        "qobuz",
        "tidal",
        "deezer",
        "amazon_music",
    )

    musiccast: MusicCastDevice | None = None
    zone_id: str | None = None
    can_browse: bool = False
    can_play: bool = False
    can_search: bool = False
    title: str | None = None
    content_id: str | None = None
    menu_layer: int = -1
    thumbnail: str | None = None
    content_type: str | None = None
    list_len: int = 8
    start_index: int = 0
    has_next_page: bool = False
    has_previous_page: bool = False
    children: list[MusicCastMediaContent] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.musiccast and not self.zone_id:
            msg = "Zone id must be provided when binding a musiccast device."
            raise ValueError(msg)

    @property
    def _zone_id(self) -> str:
        if self.zone_id is None:
            msg = "Zone id is required for this operation."
            raise ValueError(msg)
        return self.zone_id

    @property
    def _device(self) -> MusicCastDevice:
        if self.musiccast is None:
            msg = "MusicCast device must be provided for this operation."
            raise ValueError(msg)
        return self.musiccast

    @classmethod
    def from_info(
        cls,
        source: str,
        info: dict,
        menu_layer: int,
        index: int,
        parent_steps: tuple[Step, ...] | None = None,
        query: str | None = None,
    ) -> MusicCastMediaContent:
        """Return the entry at ``index`` of a list, with a path-based content id if ``parent_steps`` is given."""
        attribute = _attribute(info)
        if parent_steps is None:
            content_id = f"list:{source}:{menu_layer}:{index}"
        else:
            content_id = entry_content_id(source, (*parent_steps, index), query)
        return cls(
            can_browse=bool(attribute & ATTRIBUTE_SELECTABLE),
            can_play=bool(attribute & ATTRIBUTE_PLAYABLE),
            can_search=bool(attribute & ATTRIBUTE_SEARCHABLE),
            title=info.get("text"),
            content_id=content_id,
            thumbnail=secure_thumbnail(info.get("thumbnail")),
            menu_layer=menu_layer,
            content_type="directory" if attribute & ATTRIBUTE_SELECTABLE else "track",
        )

    @classmethod
    def from_preset(cls, preset_num: str | int, preset: Sequence[str]) -> MusicCastMediaContent:
        return cls(
            can_play=True, title=preset[0] + " - " + preset[1], content_id=f"presets:{preset_num}", content_type="track"
        )

    @classmethod
    async def browse_media(
        cls, musiccast: MusicCastDevice, zone_id: str, media_content_path: Sequence[str], list_len: int = 8
    ) -> MusicCastMediaContent:
        if media_content_path[0] == "input":
            return await cls._browse_path(musiccast, zone_id, media_content_path[1], (), 0, None, list_len)

        if media_content_path[0] == "list" and len(media_content_path) >= 5:
            source, steps, start, query = parse_path_content_id(media_content_path)
            return await cls._browse_path(
                musiccast, zone_id, source, steps, start or 0, query, list_len, entry=start is None
            )

        # Content ids without a path (list:<source>:<layer>:<index>), as created by earlier versions: navigate by layer
        # number.
        self = cls(
            musiccast=musiccast,
            zone_id=zone_id,
            can_browse=True,
            content_id=":".join(media_content_path),
            list_len=list_len,
        )
        if media_content_path[-1].startswith("<>"):
            # just a page change
            self.start_index = int(media_content_path[-1][2:])
            self.content_id = ":".join(media_content_path[:-1])

        device = self._device

        if media_content_path[0] == "list":
            source = media_content_path[1]
            self.menu_layer = int(media_content_path[2])

            list_info = await self._list_info(source, 0)
            if self.menu_layer < list_info["menu_layer"]:
                await self.return_in_list_info(source, self.menu_layer)

            elif media_content_path[3].isdigit():
                # an item was selected
                await device.select_list_item(media_content_path[3], self._zone_id)

            elif self.menu_layer != list_info.get("menu_layer"):
                Logger.warning(
                    "Unexpected menu layer. Expected %s, found %s",
                    self.menu_layer,
                    list_info.get("menu_layer"),
                )

            await self.load_list(source)

        elif media_content_path[0] == "presets":
            for i, preset in device.data.netusb_preset_list.items():
                self.children.append(self.from_preset(i, preset))

            self.title = "Presets"
            self.can_browse = True
            self.content_type = "directory"
        else:
            raise ValueError(f"{media_content_path[0]} is an unknown browse method.")

        return self

    @classmethod
    async def _browse_path(
        cls,
        musiccast: MusicCastDevice,
        zone_id: str,
        source: str,
        steps: tuple[Step, ...],
        start_index: int,
        query: str | None,
        list_len: int,
        entry: bool = False,
    ) -> MusicCastMediaContent:
        """Return a page of the list at ``steps``.

        With ``entry``, ``steps`` names a list entry being opened. A search-capable entry is not selected: devices
        answer that with an error and reset the list to the root (seen on an RX-A4A). It is returned as an empty
        folder with ``can_search`` instead, to be searched with :meth:`search`.
        """
        self = cls(musiccast=musiccast, zone_id=zone_id, can_browse=True, list_len=list_len, start_index=start_index)
        navigator = ListNavigator(musiccast, zone_id, source)
        async with navigator.lock:
            if entry and isinstance(last := steps[-1], int):
                parent = await navigator.goto(steps[:-1], query)
                info = next(iter(await navigator.read(parent, last, 1)), {})
                if _attribute(info) & ATTRIBUTE_SEARCHABLE:
                    self.can_search = True
                    self.title = info.get("text")
                    self.menu_layer = len(steps)
                    self.content_id = entry_content_id(source, steps, query)
                    self.content_type = "directory"
                    return self
            data = await navigator.goto(steps, query)
            entries = await navigator.read(data, start_index, list_len)

        self.title = data.get("menu_name")
        self.menu_layer = int(data["menu_layer"])
        self.content_id = page_content_id(source, steps, start_index, query)
        self.has_previous_page = start_index > 0
        self.children = [
            cls.from_info(source, info, self.menu_layer + 1, start_index + i, steps, query)
            for i, info in enumerate(entries)
        ]
        self.can_play = not any(child.can_browse for child in self.children)
        self.content_type = "directory" if any(child.can_browse for child in self.children) else "track"

        next_index = start_index + len(entries)
        if entries and next_index < int(data.get("max_line", 0)):
            self.has_next_page = True
            self.children.append(
                MusicCastMediaContent(
                    can_browse=True,
                    content_type="directory",
                    menu_layer=self.menu_layer,
                    content_id=page_content_id(source, steps, next_index, query),
                    title="Next Page",
                )
            )
        return self

    @classmethod
    async def play_list_entry(cls, musiccast: MusicCastDevice, zone_id: str, media_content_id: str) -> None:
        """Play the list entry a ``list:`` content id names.

        A path-based content id first moves the list cursor to the list the entry is in, so the right entry plays even
        if the cursor moved since the list was browsed. A content id without a path plays its index on the current
        list, as before.

        Parameters
        ----------
        musiccast
            The device.
        zone_id
            Zone to play on.
        media_content_id
            Content id of a playable list entry.

        Raises
        ------
        ValueError
            If the content id is not a list entry.
        """
        parts = media_content_id.split(":")
        if parts[0] != "list" or len(parts) < 4:
            raise ValueError(f"Not a list content id: {media_content_id}")

        if len(parts) == 4:
            await musiccast.play_list_media("0" if parts[3] == "-1" else parts[3], zone_id)
            return

        source, steps, start, query = parse_path_content_id(parts)
        last = steps[-1] if steps else None
        if start is not None or not isinstance(last, int):
            raise ValueError(f"Not a playable list entry: {media_content_id}")
        navigator = ListNavigator(musiccast, zone_id, source)
        async with navigator.lock:
            await navigator.goto(steps[:-1], query)
            await musiccast.play_list_media(last, zone_id)

    @classmethod
    async def search(
        cls,
        musiccast: MusicCastDevice,
        zone_id: str,
        media_content_id: str,
        search_string: str,
        list_len: int = 8,
    ) -> MusicCastMediaContent:
        """Search with a search-capable list entry and return the results.

        Parameters
        ----------
        musiccast
            The device.
        zone_id
            Zone used for list control.
        media_content_id
            Content id of a list entry with ``can_search``, or ``input:<source>`` to use the first search-capable
            entry of the input's root menu (e.g. TIDAL's "Search").
        search_string
            Text to search for.
        list_len
            Number of results per page.

        Returns
        -------
        MusicCastMediaContent
            The first page of results. Their content ids hold the search text, so they can be browsed and played
            later, even after other searches.

        Raises
        ------
        ValueError
            If there is no search-capable entry to search with.
        """
        parts = media_content_id.split(":")
        if parts[0] == "input" and len(parts) == 2:
            source = parts[1]
            navigator = ListNavigator(musiccast, zone_id, source)
            async with navigator.lock:
                data = await navigator.goto(())
                entries = await navigator.read(data, 0, int(data.get("max_line", 0)))
            index = next(
                (i for i, info in enumerate(entries) if _attribute(info) & ATTRIBUTE_SEARCHABLE),
                None,
            )
            if index is None:
                raise ValueError(f"{source} has no search-capable entry in its root menu")
            steps: tuple[Step, ...] = (search_step(index),)
        else:
            source, entry_steps, start, _query = parse_path_content_id(parts)
            last = entry_steps[-1] if entry_steps else None
            if start is not None or not isinstance(last, int):
                raise ValueError(f"Not a list entry: {media_content_id}")
            if any(is_search_step(step) for step in entry_steps[:-1]):
                raise ValueError(f"Searching within search results is not supported: {media_content_id}")
            navigator = ListNavigator(musiccast, zone_id, source)
            async with navigator.lock:
                data = await navigator.goto(entry_steps[:-1])
                entry = next(iter(await navigator.read(data, last, 1)), {})
            if not _attribute(entry) & ATTRIBUTE_SEARCHABLE:
                raise ValueError(f"List entry is not capable of search: {media_content_id}")
            steps = (*entry_steps[:-1], search_step(last))

        return await cls._browse_path(musiccast, zone_id, source, steps, 0, search_string, list_len)

    @classmethod
    def categories(cls, musiccast: MusicCastDevice, zone_id: str) -> MusicCastMediaContent:
        self = cls(
            musiccast=musiccast,
            zone_id=zone_id,
            title="Library",
            content_id="",
            content_type="categories",
            can_browse=True,
        )
        device = self._device
        sources = sorted(set(cls.BROWSABLE_INPUTS).intersection(device.data.zones[self._zone_id].input_list))
        self.children.append(
            MusicCastMediaContent(title="Presets", content_id="presets", can_browse=True, content_type="directory")
        )
        for source in sources:
            self.children.append(
                MusicCastMediaContent(
                    title=device.data.input_names.get(source, source),
                    content_id=f"input:{source}",
                    can_browse=True,
                    content_type="directory",
                )
            )

        return self

    async def load_list(self, source: str) -> None:
        # load list info
        list_info = await self._list_info(source, self.start_index)
        self.title = list_info.get("menu_name")
        self.menu_layer = int(list_info["menu_layer"])
        self.content_id = f"list:{source}:{self.menu_layer}:<>{self.start_index}"
        # get list items
        entries = list_info.get("list_info", [])
        for i in range(self.start_index + 8, self.start_index + self.list_len, 8):
            if i >= list_info.get("max_line", 8):
                break
            list_info_tmp = await self._list_info(source, i)
            entries += list_info_tmp.get("list_info", [])

        if int(self.start_index) != 0:
            self.has_previous_page = True

        for i, info in enumerate(list_info.get("list_info", [])):
            self.children.append(self.from_info(source, info, self.menu_layer + 1, self.start_index + i))
        self.can_play = not any(child.can_browse for child in self.children)
        self.can_browse = True
        self.content_type = "directory" if any(child.can_browse for child in self.children) else "track"
        if (list_info.get("max_line", 8) - self.start_index) > self.list_len:
            self.has_next_page = True
            self.children.append(
                MusicCastMediaContent(
                    can_browse=True,
                    content_type="directory",
                    menu_layer=self.menu_layer,
                    content_id=":".join(self.content_id.split(":")[:-1]) + f":<>{self.start_index + self.list_len}",
                    title="Next Page",
                )
            )

    async def return_in_list_info(self, source: str, until_layer: int = 0) -> None:
        """Send return commands until the device's list is at ``until_layer`` or above it."""
        self.menu_layer = (await self._list_info(source, 0))["menu_layer"]
        returns = 0
        while self.menu_layer > until_layer:
            if returns == MAX_LIST_RETURNS:
                raise MusicCastException(
                    f"The {source} list is still at menu layer {self.menu_layer} after {returns} return commands."
                )
            await self._device.return_in_list(self._zone_id)
            returns += 1
            self.menu_layer = (await self._list_info(source, 0))["menu_layer"]

    async def _list_info(self, source: str, index: int) -> dict[str, Any]:
        """Return the device's list info, raising if it could not be read."""
        list_info: dict[str, Any] = await self._device.get_list_info(source, index)
        if list_info.get("menu_layer") is None:
            raise MusicCastResponseException(
                f"Could not read the {source} list (response_code {list_info.get('response_code')})."
            )
        return list_info
