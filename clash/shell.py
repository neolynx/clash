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
        self.open_terminal()

        async def handler(newloop):
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await newloop.connect_read_pipe(lambda: protocol, self.p_out)
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

        def thread_wrapper():
            newloop = asyncio.new_event_loop()
            asyncio.set_event_loop(newloop)
            newloop.run_until_complete(handler(newloop))

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, thread_wrapper)

    def open_terminal(self, command="bash", columns=None, lines=None):
        if not columns or not lines:
            lines, columns, _, _ = struct.unpack('HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ,
                                                 struct.pack('HHHH', 0, 0, 0, 0)))

        p_pid, master_fd = pty.fork()
        if p_pid == 0:  # Child.
            argv = shlex.split(command)
            env = dict(COLUMNS=str(columns), LINES=str(lines))
            env.update(dict(LANG=os.environ["LANG"],
                            TERM=os.environ["TERM"]))
            os.execvpe(argv[0], argv, env)

        # File-like object for I/O with the child process aka command.
        p_out = os.fdopen(master_fd, "w+b", 0)

        orig_fl = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, orig_fl | os.O_NONBLOCK)

        self.shell_pid = p_pid
        self.p_out = p_out
