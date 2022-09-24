#!/usr/bin/python3

import fcntl
import os
import pty
import shlex
import asyncio
import struct
import termios
import signal
import psutil


class ClashShell:

    def __init__(self, log=None):
        self.log = log
        self.up = True

    async def start(self, terminal_handler, columns, lines):
        self.columns = columns
        self.lines = lines
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

    def open_shell(self, command="bash"):

        self.shell_pid, self.master_fd = pty.fork()
        if self.shell_pid == 0:  # child
            argv = shlex.split(command)
            env = dict(COLUMNS=str(self.columns), LINES=str(self.lines))
            env.update(dict(LANG=os.environ["LANG"],
                            TERM=os.environ["TERM"],
                            HOME=os.environ["HOME"]))
            os.execvpe(argv[0], argv, env)
            # child ends here

        # parent
        self.p_out = os.fdopen(self.master_fd, "w+b", 0)
        orig_fl = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self.master_fd, fcntl.F_SETFL, orig_fl | os.O_NONBLOCK)

    def write(self, data):
        try:
            self.p_out.write(data)
        except Exception:
            self.up = False

    def resize(self, cols, rows):
        self.log(f"resize: {cols}x{rows}")
        s = struct.pack('HHHH', rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, s)

        # does not work:
        # os.kill(self.shell_pid, signal.SIGWINCH)

        # crashes:
        # current_process = psutil.Process()
        # children = current_process.children(recursive=True)
        # for child in children:
        #     tgid = None
        #     with open(f"/proc/{child.pid}/stat", "r") as f:
        #         line = f.readline()
        #         tgid = int(line.split(" ")[7].strip())
        #     if tgid == child.pid:  # foreground process
        #         self.log(f"resize: sending SIGWINCH to {child.pid}")
        #         os.kill(child.pid, signal.SIGWINCH)
        #         break
