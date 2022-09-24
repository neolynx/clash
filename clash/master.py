#!/usr/bin/python3

import os
import json
import psutil
import base64
import asyncio
import aiohttp
import signal
import functools
import traceback

from .terminal import ClashTerminal
from .shell import ClashShell
from .stdin import ClashStdin


class ClashMaster:

    def __init__(self, log=None, url="http://localhost:8080/clash"):
        self.log = log
        self.url = url
        self.up = True
        self.shell = ClashShell(log=log)
        self.terminal = ClashTerminal(log=log, shell_input=self.shell.write)
        self.stdin = ClashStdin(log=log)

    def sig_handler(self, signame):
        if signame == "SIGINT":
            signum = signal.SIGINT
        elif signame == "SIGTERM":
            signum = signal.SIGTERM
        elif signame == "SIGTSTP":
            signum = signal.SIGTSTP
        elif signame == "SIGCONT":
            signum = signal.SIGCONT
        else:
            self.log(f"todo: sig: {signame}")
            return
        self.log(f"sig: {signame}")
        current_process = psutil.Process()
        children = current_process.children(recursive=True)
        for child in children:
            tgid = None
            with open(f"/proc/{child.pid}/stat", "r") as f:
                line = f.readline()
                tgid = int(line.split(" ")[7].strip())
            if tgid == child.pid:  # foreground process
                os.kill(child.pid, signum)
                break

    async def run(self):

        loop = asyncio.get_event_loop()
        for signame in {'SIGINT', 'SIGTERM', 'SIGTSTP', 'SIGCONT'}:
            loop.add_signal_handler(getattr(signal, signame), functools.partial(self.sig_handler, signame))

        print("Connecting to server ...")
        if not await self.init_master_connection():
            print("connection failed")
            return

        self.log("terminal: starting")
        self.terminal.start()

        self.log("master: starting")
        self.session_ready = loop.create_future()
        await self.run_master_worker(loop)
        self.session_id = await(self.session_ready)

        self.terminal.input(f"\r\n  -= collaboration shell =-\r\n".encode())
        self.terminal.input(f"       clash {self.session_id}\r\n\r\n".encode())

        self.log("shell: starting")
        await self.shell.start(self.handle_terminal)

        self.log("stdin: starting")
        await self.stdin.start(self.handle_stdin)

        self.log("idle loop")
        while self.up and self.shell.up:
            await asyncio.sleep(1)

        self.log("stdin: stopping...")
        await self.stdin.stop()
        self.log("master: stopping...")
        await self.stop_master_worker()
        self.log("terminal: stopping...")
        self.terminal.stop()
        self.log("clash: terminated")
        print("terminated.\n")

    async def handle_server_msg(self, msg):
        self.log(f"srv: msg {msg}")
        data = json.loads(msg)
        if "session" in data:
            session_id = data.get("session")
            self.session_ready.set_result(session_id)
        elif "init" in data:
            msg = {"screen": {
                      "rows": self.terminal.height,
                      "cols": self.terminal.width,
                      "col": self.terminal.col,
                      "row": self.terminal.row,
                      "color_fg": self.terminal.color_fg,
                      "color_bg": self.terminal.color_bg,
                      "color_flags": self.terminal.flags,
                      "dump": []}}
            for row in range(0, self.terminal.height):
                for col in range(0, self.terminal.width):
                    c = self.terminal.screen.inch(row, col)
                    msg["screen"]["dump"].append(c)
            await self.ws.send_str(json.dumps(msg))
        elif "input" in data:
            data = base64.b64decode(data.get("input"))
            self.shell.write(data)
        elif "signal" in data:
            self.sig_handler(data.get("signal"))

    async def run_master_worker(self, loop):
        self.master_worker = loop.create_future()

        async def worker():
            while self.up:
                msg = await self.ws.receive()
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self.handle_server_msg(msg.data)
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
            self.up = False
            try:
                await self.ws.send_str("{\"bye\":\"bye\"}")
                await self.client_session.close()
            except Exception:
                pass
            self.master_worker.set_result(True)
        asyncio.create_task(worker())

    async def handle_stdin(self, data):
        self.shell.write(data)

    async def handle_terminal(self, data):
        if not data:
            self.up = False
            return

        try:
            self.log(f"pty: {data}")
            self.terminal.input(data)
        except Exception:
            self.log(traceback.format_exc())

        if self.ws:  # FIXME wait until initialized, mutex?
            await self.ws.send_str(json.dumps({"output": base64.b64encode(data).decode()}))

    async def init_master_connection(self):
        self.client_session = aiohttp.ClientSession()
        print(f"master: connecting to {self.url}")
        try:
            self.ws = await self.client_session.ws_connect(self.url)
        except Exception as exc:
            await self.client_session.close()
            print(exc)
            return False
        print("master: connected")
        return True

    async def stop_master_worker(self):
        self.log("master: terminating...")
        self.up = False
        try:
            await self.ws.send_str("{\"bye\":\"bye\"}")
            await self.ws.close()
        except Exception as exc:
            self.log(f"master: {exc}")
        await(self.master_worker)
        self.log("master: terminated")
