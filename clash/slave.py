#!/usr/bin/python3

import json
import base64
import asyncio
import aiohttp
import signal
import functools
import traceback
import os

from .terminal import ClashTerminal
from .stdin import ClashStdin


class ClashSlave:

    def __init__(self, log=None, url="http://localhost:8080/clash"):
        self.log = log
        self.url = url
        self.up = True
        self.host = ""
        self.terminal = ClashTerminal(log=log)
        self.stdin = ClashStdin(log=log)
        self.signal_queue = asyncio.Queue()
        loop = asyncio.get_event_loop()
        self.screen_data_available = loop.create_future()
        self.members = []

    async def run(self, session_id):

        def sig_handler(signame, queue):
            queue.put_nowait(signame)

        async def signal_worker():
            while True:
                sig = await self.signal_queue.get()
                if sig == "SIGWINCH":
                    self.terminal.resize(full=True, inner=False)
                else:
                    d = json.dumps({"signal": sig})
                    try:
                        await self.ws.send_str(d)
                    except Exception:
                        self.log(traceback.format_exc())

        asyncio.create_task(signal_worker())

        self.log("slave: starting")
        if not await self.init_slave_connection(session_id):
            print("connection failed")
            return

        self.log("slave: connected")
        loop = asyncio.get_event_loop()
        await self.run_slave_worker(loop)

        self.log("slave: wait for screen info")
        await(self.screen_data_available)

        self.log("terminal: starting")
        for signame in {'SIGINT', 'SIGTERM', 'SIGTSTP', 'SIGWINCH'}:
            loop.add_signal_handler(getattr(signal, signame), functools.partial(sig_handler, signame, self.signal_queue))

        self.terminal.start(self.cols, self.rows, session_id=session_id)
        self.terminal.restore(self.scrinit)
        self.terminal.set_title(f"[ @{self.host}")

        self.log("stdin: starting")
        await self.stdin.start(self.handle_stdin, hotkey_handler=self.hotkey_handler)

        self.log("idle loop")
        while self.up and self.stdin.up:
            await asyncio.sleep(1)

        self.log("stdin: stopping...")
        await self.stdin.stop()
        self.log("slave: stopping...")
        await self.stop_slave_worker()
        self.log("terminal: stopping...")
        self.terminal.stop()
        self.log("clash: terminated")
        print("[exited]")

    async def init_slave_connection(self, session_id):
        url = f"{self.url}/{session_id}"
        self.master_session = aiohttp.ClientSession()
        try:
            self.ws = await self.master_session.ws_connect(url)
        except Exception as exc:
            await self.master_session.close()
            print(exc)
            return False
        return True

    async def run_slave_worker(self, loop):
        async def worker():
            try:
                await self.ws.send_str(json.dumps({"join": os.environ.get('USER')}))
            except Exception:
                self.log(traceback.format_exc())
            while self.up:
                msg = await self.ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        if not await self.handle_slave_msg(msg.data):
                            break
                    except Exception:
                        self.log(traceback.format_exc())
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
            self.up = False
            await self.ws.close()
            self.log("slave: disconnect")
        self.task = asyncio.create_task(worker())

    async def stop_slave_worker(self):
        self.up = False
        self.task.cancel()

    async def handle_slave_msg(self, msg):
        data = json.loads(msg)
        if "init" in data:
            initdata = data.get("init")
            self.host = initdata.get("host")
            self.log(f"host: {self.host}")
            self.scrinit = initdata.get("screen")
            self.rows = self.scrinit['rows']
            self.cols = self.scrinit['cols']
            self.screen_data_available.set_result(True)
        elif "output" in data:
            data = base64.b64decode(data.get("output"))
            self.terminal.input(data)
        elif "welcome" in data:
            member = data.get("welcome")
            self.members.append(member)
            members = ", ".join(self.members)
            self.terminal.set_title(f"[ @{self.host} & {members} ")
        elif "resize" in data:
            self.cols, self.rows = data.get("resize")
            self.terminal.resize(full=False, inner=True, cols=self.cols - 1, rows=self.rows - 1)
        else:
            self.log(f"cmd: unhandled command {data.keys()}")
        return True

    async def handle_stdin(self, data):
        try:
            await self.ws.send_str(json.dumps({"input": base64.b64encode(data).decode()}))
        except Exception:
            self.log(traceback.format_exc())

    async def hotkey_handler(self, key):
        if key == b'd':  # Ctrl-A d
            self.up = False
            await self.stdin.stop()
        else:
            self.log(f"unknown hotkey '{key}'")
