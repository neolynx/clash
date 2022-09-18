#!/usr/bin/python3

import curses
import curses.panel
import sys
import fcntl
import os
import pty
import shlex
import re
import termios
import struct
import json
import psutil
import base64
import asyncio
import aiohttp
import signal
import functools
import traceback

global logfile
logfile = None


def log(msg):
    global logfile
    if logfile:
        logfile.write(f"{msg}\n")
        logfile.flush()


def term_any_key():
    global old_settings
    if old_settings:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
    curses.endwin()


clash = None


class ClaSH:

    @staticmethod
    def curses_wrapper(bkg):
        global clash
        clash = ClaSH(bkg)

    def __init__(self, bkg):
        self.bkg = bkg
        self.remainder = ""
        self.flags = 0
        self.up = True
        self.col = 0
        self.row = 0
        self.ws = None
        self.color_fg = -1
        self.color_bg = -1

    async def handle_server_msg(self, msg):
        log(f"srv: msg {msg}")
        data = json.loads(msg)
        log("don")
        if "init" in data:
            msg = {"screen": {
                      "rows": self.height,
                      "cols": self.width,
                      "col": self.col,
                      "row": self.row,
                      "color_fg": self.color_fg,
                      "color_bg": self.color_bg,
                      "color_flags": self.flags,
                      "dump": []}}
            for row in range(0, self.height):
                for col in range(0, self.width):
                    c = self.screen.inch(row, col)
                    msg["screen"]["dump"].append(c)
            await self.ws.send_str(json.dumps(msg))
        elif "input" in data:
            data = base64.b64decode(data.get("input"))
            self.p_out.write(data)

    async def handle_slave_msg(self, msg):
        log("slave msg")
        data = json.loads(msg)
        if "screen" in data:
            log("got screen info")
            scrinit = data.get("screen")
            log(f"slv: screen info {scrinit['cols']}x{scrinit['rows']}")
            for r in range(0, scrinit['rows']):
                for c in range(0, scrinit['cols']):
                    ch = scrinit['dump'][r * scrinit['cols'] + c]
                    try:
                        self.screen.addch(r, c, ch)
                    except Exception as exc:
                        log(f"todo: {exc} {r} {c} {ch}")

            self.color_fg = scrinit['color_fg']
            self.color_bg = scrinit['color_bg']
            self.color_flags = scrinit['color_flags']
            self.col = scrinit['col']
            self.row = scrinit['row']

            self.screen.move(self.row, self.col)
            self.screen.refresh()
        elif "output" in data:
            data = base64.b64decode(data.get("output"))
            self.input(data)

    async def connect(self):
        session = aiohttp.ClientSession()
        log("connecting")
        while self.up:
            try:
                async with session.ws_connect('http://localhost:8080/clash') as self.ws:
                    log("connected")

                    while self.up:
                        msg = await self.ws.receive()
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self.handle_server_msg(msg.data)
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
            except aiohttp.client_exceptions.ClientConnectorError:
                await asyncio.sleep(1)
                continue
            except Exception as exc:
                raise(exc)
                await asyncio.sleep(1)
                log("reconnecting")

    async def run_slave(self):
        def sig_handler(signum, frame):
            pass

        loop = asyncio.get_event_loop()
        for signame in {'SIGINT', 'SIGTERM'}:
            loop.add_signal_handler(getattr(signal, signame), functools.partial(sig_handler, signame, loop))

        self.init_curses()
        await self.init_stdin(self.handle_slave_stdin)

        await self.init_slave_connection()

        while self.up:
            await asyncio.sleep(1)

        log("terminating")
        term_any_key()

    async def run_master(self):
        def sig_handler(signum, frame):
            current_process = psutil.Process()
            children = current_process.children(recursive=True)
            # FIXME: only kill forground process?
            for child in children:
                if child.pid == self.shell_pid:
                    continue
                os.kill(int(child.pid), signal.SIGINT)
                break

        loop = asyncio.get_event_loop()
        for signame in {'SIGINT', 'SIGTERM'}:
            loop.add_signal_handler(getattr(signal, signame), functools.partial(sig_handler, signame, loop))

        self.init_curses()
        await self.init_pty()
        await self.init_stdin(self.handle_master_stdin)

        await self.init_master_connection()

        while self.up:
            await asyncio.sleep(1)
        log("terminating")
        term_any_key()

    def init_curses(self):
        self.screen = curses.initscr()

        curses.noecho()
        curses.cbreak()
        # curses.curs_set(0)
        curses.nl()
        self.screen.keypad(1)
        self.screen.scrollok(False)
        self.screen.refresh()
        self.height, self.width = self.bkg.getmaxyx()
        self.margin_top = 0
        self.margin_bottom = self.height

        curses.start_color()
        curses.use_default_colors()

        if (not curses.can_change_color() or curses.COLORS < 256):
            curses.endwin()
            print("Error: ncurses cannot change color! Please export TERM=xterm-256color")
            return

        idx = 1
        curses.init_pair(idx, -1, -1)
        idx += 1
        for i in range(30, 38):
            curses.init_pair(idx, i - 30, -1)
            idx += 1
        for i in range(40, 48):
            curses.init_pair(idx, -1, i - 40)
            idx += 1
        for j in range(40, 48):
            for i in range(30, 38):
                curses.init_pair(idx, i - 30, j - 40)
                idx += 1

    async def init_pty(self):
        self.shell_pid, self.p_out = open_terminal()

        async def handler(newloop):
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await newloop.connect_read_pipe(lambda: protocol, self.p_out)
            while self.up:
                try:
                    data = await reader.read(1024)
                except Exception:
                    self.up = False
                    break

                if not data:
                    break

                try:
                    log(f"pty: {data}")
                    self.input(data)
                except Exception:
                    log(traceback.format_exc())

                if self.ws:  # FIXME wait until initialized, mutex?
                    await self.ws.send_str(json.dumps({"output": base64.b64encode(data).decode()}))

        def thread_wrapper():
            newloop = asyncio.new_event_loop()
            asyncio.set_event_loop(newloop)
            newloop.run_until_complete(handler(newloop))

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, thread_wrapper)

    async def handle_master_stdin(self, data):
        self.p_out.write(data)

    async def handle_slave_stdin(self, data):
        await self.ws.send_str(json.dumps({"input": base64.b64encode(data).decode()}))

    async def init_stdin(self, stdin_handler):
        global old_settings
        old_settings = termios.tcgetattr(sys.stdin)
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
                log(str(exc))

        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, thread_wrapper)

    async def init_master_connection(self):
        asyncio.create_task(self.connect())

    async def init_slave_connection(self):
        session = aiohttp.ClientSession()
        log("slave: connecting")
        while self.up:
            try:
                async with session.ws_connect('http://localhost:8080/clash/slave') as self.ws:
                    log("slave: connected")

                    while self.up:
                        msg = await self.ws.receive()
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                await self.handle_slave_msg(msg.data)
                            except Exception:
                                log(traceback.format_exc())
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            break
            except Exception:
                await asyncio.sleep(1)
            log("slave :reconnecting")

    def linefeed(self):
        if self.row < self.margin_bottom - 1:
            self.row += 1
            self.screen.move(self.row, self.col)
        else:
            log("scroll up")
            # firstline = []
            # for col in range(0, self.width):
            #     c = self.screen.inch(0, col)
            #     firstline.append(c)
            # self.scrollback.append(firstline)

            self.screen.scrollok(True)
            self.screen.scroll()
            self.screen.scrollok(False)

    def puttext(self, text):
        color = self.get_color()
        log(f"put: {text}")
        length = len(text)
        if self.col + length > self.width:
            log(f"err: truncating {length} to {self.width - self.col - 1} rest: {bytes(text[self.width - self.col - 1:].encode())}")
            length = self.width - self.col - 1
        try:
            self.bkg.addstr(self.row, self.col, text[:length], color)
        except Exception:
            log(f"err: {self.row} {self.col} {bytes(text.encode())}")
        self.col += length

    def puts(self, msg):
        if not msg:
            return

        text = ""
        for c in msg:
            code = ord(c)
            if code < 32:
                if text:  # output text before special character
                    self.puttext(text)
                    text = ""

                # handle special character
                if code == 7:  # Bell
                    log("beep")
                elif code == 8:  # BS
                    if self.col > 0:
                        self.col -= 1
                        self.screen.move(self.row, self.col)
                elif code == 9:  # Tab
                    if self.col < self.width - 8:
                        try:
                            self.bkg.addstr(self.row, self.col, "        ", self.get_color())
                        except Exception:
                            log(f"err: {self.row} {self.col} '        ")
                        self.col += 8
                        self.screen.move(self.row, self.col)
                elif code == 10:  # LF
                    self.linefeed()
                    self.screen.move(self.row, self.col)
                elif code == 13:  # CR
                    self.col = 0
                    try:
                        self.screen.move(self.row, self.col)
                    except Exception:
                        log("err: CR move down")
                elif code == 15:  # reset font ??
                    self.flags = 0
                    self.color_fg = -1
                    self.color_bg = -1

                else:
                    log(f"todo: unknown ascii {ord(c)}")
#            if code > 127:
#                log(f"unknown ascii {ord(c)}")
            else:
                text += c

        if text:
            self.puttext(text)

    def set_color(self, params):
        # 0     	Reset or normal
        # 1     	Bold or increased intensity
        # 2     	Faint, decreased intensity, or dim
        # 3     	Italic
        # 4     	Underline
        # 5     	Slow blink
        # 6     	Rapid blink
        # 7     	Reverse video or invert
        # 8     	Conceal or hide
        # 9     	Crossed-out, or strike
        # 10     	Primary (default) font
        # 11–19 	Alternative font
        # 20     	Fraktur (Gothic)
        # 21     	Doubly underlined; or: not bold
        # 22     	Normal intensity
        # 23     	Neither italic, nor blackletter
        # 24     	Not underlined
        # 25     	Not blinking
        # 26     	Proportional spacing
        # 27     	Not reversed
        # 28     	Reveal
        # 29     	Not crossed out
        # 30–37 	Set foreground color
        # 38    	Set foreground color
        # 39    	Default foreground color
        # 40–47 	Set background color
        # 48 	    Set background color
        # 49     	Default background color
        # 50    	Disable proportional spacing
        # 51    	Framed
        # 52    	Encircled
        # 53    	Overlined
        # 54    	Neither framed nor encircled
        # 55    	Not overlined
        # 58    	Set underline color
        # 59    	Default underline color
        # 60    	Ideogram underline or right side line
        # 61    	Ideogram double underline, or double line on the right side
        # 62    	Ideogram overline or left side line
        # 63    	Ideogram double overline, or double line on the left side
        # 64    	Ideogram stress marking
        # 65    	No ideogram attributes
        # 73    	Superscript
        # 74    	Subscript
        # 75    	Neither superscript nor subscript
        # 90–97 	Set bright foreground color
        # 100–107 	Set bright background color

        for param in params:
            if param is None:
                continue

            if param == 0:
                self.flags = 0
                self.color_fg = -1
                self.color_bg = -1
            elif param == 1:
                self.flags |= curses.A_BOLD
            elif param == 2:
                self.flags |= curses.A_DIM
            elif param == 3:
                self.flags |= curses.A_ITALIC
            elif param == 4:
                self.flags |= curses.A_UNDERLINE
            elif param == 5:
                self.flags |= curses.A_BLINK
            elif param == 6:
                self.flags |= curses.A_BLINK
            elif param == 7:  # invert colors fg, bg
                self.flags |= curses.A_REVERSE

            elif param >= 30 and param <= 37:
                self.color_fg = param
            elif param >= 40 and param <= 47:
                self.color_bg = param

            elif param >= 90 and param <= 97:
                self.color_fg = param
                self.flags |= curses.A_STANDOUT
            elif param >= 100 and param <= 107:
                self.color_bg = param
                self.flags |= curses.A_STANDOUT

            elif param == 39:
                self.color_fg = -1
            elif param == 49:
                self.color_bg = -1

    def get_color(self):
        fg = bg = None
        if self.color_fg == -1:
            fg = -1
        elif self.color_fg >= 30 and self.color_fg <= 37:
            self.flags &= ~curses.A_STANDOUT
            fg = self.color_fg - 30
        elif self.color_fg >= 90 and self.color_fg <= 97:
            self.flags |= curses.A_STANDOUT
            fg = self.color_fg - 90

        if self.color_bg == -1:
            bg = -1
        elif self.color_bg >= 40 and self.color_bg <= 47:
            # self.flags &= ~A_BRIGHT
            bg = self.color_bg - 40
        elif self.color_bg >= 100 and self.color_bg <= 107:
            # self.flags |= A_BRIGHT
            bg = self.color_bg - 100

        if fg == -1 and bg == -1:
            color_idx = 0
        elif fg == -1:
            color_idx = bg * 8 + 2
        elif bg == -1:
            color_idx = fg + 2
        else:
            color_idx = fg + (bg + 2) * 8 + 2

        log(f"color: {fg} {bg} {color_idx}")
        log(f"clr: {self.color_fg} {self.color_bg} {self.flags}")
        return curses.color_pair(color_idx) | self.flags

    def ansi_unhandled(self, g):
        log(f"todo: {g[0]}")

    def ansi_reset_color(self, g):
        self.color_fg = -1
        self.color_bg = -1
        self.flags = 0

    def ansi_color(self, g):
        self.set_color([int(x) for x in g])

    def ansi_move_up(self, g):
        # FIXME: get rows optionally grom g[0]?
        rows = 1
        log(f"mov: up {rows} from {self.row}")
        self.row -= int(rows) - 1
        if self.row < 0:
            self.row = 0
        self.screen.move(self.row, self.col)

    def ansi_delete_chars(self, g):
        num = 1
        if len(g) > 0:
            try:
                num = int(g[0])
            except Exception:
                pass
        self.bkg.addstr(self.row, self.col, " " * num, self.get_color())

    def ansi_move_right(self, g):
        cols = 1
        if len(g) > 0:
            try:
                cols = int(g[0])
            except Exception:
                pass
        log(f"mov: right {cols} from {self.col}")
        self.col += cols
        self.screen.move(self.row, self.col)

    def ansi_move_row(self, g):
        row = g[0]
        self.row = int(row) - 1
        log(f"row: {self.row}")
        self.screen.move(self.row, self.col)

    def ansi_position_col(self, g):
        col = g[0]
        self.col = int(col) - 1
        self.screen.move(self.row, self.col)
        log(f"pos: {self.row} {self.col}")

    def ansi_insert_lines(self, g):
        count = g[0]
        blank = " " * self.width
        self.col = 0

        if self.row == 0:  # first row scroll up
            log("scroll down")
            self.screen.scrollok(True)
            self.screen.scroll(-1)
            self.screen.scrollok(False)

        for i in count:
            self.row += 1
            try:
                self.bkg.addstr(self.row, 0, blank, self.get_color())
            except Exception:
                log(f"err: {self.row} 0 ' ' * {self.width}")

        self.screen.move(self.row, self.col)

    def ansi_position(self, g):
        if len(g) > 1:
            row, col = g[0:2]
            self.row = int(row) - 1
            self.col = int(col) - 1
        elif len(g) == 1:
            col = g[0]
            self.col = int(col) - 1
        log(f"pos: {self.row} {self.col}")
        try:
            self.screen.move(self.row, self.col)
        except Exception:
            log(f"err: move {self.row} {self.col}")

    def ansi_pos_home(self, g):
        self.row = 0
        self.col = 0
        self.screen.move(self.row, self.col)

    def ansi_erase_line(self, g):
        log(f"erase line {g}")
        # ESC[K	erase in line (same as ESC[0K)
        # ESC[0K	erase from cursor to end of line
        # ESC[1K	erase start of line to the cursor
        # ESC[2K	erase the entire line

        param = g[0]
        variant = g[1]

        if variant == "X":  # erase right with optional length
            if param is not None:
                length = int(param)
            else:
                length = self.width - self.col
            start = self.col

        elif variant == "K":  # erase with different behavior
            if param == "" or int(param) == 0:  # erase from cursor to end of line
                length = self.width - self.col - 1
                start = self.col
            elif int(param) == 1:                 # erase start of line to the cursor
                length = self.col
                start = 0
            elif int(param) == 2:                 # erase the entire line
                length = self.width
                start = 0

        blank = " " * length
        try:
            # FIXME: should not move cursor, just will text
            self.bkg.addstr(self.row, start, blank, self.get_color())
            self.screen.move(self.row, self.col)
        except Exception:
            log(f"err: {self.row} {start} ' ' * {length}")

    def ansi_erase(self, g):

        if len(g) > 1:
            if g[1] == "0" or g[1] == "":  # J / 0J: erase from cursor until end of screen
                log(f"todo: erase from cursor until end of screen")

            elif g[1] == "1":  # 1J: erase from cursor to beginning of screen
                log(f"todo: erase scrollback")

            elif g[1] == "2":  # 2J: erase entire screen
                self.row = 0
                self.col = 0
                self.screen.move(self.row, self.col)
                blank = " " * self.width
                for r in range(self.row, self.height - 1):
                    try:
                        self.bkg.addstr(r, 0, blank, self.get_color())
                    except Exception:
                        log(f"err: {r} 0 ' ' * {self.width}")

            elif g[1] == "3":  # 3J: erase saved lines / scrollback
                log(f"todo: erase scrollback")

            else:
                log(f"todo: {g}")

        else:  # erase rest of line and screen
            blank = " " * (self.width - self.col)
            try:
                self.bkg.addstr(self.row, self.col, blank, self.get_color())
            except Exception:
                log(f"err: {self.row} {self.col} ' ' * {self.width - self.col}")

            blank = " " * self.width
            for r in range(self.row, self.height - 1):
                try:
                    self.bkg.addstr(r, 0, blank, self.get_color())
                except Exception:
                    log(f"err: {r} 0 ' ' * {self.width}")

    def ansi_hide_cursor(self, g):
        curses.curs_set(0)

    def ansi_show_cursor(self, g):
        curses.curs_set(1)

    def ansi_report(self, g):
        log(f"report {g}")
        code = None
        if len(g) > 1:
            try:
                code = int(g[1])
            except Exception:
                pass

        if code == 6:  # get cursoe pos
            self.p_out.write(f"\x1b[{self.col};{self.row}R".encode())  # ^[<v>;<h>R
        else:
            log(f"todo: report code {code}")

    def ansi_clear_screen(self, g):
        self.screen.clear()

    def ansi_set_margin(self, g):
        self.margin_top = int(g[0]) - 1
        self.margin_bottom = int(g[1]) - 1
        self.screen.setscrreg(self.margin_top, self.margin_bottom)
        log(f"scroll margin: {self.margin_top} {self.margin_bottom}")

    def ansi_scroll_up(self, g):
        rows = int(g[0])
        log(f"todo: scroll up: {rows}")

    def ansi_keypad(self, g):
        keypad = g[0]
        if keypad == "=":
            log(f"todo: alternate keypad mode")
        elif keypad == ">":
            log(f"todo: numkeypad mode")

    def ansi_charset(self, g):
        log(f"todo: Set United States G0 character set")

    def dec_private_modes(self, g):
        opt = g[0]
        try:
            opt = int(opt)
        except Exception:
            pass

        val = False
        if g[1] == 'h':  # set
            val = True
        elif g[1] == 'l':  # reset
            val = False

        if opt == 1:
            log(f"todo: dec: Application Cursor Keys {val}")

        elif opt == 7:
            log(f"todo: dec: autowrap {val}")

        elif opt == 12:
            log(f"todo: dec: blinking cursor  {val}")

        elif opt == 1000:
            log(f"todo: dec: X11 mouse {val}")

        elif opt == 1049:
            log(f"dec: Save cursor and switch to alternate buffer clearing it {val}")
            if val is True:
                self.savedcol = self.col
                self.savedrow = self.row
                self.savedbuffer = []
                for row in range(0, self.height):
                    for col in range(0, self.width):
                        c = self.screen.inch(row, col)
                        self.savedbuffer.append(c)
            else:
                for r in range(0, self.height):
                    for c in range(0, self.width):
                        ch = self.savedbuffer[r * self.width + c]
                        try:
                            self.screen.addch(r, c, ch)
                        except Exception as exc:
                            log(f"todo: {exc} {r} {c} {ch}")
                self.savedbuffer = []
                self.col = self.savedcol
                self.row = self.savedrow
                self.screen.move(self.row, self.col)

        elif opt == 2004:
            log(f"todo: dec: Set bracketed paste mode {val}")
            # https://cirw.in/blog/bracketed-paste

        else:
            log(f"todo: dec {opt} {val}")

    def xterm_set_window_title(self, g):
        log(f"window title: {g[0]}")

    def ansi_secondary_device(self, g):
        log("todo: dec: set secondary device attributes")

    def addansi(self, bkg, row, col, line):
        # https://espterm.github.io/docs/VT100%20escape%20codes.html
        # https://man7.org/linux/man-pages/man4/console_codes.4.html
        # https://xtermjs.org/docs/api/vtfeatures/
        # https://invisible-island.net/xterm/ctlseqs/ctlseqs.html

        ansi = {
                r"\[(\d+)[mM]": self.ansi_color,
                r"\[(\d+);(\d+)m": self.ansi_color,
                r"\[(\d+);(\d+);(\d+)m": self.ansi_color,
                r"\[(\d+);(\d+)H": self.ansi_position,
                r"\[(\d+)H": self.ansi_position,
                r"(\[4l)": self.ansi_unhandled,  # ReSet insert mode.
                r"\[\?25l": self.ansi_hide_cursor,
                r"\[\?25h": self.ansi_show_cursor,
                r"\[\?1c": self.ansi_hide_cursor,
                r"\[\?0c": self.ansi_show_cursor,
                r"(\)0)": self.ansi_unhandled,  # )0 Start / (0 Select VT100 graphics mapping
                r"\[(\d+);(\d+)r": self.ansi_set_margin,
                r"(\[(\d+)n)": self.ansi_report,
                r"\[(\d+)d": self.ansi_move_row,
                r"\[\?(\d+)([hl])": self.dec_private_modes,
                r"\[(\d*)([XK])": self.ansi_erase_line,
                r"(\[(\d+)A)": self.ansi_unhandled,  # move cursor up
                r"\[(\d+)G": self.ansi_position_col,
                r"(\[(\d+)M)": self.ansi_unhandled,
                r"\[(\d*)L": self.ansi_insert_lines,
                r"(\[(\d*)J)": self.ansi_erase,
                r"(\[(\d+)P)": self.ansi_delete_chars,  # delete n chars from pos
                r"\[(\d*)C": self.ansi_move_right,
                r"\[H": self.ansi_pos_home,
                r"M": self.ansi_move_up,   # https://www.aivosto.com/articles/control-characters.html
                r"\[m": self.ansi_reset_color,
                r"(\[?1000l)": self.ansi_unhandled,  # X11 Mouse Reporting
                r"(c)": self.ansi_unhandled,  # Reset
                r"(\]R)": self.ansi_unhandled,  # Reset Palette
                r"\]0;([^\a]+)\a": self.xterm_set_window_title,
                r"(\[>c)": self.ansi_secondary_device,
                r"(\]10;\?\x07)": self.ansi_unhandled,
                r"(\]11;\?\x07)": self.ansi_unhandled,
                r"(\[2(\d);(\d)t)": self.ansi_unhandled,
                r"(\[2(\d);(\d);(\d)t)": self.ansi_unhandled,
                r"(\[>(\d);(\d?)m)": self.ansi_unhandled,
                r"(\[?2004h)": self.ansi_unhandled,
                r"(=)": self.ansi_keypad,
                r"(>)": self.ansi_keypad,
                r"(\(B)": self.ansi_charset,
                r"(\](\d+)\x07)": self.ansi_unhandled,
                r"(\[!p)": self.ansi_unhandled,
                r"(\[\?(\d);(\d)l)": self.ansi_unhandled,
                r"(\(0)": self.ansi_unhandled,
                r"(\[(\d)S)": self.ansi_scroll_up,
                r"(\[(\d+)@)": self.ansi_unhandled,  # CSI Ps @  Insert Ps (Blank) Character(s) (default = 1) (ICH).
                r"\[(\d+)T": self.ansi_unhandled,  # CSI Ps T  Scroll down Ps lines (default = 1) (SD), VT420.
        }

        if self.remainder:
            line = self.remainder + line
            self.remainder = ""

        while self.up:
            parts = line.split(b"\033", 1)
            if parts[0] != "":
                try:
                    self.puts(parts[0].decode(errors="replace"))
                except Exception:
                    log(f"err: puts {parts[0]}")
                    log(traceback.format_exc())

            if len(parts) == 1:
                break

            part = parts[1]
            if part == "":
                self.remainder = b"\033"
                break

            handled = False
            for a in ansi:
                try:
                    # FIXME: precompile
                    r = re.compile(fr"^{a}(.*)".encode(), re.DOTALL)
                except Exception:
                    log(f"todo: error compiling {a}")
                    continue
                m = r.match(part)
                if m:
                    g = m.groups()
                    ansi[a]([x.decode() for x in g[:-1]])
                    line = g[-1]
                    handled = True
                    break

            if not handled:
                if b"\033" not in part:
                    self.remainder = b"\033" + part
                    break
                else:
                    log(f"todo: unknown esc seq: {part}")
                    line = part

    def input(self, data):
        self.addansi(self.bkg, self.row, self.col, data)
        self.screen.refresh()


def terminal_size():
    h, w, hp, wp = struct.unpack('HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ,
                                 struct.pack('HHHH', 0, 0, 0, 0)))
    return w, h


def open_terminal(command="bash", columns=None, lines=None):

    if not columns or not lines:
        columns, lines = terminal_size()

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

    return p_pid, p_out


def main():
    global logfile
    curses.wrapper(ClaSH.curses_wrapper)

    loop = asyncio.get_event_loop()
    if len(sys.argv) > 1:
        logfile = open("log-slave.txt", "w+")
        loop.run_until_complete(clash.run_slave())
    else:
        logfile = open("log-master.txt", "w+")
        loop.run_until_complete(clash.run_master())


if __name__ == "__main__":
    main()
