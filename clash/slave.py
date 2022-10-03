#!/usr/bin/python3

import json
import base64
import asyncio
import aiohttp
import signal
import functools
import traceback

from .terminal import ClashTerminal
from .stdin import ClashStdin


class ClashSlave:

    def __init__(self, log=None, url="http://localhost:8080/clash"):
        self.log = log
        self.url = url
        self.up = True
        self.terminal = ClashTerminal(log=log)
        self.stdin = ClashStdin(log=log)
        self.signal_queue = asyncio.Queue()
        loop = asyncio.get_event_loop()
        self.screen_data_available = loop.create_future()

    async def run(self, session_id):

        def sig_handler(signame, queue):
            queue.put_nowait(signame)

        async def signal_worker():
            while True:
                sig = await self.signal_queue.get()
                d = json.dumps({"signal": sig})
                await self.ws.send_str(d)

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
        for signame in {'SIGINT', 'SIGTERM', 'SIGTSTP', 'SIGCONT'}:
            loop.add_signal_handler(getattr(signal, signame), functools.partial(sig_handler, signame, self.signal_queue))
            # loop.add_signal_handler(getattr(signal, signame), lambda signame=signame: asyncio.create_task(sig_handler(signame)))

        self.terminal.start(self.cols, self.rows)
        self.init_screen()

        self.log("stdin: starting")
        await self.stdin.start(self.handle_stdin)

        self.log("idle loop")
        while self.up:
            await asyncio.sleep(1)

        self.log("stdin: stopping...")
        self.stdin.stop()
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
        self.slave_worker_done = loop.create_future()

        async def worker():
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
            self.slave_worker_done.set_result(True)
        asyncio.create_task(worker())

    async def stop_slave_worker(self):
        self.up = False
        return await(self.slave_worker_done)

    async def handle_slave_msg(self, msg):
        data = json.loads(msg)
        if "screen" in data:
            self.scrinit = data.get("screen")
            self.rows = self.scrinit['rows']
            self.cols = self.scrinit['cols']
            self.log(f"slv: screen info {self.scrinit['cols']}x{self.scrinit['rows']}")
            self.screen_data_available.set_result(True)
        elif "output" in data:
            data = base64.b64decode(data.get("output"))
            self.terminal.input(data)
        elif "bye" in data:
            return False
        return True

    def init_screen(self):
        for r in range(0, self.scrinit['rows']):
            for c in range(0, self.scrinit['cols']):
                ch = self.scrinit['dump'][r * self.scrinit['cols'] + c]
                try:
                    self.terminal.pad.addch(r, c, ch)
                except Exception as exc:
                    self.log(f"todo: {exc} {r} {c} {ch}")

        self.terminal.color_fg = self.scrinit['color_fg']
        self.terminal.color_bg = self.scrinit['color_bg']
        self.terminal.color_flags = self.scrinit['color_flags']
        self.terminal.col = self.scrinit['col']
        self.terminal.row = self.scrinit['row']
        self.log(f"mov: {self.terminal.row}, {self.terminal.col}")
        self.terminal.move(self.terminal.row, self.terminal.col)
        self.terminal.refresh()

    async def handle_stdin(self, data):
        await self.ws.send_str(json.dumps({"input": base64.b64encode(data).decode()}))
