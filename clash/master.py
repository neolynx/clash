#!/usr/bin/python3

import os
import json
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
        self.sigqueue = asyncio.Queue()
        self.host = os.environ.get('USER', "nobody")
        self.members = []

    def sig_handler(self, signame):
        if signame == "SIGINT" or signame == "SIGTERM":
            self.shell.write("\x03".encode())
        elif signame == "SIGTSTP":
            self.shell.write("\x1a".encode())
        elif signame == "SIGWINCH":
            self.sigqueue.put_nowait(signame)
        else:
            self.log(f"todo: sig: {signame}")

    async def run(self):
        loop = asyncio.get_event_loop()

        async def sig_worker():
            while self.up:
                signame = await self.sigqueue.get()
                if signame == "SIGWINCH":
                    await self.resize()

        loop.create_task(sig_worker())

        if not await self.init_master_connection():
            print(f"connecting to {self.url} failed")
            return

        self.log("terminal: starting")
        for signame in {'SIGINT', 'SIGTERM', 'SIGTSTP', 'SIGWINCH'}:
            loop.add_signal_handler(getattr(signal, signame), functools.partial(self.sig_handler, signame))

        self.log("master: starting")
        self.session_ready = loop.create_future()
        await self.run_master_worker(loop)
        self.session_id = await(self.session_ready)

        cols, rows = self.terminal.start(session_id=self.session_id)
        self.terminal.input(f"\r\n \x1b[38;5;69m\x1b[48;5;0m -= collaboration shell =-".encode())
        self.terminal.input(f"  clash {self.session_id} \x1b[m\r\n\r\n".encode())

        self.terminal.set_title(f"[ {self.host} ]")

        self.log("shell: starting")
        await self.shell.start(self.handle_terminal, cols, rows)

        self.log("stdin: starting")
        await self.stdin.start(self.handle_stdin)

        self.log("idle loop")
        while self.up and self.shell.up and self.stdin.up:
            await asyncio.sleep(1)

        self.log("stdin: stopping...")
        await self.stdin.stop()
        self.log("master: stopping...")
        await self.stop_master_worker()
        self.log("terminal: stopping...")
        self.terminal.stop()
        self.log("clash: terminated")
        print("[exited]")

    async def handle_server_msg(self, msg):
        data = json.loads(msg)
        if "header" in data:
            slave_id = data["header"]["from"]
            self.log(f"from {slave_id}")
        if "session" in data:
            session_id = data.get("session")
            self.session_ready.set_result(session_id)
        elif "init" in data:
            username = data.get("init")
            self.log(f"join: {username}")
            self.members.append(username)
            members = ", ".join(self.members)
            self.terminal.set_title(f"[ {self.host} ] <{members}>")
            msg = {"init": {}, "header": {"to": slave_id}}
            msg["init"]["screen"] = self.terminal.dump()
            msg["init"]["host"] = self.host
            if self.ws:
                try:
                    await self.ws.send_str(json.dumps(msg))
                except Exception:
                    self.log(traceback.format_exc())
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
                    try:
                        await self.handle_server_msg(msg.data)
                    except Exception:
                        self.log(traceback.format_exc())

                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
            self.up = False
            if self.ws:
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
            try:
                await self.ws.send_str(json.dumps({"output": base64.b64encode(data).decode()}))
            except Exception:
                self.log(traceback.format_exc())
                self.ws = None

    async def init_master_connection(self):
        self.client_session = aiohttp.ClientSession()
        try:
            self.ws = await self.client_session.ws_connect(self.url)
        except Exception as exc:
            await self.client_session.close()
            print(exc)
            return False
        return True

    async def stop_master_worker(self):
        self.log("master: terminating...")
        self.up = False
        if self.ws:
            try:
                await self.ws.send_str("{\"bye\":\"bye\"}")
                await self.ws.close()
            except Exception as exc:
                self.log(f"master: {exc}")
        await(self.master_worker)
        self.log("master: terminated")

    async def resize(self):
        cols, rows = self.terminal.resize(full=True, inner=True)
        self.shell.resize(cols - 1, rows - 1)
        if self.ws:
            try:
                await self.ws.send_str(json.dumps({"resize": [cols, rows]}))
            except Exception:
                self.log(traceback.format_exc())
