"""WebSocket session handling between the cockpit page and the ESP32.

Safety rules:
  * one controlling browser at a time (others get {"type": "busy"} and close code 4001)
  * malformed messages are ignored, never crash the session
  * silence longer than command_timeout -> stop wheels + blower, keep camera tilt
  * disconnect -> same stop
Each accepted command is echoed back as {"type": "ack", "cmd": ...} so the page
shows what the robot actually received (motion status + latency).
"""

import asyncio
import itertools
import json
import time

from control import DEFAULT_TILT, ControllerLock, sanitize_command, stop_command

BUSY_CLOSE_CODE = 4001


class RobotBridge:
    def __init__(self, serial, command_timeout: float = 0.5, watchdog_period: float = 0.1):
        self.serial = serial
        self.command_timeout = command_timeout
        self.watchdog_period = watchdog_period
        self.lock = ControllerLock()
        self.last_tilt = DEFAULT_TILT
        self._ids = itertools.count(1)

    def _stop(self):
        self.serial.send_json(stop_command(self.last_tilt))

    async def handle(self, websocket):
        session = next(self._ids)
        if not self.lock.acquire(session):
            await websocket.send(json.dumps({"type": "busy"}))
            await websocket.close(BUSY_CLOSE_CODE, "another controller is active")
            return

        last_seen = time.monotonic()
        stopped_for_silence = False

        async def watchdog():
            nonlocal stopped_for_silence
            while True:
                await asyncio.sleep(self.watchdog_period)
                if time.monotonic() - last_seen > self.command_timeout and not stopped_for_silence:
                    self._stop()
                    stopped_for_silence = True

        watchdog_task = asyncio.create_task(watchdog())
        try:
            await websocket.send(json.dumps({"type": "hello", "controller": True, "tilt": self.last_tilt}))
            async for message in websocket:
                try:
                    raw = json.loads(message)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(raw, dict):
                    continue
                command = sanitize_command(raw, last_tilt=self.last_tilt)
                self.last_tilt = command["tilt"]
                last_seen = time.monotonic()
                stopped_for_silence = False
                self.serial.send_json(command)
                await websocket.send(json.dumps({"type": "ack", "cmd": command}))
        except Exception:  # connection dropped mid-send etc. -> fall through to stop
            pass
        finally:
            watchdog_task.cancel()
            self._stop()
            self.lock.release(session)
