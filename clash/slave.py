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

    def __init__(self, log=None):
        self.log = log
        self.up = True
        self.terminal = ClashTerminal(log=log)
        self.stdin = ClashStdin(log=log)

    async def run(self, session_id):
        def sig_handler(signum, frame):
            pass

        loop = asyncio.get_event_loop()
        for signame in {'SIGINT', 'SIGTERM'}:
            loop.add_signal_handler(getattr(signal, signame), functools.partial(sig_handler, signame, loop))

        print("Connecting to server ...")
        if not await self.init_slave_connection(session_id):
            print("connection failed")
            return

        self.log("terminal: starting")
        self.terminal.start()

        self.log("master: starting")
        await self.run_slave_worker(loop)

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
        print("terminated.\n")

    async def init_slave_connection(self, session_id):
        url = f"http://localhost:8080/clash/{session_id}"
        self.master_session = aiohttp.ClientSession()
        print(f"slave: connecting to {url}")
        try:
            self.ws = await self.master_session.ws_connect(url)
        except Exception as exc:
            await self.master_session.close()
            print(exc)
            return False
        print("slave: connected")
        return True

    async def run_slave_worker(self, loop):
        self.slave_worker = loop.create_future()

        async def worker():
            while self.up:
                msg = await self.ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        await self.handle_slave_msg(msg.data)
                    except Exception:
                        self.log(traceback.format_exc())
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
            await self.client_session.close()
            self.slave_worker.set_result(True)
        asyncio.create_task(worker())

    async def stop_slave_worker(self):
        return await(self.slave_worker)

    async def handle_slave_msg(self, msg):
        self.log("slave msg")
        data = json.loads(msg)
        if "screen" in data:
            self.log("got screen info")
            scrinit = data.get("screen")
            self.log(f"slv: screen info {scrinit['cols']}x{scrinit['rows']}")
            for r in range(0, scrinit['rows']):
                for c in range(0, scrinit['cols']):
                    ch = scrinit['dump'][r * scrinit['cols'] + c]
                    try:
                        self.terminal.screen.addch(r, c, ch)
                    except Exception as exc:
                        self.log(f"todo: {exc} {r} {c} {ch}")

            self.color_fg = scrinit['color_fg']
            self.color_bg = scrinit['color_bg']
            self.color_flags = scrinit['color_flags']
            self.col = scrinit['col']
            self.row = scrinit['row']

            self.terminal.screen.move(self.row, self.col)
            self.terminal.screen.refresh()
        elif "output" in data:
            data = base64.b64decode(data.get("output"))
            self.terminal.input(data)

    async def handle_stdin(self, data):
        await self.ws.send_str(json.dumps({"input": base64.b64encode(data).decode()}))
