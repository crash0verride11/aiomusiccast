"""Tests for the HTTP/UDP transport in pyamaha.AsyncDevice, against a local aiohttp test server."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from aiomusiccast_co.exceptions import MusicCastConfigurationException, MusicCastConnectionException
from aiomusiccast_co.pyamaha import AsyncDevice, MusicCastUdpProtocol, NetUSB, System, Zone

DESCRIPTION = """<?xml version="1.0"?>
<root><device><serviceList>
<service><serviceType>urn:schemas-upnp-org:service:RenderingControl:1</serviceType>
<serviceId>urn:upnp-org:serviceId:RenderingControl</serviceId><controlURL>/RenderingControl/ctrl</controlURL></service>
<service><serviceType>urn:schemas-upnp-org:service:AVTransport:1</serviceType>
<serviceId>urn:upnp-org:serviceId:AVTransport</serviceId><controlURL>/AVTransport/ctrl</controlURL></service>
</serviceList></device></root>"""

DESCRIPTION_WITHOUT_AVT = DESCRIPTION.replace("AVTransport", "ConnectionManager")


class FakeReceiver:
    """A local HTTP server answering YXC and UPnP requests and recording what it received."""

    def __init__(self) -> None:
        self.requests: list[web.Request] = []
        self.bodies: list[bytes] = []
        self.responses: dict[str, web.Response] = {}
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self.handle)
        self.server = TestServer(app, host="127.0.0.1")

    @property
    def host(self) -> str:
        return f"127.0.0.1:{self.server.port}"

    def respond(self, path: str, body: bytes | str, content_type: str = "application/json") -> None:
        data = body.encode() if isinstance(body, str) else body
        self.responses[path] = web.Response(body=data, content_type=content_type, charset="utf-8")

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(request)
        self.bodies.append(await request.read())
        return self.responses.get(request.path, web.json_response({"response_code": 0}))


@pytest.fixture
async def receiver() -> AsyncIterator[FakeReceiver]:
    fake = FakeReceiver()
    await fake.server.start_server()
    yield fake
    await fake.server.close()


@pytest.fixture
async def session() -> AsyncIterator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as client:
        yield client


EventHandler = Callable[[dict[str, Any] | None], Awaitable[None]]


def make_device(
    session: aiohttp.ClientSession,
    host: str,
    handle_event: EventHandler | None = None,
    upnp_description: str | None = None,
) -> AsyncDevice:
    return AsyncDevice(session, host, asyncio.get_running_loop(), handle_event, upnp_description)


# -- HTTP -----------------------------------------------------------------------------------------------------------


async def test_request_json_get(receiver: FakeReceiver, session: aiohttp.ClientSession) -> None:
    receiver.respond("/YamahaExtendedControl/v1/main/getStatus", '{"response_code": 0, "power": "on"}')
    device = make_device(session, receiver.host)

    assert await device.request_json(Zone.get_status("main")) == {"response_code": 0, "power": "on"}
    assert receiver.requests[0].method == "GET"
    assert "X-AppPort" not in receiver.requests[0].headers


async def test_request_json_post(receiver: FakeReceiver, session: aiohttp.ClientSession) -> None:
    device = make_device(session, receiver.host)

    await device.request_json(Zone.set_scene_info("main", 2, "Party"))

    assert receiver.requests[0].method == "POST"
    assert receiver.requests[0].path == "/YamahaExtendedControl/v1/main/setSceneInfo"
    assert json.loads(receiver.bodies[0]) == {"num": 2, "text": "Party"}


async def test_request_get_and_post(receiver: FakeReceiver, session: aiohttp.ClientSession) -> None:
    device = make_device(session, receiver.host)

    response = await device.request(Zone.set_power("main", "on"))
    await device.request(Zone.set_scene_info("main", 1, "Movie"))

    assert response.status == 200
    assert [(r.method, r.path_qs) for r in receiver.requests] == [
        ("GET", "/YamahaExtendedControl/v1/main/setPower?power=on"),
        ("POST", "/YamahaExtendedControl/v1/main/setSceneInfo"),
    ]


async def test_response_with_invalid_utf8_is_decoded_leniently(
    receiver: FakeReceiver, session: aiohttp.ClientSession, caplog: pytest.LogCaptureFixture
) -> None:
    receiver.respond("/YamahaExtendedControl/v1/netusb/getPlayInfo", b'{"response_code": 0, "track": "Caf\xe9"}')
    device = make_device(session, receiver.host)

    with caplog.at_level(logging.WARNING):
        result = await device.request_json(NetUSB.get_play_info())

    assert result == {"response_code": 0, "track": "Caf"}
    assert "Failed to decode response" in caplog.text


async def test_response_with_invalid_json_raises(
    receiver: FakeReceiver, session: aiohttp.ClientSession, caplog: pytest.LogCaptureFixture
) -> None:
    receiver.respond("/YamahaExtendedControl/v1/main/getStatus", "<html>busy</html>", "text/html")
    device = make_device(session, receiver.host)

    with pytest.raises(ValueError, match="Expecting value"):
        await device.request_json(Zone.get_status("main"))
    assert "Failed to generate JSON from <html>busy</html>" in caplog.text


@pytest.mark.parametrize("method", ["request", "request_json"])
async def test_unreachable_device_raises_connection_exception(session: aiohttp.ClientSession, method: str) -> None:
    # Nothing listens on port 1 of the loopback address.
    device = make_device(session, "127.0.0.1:1")

    with pytest.raises(MusicCastConnectionException):
        await getattr(device, method)(Zone.get_status("main"))


@pytest.mark.parametrize("method", ["request", "request_json"])
async def test_timeout_raises_connection_exception(method: str) -> None:
    client = MagicMock()
    client.get = AsyncMock(side_effect=TimeoutError)
    device = AsyncDevice(client, "192.0.2.1", asyncio.get_running_loop())

    with pytest.raises(MusicCastConnectionException):
        await getattr(device, method)(Zone.get_status("main"))


# -- UDP events -----------------------------------------------------------------------------------------------------


async def send_udp(port: int, payload: bytes) -> None:
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        asyncio.DatagramProtocol, remote_addr=("127.0.0.1", port)
    )
    transport.sendto(payload)
    transport.close()


async def test_enable_polling_registers_for_udp_events(receiver: FakeReceiver, session: aiohttp.ClientSession) -> None:
    events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    device = make_device(session, receiver.host, events.put)

    await device.enable_polling()
    try:
        headers = receiver.requests[0].headers
        assert receiver.requests[0].path == "/YamahaExtendedControl/v1/system/getDeviceInfo"
        assert headers["X-AppName"] == "MusicCast/1.0"
        port = int(headers["X-AppPort"])
        assert device.transport is not None

        await send_udp(port, b'{"main": {"volume": 50}, "device_id": "00A0DE000000"}')
        assert await asyncio.wait_for(events.get(), 1) == {"main": {"volume": 50}, "device_id": "00A0DE000000"}

        # Later requests carry the headers too, so the device keeps sending events.
        await device.request(System.get_func_status())
        assert receiver.requests[-1].headers["X-AppPort"] == str(port)
    finally:
        device.disable_polling()

    assert device.transport is None
    await device.request(System.get_func_status())
    assert "X-AppPort" not in receiver.requests[-1].headers


@pytest.mark.parametrize(
    ("payload", "log"),
    [(b"not json", "Received invalid message: not json"), (b"\xff\xfe", "Received non UTF-8 compliant message")],
)
async def test_invalid_udp_message_is_passed_as_none(
    payload: bytes, log: str, caplog: pytest.LogCaptureFixture
) -> None:
    events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    protocol = MusicCastUdpProtocol(events.put)

    protocol.datagram_received(payload, ("192.0.2.1", 41100))

    assert await asyncio.wait_for(events.get(), 1) is None
    assert log in caplog.text


async def test_enable_polling_without_socket_disables_again(caplog: pytest.LogCaptureFixture) -> None:
    transport = MagicMock()
    transport.get_extra_info.return_value = None
    loop = MagicMock()
    loop.create_datagram_endpoint = AsyncMock(return_value=(transport, None))
    client = MagicMock()
    client.get = AsyncMock()
    device = AsyncDevice(client, "192.0.2.1", loop, AsyncMock())

    await device.enable_polling()

    assert "Failed to open UDP connection" in caplog.text
    transport.close.assert_called_once_with()
    assert device.transport is None
    client.get.assert_not_awaited()


# -- DLNA -----------------------------------------------------------------------------------------------------------


async def test_dlna_request_needs_upnp_description(session: aiohttp.ClientSession) -> None:
    device = make_device(session, "192.0.2.1")

    with pytest.raises(MusicCastConfigurationException, match="UPNP description"):
        await device.dlna_avt_request("Stop", {"InstanceID": 0})


async def test_dlna_request(receiver: FakeReceiver, session: aiohttp.ClientSession) -> None:
    receiver.respond("/desc.xml", DESCRIPTION, "text/xml")
    # The UPnP port comes from the description URL; YXC requests use the host as given.
    device = make_device(session, "127.0.0.1", upnp_description=f"http://{receiver.host}/desc.xml")

    await device.dlna_avt_request("Stop", {"InstanceID": 0})
    await device.dlna_avt_request("Play", {"InstanceID": 0, "Speed": 1})

    assert [r.path for r in receiver.requests] == ["/desc.xml", "/AVTransport/ctrl", "/AVTransport/ctrl"]
    play = receiver.requests[2]
    assert play.headers["SOAPACTION"] == '"urn:schemas-upnp-org:service:AVTransport:1#Play"'
    body = receiver.bodies[2].decode()
    assert '<u:Play xmlns:u="urn:schemas-upnp-org:service:AVTransport:1">' in body
    assert "<InstanceID>0</InstanceID><Speed>1</Speed>" in body


async def test_dlna_request_without_avtransport_raises(receiver: FakeReceiver, session: aiohttp.ClientSession) -> None:
    receiver.respond("/desc.xml", DESCRIPTION_WITHOUT_AVT, "text/xml")
    device = make_device(session, "127.0.0.1", upnp_description=f"http://{receiver.host}/desc.xml")

    with pytest.raises(MusicCastConfigurationException, match="AVTransport"):
        await device.dlna_avt_request("Stop", {"InstanceID": 0})
