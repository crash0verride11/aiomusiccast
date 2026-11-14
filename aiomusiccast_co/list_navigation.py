"""Walk a device's netusb list menu along a path of selections.

A MusicCast device has a single list cursor. Every client that uses the list API (the MusicCast app, Home Assistant,
scripts) moves the same cursor, and ``getListInfo`` only reports where it is now: ``menu_layer`` and ``menu_name``.
Naming an entry "index N of whatever list is at layer L" breaks as soon as the cursor is on a different list at that
layer, for example after a browser re-fetched a parent level, or when an input offers sort variants of a list
(Albums -> Sort by date added) that put a different list one level up.

:class:`ListNavigator` names a list by the full path of selections from the input's root menu instead. Before the list
is read or an entry is played, it walks the cursor to that exact list: back up to the common part of where it left the
cursor and where it has to go, then down, waiting after every command until the device reports the expected layer.
"""

from __future__ import annotations

import asyncio
import logging
import weakref
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypeAlias

from .exceptions import MusicCastConnectionException, MusicCastException, MusicCastResponseException

if TYPE_CHECKING:
    from .musiccast_device import MusicCastDevice

_LOGGER = logging.getLogger(__name__)

#: Entries returned per ``getListInfo`` request. Its ``index`` has to be a multiple of this.
LIST_BLOCK_SIZE = 8

#: A path step: an ``int`` selects the entry at that index, ``"s<index>"`` runs the search text with the
#: search-capable entry at ``<index>`` (``setSearchString``).
Step: TypeAlias = int | str

SEARCH_STEP_PREFIX = "s"


def search_step(index: int) -> str:
    """Return the step that searches with the entry at ``index``."""
    return f"{SEARCH_STEP_PREFIX}{index}"


def is_search_step(step: Step) -> bool:
    """Return whether ``step`` runs a search."""
    return isinstance(step, str)


def step_index(step: Step) -> int:
    """Return the list index ``step`` selects or searches with."""
    return step if isinstance(step, int) else int(step.removeprefix(SEARCH_STEP_PREFIX))


def encode_steps(steps: tuple[Step, ...]) -> str:
    """Encode path steps for a content id."""
    return ".".join(str(step) for step in steps)


def decode_steps(raw: str) -> tuple[Step, ...]:
    """Decode path steps from a content id.

    Raises
    ------
    ValueError
        If a step is neither an index nor a search step.
    """
    steps: list[Step] = []
    for part in raw.split(".") if raw else ():
        if part.startswith(SEARCH_STEP_PREFIX):
            int(part.removeprefix(SEARCH_STEP_PREFIX))
            steps.append(part)
        else:
            steps.append(int(part))
    return tuple(steps)


@dataclass
class _Cursor:
    """Where a navigator last left the device's list cursor for an input."""

    steps: tuple[Step, ...]
    query: str | None
    layer: int
    name: str | None
    max_line: Any

    def matches(self, data: dict[str, Any]) -> bool:
        """Return whether the device's current list looks like the one the cursor was left on."""
        return (int(data["menu_layer"]), data.get("menu_name"), data.get("max_line")) == (
            self.layer,
            self.name,
            self.max_line,
        )


@dataclass
class _DeviceState:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cursors: dict[str, _Cursor] = field(default_factory=dict)


_STATES: weakref.WeakKeyDictionary[MusicCastDevice, _DeviceState] = weakref.WeakKeyDictionary()


def _state(device: MusicCastDevice) -> _DeviceState:
    state = _STATES.get(device)
    if state is None:
        state = _STATES[device] = _DeviceState()
    return state


class ListNavigator:
    """Moves a device's list cursor along step paths of one input.

    Hold :attr:`lock` around :meth:`goto` and everything that relies on the cursor staying there (reading the list,
    playing an entry), so concurrent requests for the same device don't interleave.

    Parameters
    ----------
    device
        The device whose list cursor is moved.
    zone_id
        Zone used for list control commands.
    source
        Input whose list menu is walked, e.g. ``"tidal"``.
    """

    #: Seconds to wait for the device to reach a layer after a command.
    STEP_TIMEOUT = 4.0
    #: Seconds between list info requests while waiting.
    POLL_INTERVAL = 0.15

    def __init__(self, device: MusicCastDevice, zone_id: str, source: str) -> None:
        self.device = device
        self.zone_id = zone_id
        self.source = source
        self._state = _state(device)

    @property
    def lock(self) -> asyncio.Lock:
        """Lock serialising list cursor use for this device."""
        return self._state.lock

    async def list_info(self, start_index: int = 0) -> dict[str, Any]:
        """Return the list info of the current list from ``start_index``.

        Raises
        ------
        MusicCastResponseException
            If the device sent no list.
        """
        data: dict[str, Any] = await self.device.get_list_info(self.source, start_index)
        if data.get("menu_layer") is None:
            raise MusicCastResponseException(
                f"Could not read the {self.source} list (response_code {data.get('response_code')})."
            )
        return data

    async def read(self, data: dict[str, Any], start_index: int, count: int) -> list[dict[str, Any]]:
        """Read up to ``count`` entries of the current list from ``start_index``.

        Parameters
        ----------
        data
            List info of the current list from index 0, as returned by :meth:`goto`.
        start_index
            First entry to read. It need not be a multiple of :data:`LIST_BLOCK_SIZE`.
        count
            Maximum number of entries.

        Returns
        -------
        list[dict[str, Any]]
            The ``list_info`` entries.
        """
        end = min(start_index + count, int(data.get("max_line", 0)))
        offset = start_index % LIST_BLOCK_SIZE
        block = start_index - offset
        entries: list[dict[str, Any]] = []
        while block < end:
            got = (data if block == 0 else await self.list_info(block)).get("list_info", [])
            entries.extend(got)
            if len(got) < LIST_BLOCK_SIZE:
                break
            block += LIST_BLOCK_SIZE
        return entries[offset : offset + max(end - start_index, 0)]

    async def goto(self, steps: tuple[Step, ...], query: str | None = None) -> dict[str, Any]:
        """Move the cursor into the list at ``steps``.

        The caller must hold :attr:`lock`. If the walk fails, for example because another client moved the cursor
        meanwhile, it is started again from the root once. Connection and response errors are not retried.

        Parameters
        ----------
        steps
            Path from the input's root menu.
        query
            Search text for the search steps in ``steps``.

        Returns
        -------
        dict[str, Any]
            List info of the reached list from index 0.
        """
        try:
            return await self._goto(steps, query)
        except MusicCastConnectionException:
            raise
        except MusicCastException as err:
            _LOGGER.debug("Walking the %s list failed (%s), retrying from the root", self.source, err)
            return await self._goto(steps, query)

    async def _goto(self, target: tuple[Step, ...], query: str | None) -> dict[str, Any]:
        try:
            data = await self.list_info()
            known = self._state.cursors.get(self.source)
            if known is not None and known.matches(data):
                current = list(known.steps)
                current_query = known.query
            else:
                data = await self._to_root()
                current = []
                current_query = None

            common = 0
            while (
                common < min(len(current), len(target))
                and current[common] == target[common]
                and (not is_search_step(current[common]) or current_query == query)
            ):
                common += 1

            while len(current) > common:
                await self.device.return_in_list(self.zone_id)
                current.pop()
                data = await self._wait_for_layer(len(current))

            for step in target[len(current) :]:
                if is_search_step(step):
                    await self.device.search_list_item(query or "", step_index(step))
                else:
                    await self.device.select_list_item(step, self.zone_id)
                current.append(step)
                data = await self._wait_for_layer(len(current))

            reached = tuple(current)
            self._state.cursors[self.source] = _Cursor(
                reached,
                query if any(is_search_step(step) for step in reached) else None,
                int(data["menu_layer"]),
                data.get("menu_name"),
                data.get("max_line"),
            )
            return data
        except Exception:
            self._state.cursors.pop(self.source, None)
            raise

    async def _to_root(self) -> dict[str, Any]:
        data = await self.list_info()
        while (layer := int(data["menu_layer"])) > 0:
            await self.device.return_in_list(self.zone_id)
            data = await self._wait_for_layer(layer - 1)
        return data

    async def _wait_for_layer(self, layer: int) -> dict[str, Any]:
        """Wait until the device reports ``layer`` with the same list twice in a row.

        Devices sometimes still report the previous layer for a moment after a command, so a single matching read
        isn't trusted.

        Raises
        ------
        MusicCastException
            If the device doesn't settle on ``layer`` within :attr:`STEP_TIMEOUT`.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.STEP_TIMEOUT
        previous: tuple[int, Any, Any] | None = None
        while True:
            data = await self.list_info()
            signature = (int(data["menu_layer"]), data.get("menu_name"), data.get("max_line"))
            if signature[0] == layer and signature == previous:
                return data
            previous = signature if signature[0] == layer else None
            if loop.time() > deadline:
                raise MusicCastException(
                    f"The {self.source} list did not reach menu layer {layer} (at {signature[0]} {signature[1]!r})."
                )
            await asyncio.sleep(self.POLL_INTERVAL)
