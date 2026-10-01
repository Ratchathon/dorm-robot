import asyncio
import json

import pytest
import websockets

from bridge import RobotBridge


class FakeSerial:
    def __init__(self):
        self.sent = []

    def send_json(self, payload):
        self.sent.append(payload)


@pytest.fixture
async def server():
    serial = FakeSerial()
    bridge = RobotBridge(serial, command_timeout=0.3, watchdog_period=0.05)
    async with websockets.serve(bridge.handle, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}", serial, bridge


async def recv_json(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 1))


async def test_malformed_messages_do_not_kill_the_connection(server):
    url, serial, _ = server
    async with websockets.connect(url) as ws:
        hello = await recv_json(ws)
        assert hello["type"] == "hello" and hello["controller"] is True
        for bad in ["not json", "[1,2]", "null", json.dumps({"tilt": "abc"})]:
            await ws.send(bad)
        await ws.send(json.dumps({"move": {"forward": True}, "tilt": 120, "blower": True}))
        acks = [await recv_json(ws) for _ in range(2)]  # {"tilt":"abc"} is a dict -> acked too
        assert acks[-1] == {"type": "ack", "cmd": {
            "move": {"forward": True, "backward": False, "left": False, "right": False},
            "tilt": 120, "blower": True}}
    await asyncio.sleep(0.05)
    assert serial.sent[-1]["move"]["forward"] is False  # stop on disconnect


async def test_second_browser_is_told_busy(server):
    url, _, _ = server
    async with websockets.connect(url) as first:
        await recv_json(first)
        async with websockets.connect(url) as second:
            msg = await recv_json(second)
            assert msg == {"type": "busy"}
            with pytest.raises(websockets.ConnectionClosed) as exc:
                await asyncio.wait_for(second.recv(), 1)
            assert exc.value.rcvd.code == 4001


async def test_lock_is_released_after_disconnect(server):
    url, _, _ = server
    async with websockets.connect(url) as ws:
        await recv_json(ws)
    await asyncio.sleep(0.05)
    async with websockets.connect(url) as ws:
        assert (await recv_json(ws))["controller"] is True


async def test_silence_stops_wheels_but_keeps_tilt(server):
    url, serial, _ = server
    async with websockets.connect(url) as ws:
        await recv_json(ws)
        await ws.send(json.dumps({"move": {"forward": True}, "tilt": 35, "blower": True}))
        await recv_json(ws)
        await asyncio.sleep(0.5)  # longer than command_timeout
        stop = serial.sent[-1]
        assert stop["move"]["forward"] is False
        assert stop["blower"] is False
        assert stop["tilt"] == 35


async def test_disconnect_stop_keeps_tilt(server):
    url, serial, _ = server
    async with websockets.connect(url) as ws:
        await recv_json(ws)
        await ws.send(json.dumps({"tilt": 140}))
        await recv_json(ws)
    await asyncio.sleep(0.05)
    assert serial.sent[-1]["tilt"] == 140


async def test_new_session_starts_from_last_known_tilt(server):
    url, _, bridge = server
    async with websockets.connect(url) as ws:
        await recv_json(ws)
        await ws.send(json.dumps({"tilt": 44}))
        await recv_json(ws)
    await asyncio.sleep(0.05)
    async with websockets.connect(url) as ws:
        hello = await recv_json(ws)
        assert hello["tilt"] == 44
