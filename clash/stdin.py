#!/usr/bin/python3

import sys
import fcntl
import os
import termios
import asyncio


class ClashStdin:

    def __init__(self, log=None):
        self.log = log
        self.up = True
        self.gotCtrlA = False

    async def start(self, stdin_handler, hotkey_handler=None):
        self.hotkey_handler = hotkey_handler

        async def handler():
            self.log("stdin: handler started")
            self.reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(self.reader)
            await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin)

            self.old_settings = termios.tcgetattr(sys.stdin)
            new_settings = termios.tcgetattr(sys.stdin)
            new_settings[3] = new_settings[3] & ~(termios.ECHO | termios.ICANON)  # lflags
            new_settings[6][termios.VMIN] = 0   # cc
            new_settings[6][termios.VTIME] = 0  # cc
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, new_settings)

            # set sys.stdin non-blocking
            orig_fl = fcntl.fcntl(sys.stdin, fcntl.F_GETFL)
            fcntl.fcntl(sys.stdin, fcntl.F_SETFL, orig_fl | os.O_NONBLOCK)

            while self.up:
                data = await self.reader.read(1024)
                if self.hotkey_handler:
                    if data == b'\x01':  # Ctrl-A
                        if self.gotCtrlA:
                            self.gotCtrlA = False
                            # fallthrough: send real Ctrl-A
                        else:
                            self.gotCtrlA = True
                            continue
                    elif self.gotCtrlA:
                        self.gotCtrlA = False
                        await self.hotkey_handler(data)
                        continue

                if not data:
                    self.up = False
                    break
                await stdin_handler(data)

            self.log(f"stdin: handler done")

        loop = asyncio.get_event_loop()
        self.task = loop.create_task(handler())

        self.log(f"stdin: start done")

    async def stop(self):
        self.log("stdin: terminating...")
        self.up = False
        self.task.cancel()
        try:
            await self.task
        except asyncio.CancelledError:
            pass
        if self.old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
        self.log("stdin: terminated")
