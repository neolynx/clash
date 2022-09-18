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

    async def init(self, stdin_handler):
        self.old_settings = termios.tcgetattr(sys.stdin)
        new_settings = termios.tcgetattr(sys.stdin)
        new_settings[3] = new_settings[3] & ~(termios.ECHO | termios.ICANON)  # lflags
        new_settings[6][termios.VMIN] = 0   # cc
        new_settings[6][termios.VTIME] = 0  # cc
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, new_settings)

        # set sys.stdin non-blocking
        orig_fl = fcntl.fcntl(sys.stdin, fcntl.F_GETFL)
        fcntl.fcntl(sys.stdin, fcntl.F_SETFL, orig_fl | os.O_NONBLOCK)

        async def handler(newloop):
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await newloop.connect_read_pipe(lambda: protocol, sys.stdin)

            while self.up:
                data = await reader.read(1024)
                if not data:
                    break
                await stdin_handler(data)

        def thread_wrapper():
            try:
                newloop = asyncio.new_event_loop()
                asyncio.set_event_loop(newloop)
                newloop.run_until_complete(handler(newloop))
            except Exception as exc:
                self.log(str(exc))

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, thread_wrapper)

    def term_any_key(self):
        if self.old_settings:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
