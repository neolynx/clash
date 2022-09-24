#!/usr/bin/python3

import fcntl
import os
import pty
import shlex
import termios
import struct
import asyncio


class ClashShell:

    def __init__(self, log=None):
        self.log = log
        self.up = True

    async def start(self, terminal_handler):
        self.open_shell()

        async def handler():
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, self.p_out)
            while self.up:
                try:
                    data = await reader.read(1024)
                except Exception:
                    await terminal_handler(None)
                    self.up = False
                    break

                await terminal_handler(data)
                if not data:
                    self.up = False
                    break
            self.log("shell: terminated")

        loop = asyncio.get_event_loop()
        loop.create_task(handler())

    def open_shell(self, command="bash", columns=None, lines=None):
        if not columns or not lines:
            lines, columns, _, _ = struct.unpack('HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ,
                                                 struct.pack('HHHH', 0, 0, 0, 0)))

        self.shell_pid, master_fd = pty.fork()
        if self.shell_pid == 0:  # child
            argv = shlex.split(command)
            env = dict(COLUMNS=str(columns), LINES=str(lines))
            env.update(dict(LANG=os.environ["LANG"],
                            TERM=os.environ["TERM"],
                            HOME=os.environ["HOME"]))
            os.execvpe(argv[0], argv, env)

        self.p_out = os.fdopen(master_fd, "w+b", 0)

        orig_fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, orig_fl | os.O_NONBLOCK)

    def write(self, data):
        try:
            self.p_out.write(data)
        except Exception:
            self.up = False
