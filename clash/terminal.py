#!/usr/bin/python3

import curses
import curses.panel
import re
import traceback
import os

from struct import pack, unpack
from fcntl import ioctl
from termios import TIOCGWINSZ


class ClashTerminal:

    def __init__(self, log=None, shell_input=None):
        self.log = log
        self.shell_input = shell_input
        self.remainder = ""
        self.flags = 0
        self.cols = 0
        self.rows = 0
        self.col = 0
        self.row = 0
        self.color_fg = -1
        self.color_bg = -1
        self.dec_blinking_cursor = True
        self.colors = {}
        self.charset_lines = False
        self.border_row = None
        self.border_col = None
        self.less_rows = None
        self.less_cols = None
        self.title = " clash "

        # dec
        self.dec_bracketed_paste_mode = False

        # vt100
        self.saved_row = self.row
        self.saved_col = self.col

    def start(self, cols=0, rows=0, session_id=" clash "):
        self.session_id = session_id
        self.screen = curses.initscr()

        self.height, self.width = self.screen.getmaxyx()
        if not rows or not cols:
            self.rows = self.height - 1
            self.cols = self.width - 1
        else:
            self.cols = cols
            self.rows = rows
        self.log(f"terminal: starting {self.cols}x{self.rows} ({self.width} {self.height})")
        self.pad = curses.newpad(self.rows, self.cols + 1)  # 1 more column to allow printing to the last bottom right character

        curses.noecho()
        curses.cbreak()
        # curses.curs_set(0)
        curses.nl()
        self.screen.keypad(1)
        self.screen.scrollok(False)
        # curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        self.refresh()
        self.margin_top = 0
        self.margin_bottom = self.rows

        curses.start_color()
        curses.use_default_colors()

        if (not curses.can_change_color() or curses.COLORS < 256):
            curses.endwin()
            raise Exception("Error: ncurses cannot change color! Please export TERM=xterm-256color")

        self.update_border()
        self.refresh()
        return self.cols, self.rows

    def stop(self):
        self.log("terminal: terminating...")
        curses.nocbreak()
        self.screen.keypad(False)
        curses.echo()
        curses.endwin()
        self.log("terminal: terminated")

    def update_border(self):
        old_color_fg = self.color_fg
        old_color_bg = self.color_bg
        old_flags = self.flags

        row = self.rows
        col = self.cols
        self.less_rows = False
        self.less_cols = False
        if row >= self.height:
            row = self.height - 1
            self.less_rows = True
        if col >= self.width:
            col = self.width - 1
            self.less_cols = True

        bottom = "─"
        right = "│"
        corner = "╯"
        if self.less_rows:
            bottom = corner = "↓"
        if self.less_cols:
            right = corner = "→"
        if self.less_rows and self.less_cols:
            corner = "↘"

        self.color_fg = 69
        self.color_bg = 0
        self.flags = 0
        curses.curs_set(0)

        self.screen.addstr(row, 0, bottom * 2, self.get_color())
        self.screen.addstr(row, 2, self.title, self.get_color())
        pos = 2 + len(self.title)

        session = f"⟨ {self.session_id} ⟩"
        self.screen.addstr(row, pos, bottom * (col - len(session) - 7 - len(self.title) - 2), self.get_color())
        self.screen.addstr(row, col - len(session) - 7, session, self.get_color())
        self.screen.addstr(row, col - 7, bottom * 7, self.get_color())
        for i in range(0, row):
            self.screen.addstr(i, col, right, self.get_color())
        # writing to bottom right corner throws an exception, but works
        try:
            self.screen.addstr(row, col, corner, self.get_color())
        except Exception:
            pass
        self.border_row = row
        self.border_col = col

        self.color_fg = old_color_fg
        self.color_bg = old_color_bg
        self.flags = old_flags

        self.move_cursor(self.row, self.col)
        curses.curs_set(1)

    def linefeed(self):
        if self.row < self.margin_bottom - 1:
            self.row += 1
            # self.log(f"pos: linefeed {self.row}")
            self.move_cursor(self.row, self.col)
        else:
            self.log("pos: scroll up")
            # firstline = []
            # for col in range(0, self.width):
            #     c = self.screen.inch(0, col)
            #     firstline.append(c)
            # self.scrollback.append(firstline)

            # reset color attributes
            self.flags = 0
            self.color_fg = -1
            self.color_bg = -1

            self.pad.scrollok(True)
            self.pad.scroll()
            self.pad.scrollok(False)

    def puttext(self, text):
        color = self.get_color()
        # self.log(f"put: {self.row}x{self.col}: {text}")
        length = len(text)
        if self.col + length > self.cols:
            self.log(f"err: truncating {length} to {self.cols - self.col - 1} rest: {bytes(text[self.cols - self.col - 1:].encode())}")
            length = self.cols - self.col - 1

        if self.charset_lines:
            map_linechar_utf8 = {
                    "l": "┌",
                    "x": "│",
                    "j": "┘",
                    "q": "─",
                    "k": "┐",
                    "m": "└",
                    }
            for k in map_linechar_utf8:
                text = text.replace(k, map_linechar_utf8[k])

        try:
            self.pad.addstr(self.row, self.col, text[:length], color)
        except Exception:
            self.log(f"err: {self.row} {self.col} {bytes(text.encode())}")
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
                    self.log("beep")
                elif code == 8:  # BS
                    if self.col > 0:
                        self.col -= 1
                        self.move_cursor(self.row, self.col)
                elif code == 9:  # Tab
                    if self.col < self.cols - 8:
                        try:
                            self.pad.addstr(self.row, self.col, "        ", self.get_color())
                        except Exception:
                            self.log(f"err: {self.row} {self.col} '        ")
                        self.col += 8
                        self.move_cursor(self.row, self.col)
                elif code == 10:  # LF
                    # self.log("chr: LF")
                    self.linefeed()
                elif code == 13:  # CR
                    # self.log(f"chr: CR {self.row}")
                    self.col = 0
                    self.move_cursor(self.row, self.col)
                elif code == 15:  # reset font ??
                    self.flags = 0
                    self.color_fg = -1
                    self.color_bg = -1

                else:
                    self.log(f"todo: unknown ascii {ord(c)}")
#            if code > 127:
#                self.log(f"unknown ascii {ord(c)}")
            else:
                text += c

        if text:
            self.puttext(text)

    def set_color(self, params):

        if len(params) == 0:  # reset
            self.flags = 0
            self.color_fg = -1
            self.color_bg = -1
            return

        # check for 256 color
        color256 = False
        color256fg = False
        color256bg = False
        for param in params:
            if param is None:
                continue
            if param == 38:
                color256fg = True
            if param == 48:
                color256bg = True
            if param == 5 and (color256fg or color256bg):
                color256 = True

            if not color256:
                if param == 0:  # reset
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
                    if self.dec_blinking_cursor:
                        self.flags |= curses.A_BLINK
                    else:
                        # self.flags |= curses.A_STANDOUT
                        self.log("todo: blink with .dec_blinking_cursor false")
                elif param == 6:
                    self.log("todo: color flag 6")
                    self.flags |= curses.A_STANDOUT

                elif param == 7:
                    self.flags |= curses.A_REVERSE

                elif param == 27:
                    self.flags &= ~curses.A_REVERSE

                elif param >= 30 and param <= 37:
                    self.color_fg = param - 30
                elif param >= 40 and param <= 47:
                    self.color_bg = param - 40

                elif param >= 90 and param <= 97:
                    self.color_fg = param - 90 + 8
                elif param >= 100 and param <= 107:
                    self.color_bg = param - 100 + 8

                # 256 color flags
                elif param == 38:
                    continue
                elif param == 48:
                    continue

                elif param == 39:
                    self.color_fg = -1
                elif param == 49:
                    self.color_bg = -1

                else:
                    self.log(f"todo: clr {param}")

            elif color256fg:
                self.color_fg = param
            elif color256bg:
                self.color_bg = param

    def get_color(self):
        idx = -1
        fg = 2  # green
        bg = 0  # black

        if self.color_fg != -1:
            fg = self.color_fg
        if self.color_bg != -1:
            bg = self.color_bg

        if bg * 256 + fg not in self.colors:
            idx = len(self.colors)
            self.log(f"clr: adding {idx}: {fg} {bg}")
            curses.init_pair(idx + 1, fg, bg)
            self.colors[bg * 256 + fg] = idx
        else:
            idx = self.colors[bg * 256 + fg]

        return curses.color_pair(idx + 1) | self.flags

    def ansi_unhandled(self, g):
        self.log(f"todo: esc seq '\\x1b{g[0]}'")

    def ansi_color(self, g):
        # self.log(f"clr: {g}")
        params = []
        for c in g[0].split(";"):
            v = c.lstrip("0")
            if v == "":
                v = "0"
            params.append(int(v))
        self.set_color(params)

    def ansi_move_up(self, g):
        rows = 1
        if len(g) > 0:
            try:
                rows = int(g[0])
            except Exception:
                pass
        if rows < 1:  # is this an error? \x1b[-1A
            return
        self.row -= int(rows)
        if self.row < 0:
            self.row = 0
        self.log(f"mov: up {rows} rows to {self.row}")
        self.move_cursor(self.row, self.col)

    def ansi_move_down(self, g):
        rows = 1
        if len(g) > 0:
            try:
                rows = int(g[0])
            except Exception:
                pass
        self.row += int(rows)
        if self.row < 0:
            self.row = 0
        self.log(f"mov: down {rows} rows to {self.row}")
        self.move_cursor(self.row, self.col)

    def ansi_move_right(self, g):
        cols = 1
        if len(g) > 0:
            try:
                cols = int(g[0])
            except Exception:
                pass
        self.log(f"mov: right {cols} from {self.col}")
        self.col += cols
        self.move_cursor(self.row, self.col)

    def ansi_move_left(self, g):
        cols = 1
        if len(g) > 0:
            try:
                cols = int(g[0])
            except Exception:
                pass
        self.log(f"mov: left {cols} from {self.col}")
        self.col -= cols
        if self.col < 0:
            self.col = 0
        self.move_cursor(self.row, self.col)

    def insert_chars(self, g):
        num = 1
        if len(g) > 0:
            try:
                num = int(g[0])
            except Exception:
                pass
        self.log(f"ins: insert {num} chars at {self.col}")
        for c in range(self.cols - 1, self.col + num - 1, -1):
            ch = self.pad.inch(self.row, c - num)
            self.pad.addch(self.row, c, ch)
        self.pad.addstr(self.row, self.col, " " * num, self.get_color())

    def ansi_delete_chars(self, g):
        num = 1
        if len(g) > 0:
            try:
                num = int(g[0])
            except Exception:
                pass
        if self.col + num > self.cols:
            num = self.cols - self.col
        self.log(f"era: erase {num} chars from {self.col}")
        for c in range(self.col + num, self.cols):
            ch = self.pad.inch(self.row, c)
            self.pad.addch(self.row, c - num, ch)
        self.pad.addstr(self.row, self.col + num, " " * num, self.get_color())
        self.move_cursor(self.row, self.col)

    def ansi_move_row(self, g):
        row = g[0]
        self.row = int(row) - 1
        self.log(f"row: {self.row}")
        self.move_cursor(self.row, self.col)

    def ansi_position_col(self, g):
        col = 1
        if len(g) > 0:
            try:
                col = int(g[0])
            except Exception:
                pass
        self.col = int(col) - 1
        self.log(f"col: {self.col}")
        self.move_cursor(self.row, self.col)

    def ansi_insert_lines(self, g):
        if g[0] == "":
            count = 1
        else:
            count = int(g[0])

        self.log(f"ins: {count} lines")
        blank = " " * self.cols
        for _ in range(count):
            self.log("scroll down")
            self.pad.scrollok(True)
            self.pad.scroll(-1)
            self.pad.scrollok(False)
            try:
                self.pad.addstr(self.row, 0, blank, self.get_color())
            except Exception:
                self.log(f"err: {self.row} 0 ' ' * {self.cols}")

    def ansi_position(self, g):
        if len(g) > 1:
            row, col = g[0:2]
            self.row = int(row) - 1
            self.col = int(col) - 1
        elif len(g) == 1:
            col = g[0]
            self.col = int(col) - 1

        if self.row < 0:
            self.row = 0
        elif self.row >= self.rows:
            self.row = self.rows - 1
        # self.log(f"pos: {self.row} {self.col}")
        try:
            self.move_cursor(self.row, self.col)
        except Exception:
            self.log(f"err: move {self.row} {self.col}")

    def ansi_pos_home(self, g):
        self.row = 0
        self.col = 0
        # self.log(f"pos: {self.row} {self.col}")
        self.move_cursor(self.row, self.col)

    def ansi_erase_line(self, g):
        self.log(f"erase line {g}")
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
                length = self.cols - self.col
            start = self.col

        elif variant == "K":  # erase with different behavior
            if param == "" or int(param) == 0:  # erase from cursor to end of line
                length = self.cols - self.col
                start = self.col
            elif int(param) == 1:                 # erase start of line to the cursor
                length = self.col
                start = 0
            elif int(param) == 2:                 # erase the entire line
                length = self.cols
                start = 0

        blank = " " * length
        try:
            # FIXME: should not move cursor, just will text
            self.pad.addstr(self.row, start, blank, self.get_color())
            self.move_cursor(self.row, self.col)
        except Exception:
            self.log(f"err: {self.row} {start} ' ' * {length}")

    def ansi_erase(self, g):

        if len(g) > 0:
            param = 0
            try:
                param = int(g[0])
            except Exception:
                pass
            if param == 0:  # J / 0J: erase from cursor until end of screen
                self.log(f"erase: until end of screen")
                try:
                    self.pad.addstr(self.row, self.col, " " * (self.cols - self.col), self.get_color())
                except Exception:
                    pass
                self.row += 1
                blank = " " * self.cols
                for r in range(self.row, self.rows):
                    try:
                        self.pad.addstr(r, 0, blank, self.get_color())
                    except Exception:
                        self.log(f"err: {r} 0 ' ' * {self.cols}")

            elif param == 1:  # 1J: erase from cursor to beginning of screen
                self.log(f"todo: erase scrollback")

            elif param == 2:  # 2J: erase entire screen
                self.log(f"erase screen")
                self.row = 0
                self.col = 0
                self.move_cursor(self.row, self.col)
                blank = " " * self.cols
                for r in range(self.row, self.rows):
                    try:
                        self.pad.addstr(r, 0, blank, self.get_color())
                    except Exception:
                        self.log(f"err: {r} 0 ' ' * {self.cols}")

            elif param == 3:  # 3J: erase saved lines / scrollback
                self.log(f"todo: erase scrollback")

            else:
                self.log(f"todo: {g}")

        else:  # erase rest of line and screen
            blank = " " * (self.cols - self.col)
            try:
                self.pad.addstr(self.row, self.col, blank, self.get_color())
            except Exception:
                self.log(f"err: {self.row} {self.col} ' ' * {self.cols - self.col}")

            blank = " " * self.cols
            for r in range(self.row, self.rows - 1):
                try:
                    self.pad.addstr(r, 0, blank, self.get_color())
                except Exception:
                    self.log(f"err: {r} 0 ' ' * {self.cols}")

    def ansi_hide_cursor(self, *g):
        self.log("cur: hide")
        curses.curs_set(0)

    def ansi_show_cursor(self, *g):
        self.log("cur: show")
        curses.curs_set(1)

    def ansi_report(self, g):
        code = None
        if len(g) > 0:
            try:
                code = int(g[0])
            except Exception:
                pass

        if code == 6:  # get cursoe pos
            if self.shell_input:
                self.log(f"report: cursor at {self.row + 1} {self.col + 1}")
                self.shell_input(f"\x1b[{self.row + 1};{self.col + 1}R".encode())
        else:
            self.log(f"todo: report code {code}")

    def ansi_clear_screen(self, g):
        self.pad.clear()

    def ansi_set_margin(self, g):
        self.margin_top = int(g[0])
        self.margin_bottom = int(g[1])
        # FIXME: check negative
        try:
            self.pad.setscrreg(self.margin_top - 1, self.margin_bottom - 1)
        except Exception:
            pass
        self.row = self.margin_top
        self.col = 0
        self.move_cursor(self.row, self.col)
        self.log(f"scroll margin: {self.margin_top} {self.margin_bottom}")

    def ansi_scroll_up(self, g):
        rows = int(g[0])
        self.log(f"todo: scroll up: {rows}")

    def ansi_append_lines(self, g):
        count = int(g[0])
        # self.log(f"pos: append {count} lines")
        row_old = self.row
        col_old = self.col
        self.row = self.margin_bottom - 1
        self.col = 0
        self.move_cursor(self.row, self.col)
        for _ in range(count):
            self.linefeed()
        self.row = row_old
        self.col = col_old
        self.move_cursor(self.row, self.col)

    def ansi_keypad(self, g):
        keypad = g[0]
        if keypad == "=":
            self.log(f"todo: alternate keypad mode")
        elif keypad == ">":
            self.log(f"todo: numkeypad mode")

    def ansi_charset(self, g):
        self.log(f"todo: character set {g[0]}")
        # 0 = DEC Special Character and Line Drawing Set, VT100.
        if g[0] == "0":
            self.charset_lines = True
        else:
            self.charset_lines = False

    def csi_set_mode(self, g):
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

        if opt == 2:
            self.log(f"todo: Keyboard Action Mode (KAM) {val}")

        elif opt == 4:
            self.log(f"todo: Insert Mode (IRM) {val}")

        elif opt == 12:
            self.log(f"todo: Send/receive (SRM) {val}")

        elif opt == 20:
            self.log(f"todo: Automatic Newline (LNM) {val}")

        else:
            self.log(f"todo: set mode {opt} {val}")

    def dec_private_modes(self, g):
        # https://terminalguide.namepad.de/mode/
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
            self.log(f"todo: dec: Application Cursor Keys {val}")
            # https://documentation.help/PuTTY/config-appcursor.html
            if val:
                self.ansi_hide_cursor()
            else:
                self.ansi_show_cursor()

        elif opt == 4:
            self.log(f"todo: dec: insert mode {val}")

        elif opt == 7:
            self.log(f"todo: dec: autowrap {val}")

        elif opt == 12:
            self.dec_blinking_cursor = val

        elif opt == 25:
            if val:
                self.ansi_show_cursor()
            else:
                self.ansi_hide_cursor()

        elif opt == 1000:
            self.log(f"todo: dec: X11 mouse {val}")

        elif opt == 1006:  # Mouse Reporting Format Digits
            self.log(f"todo: dec: X11 mouse format digits {val}")

        elif opt == 1049:
            self.log(f"dec: Save cursor and switch to alternate buffer clearing it {val}")
            if val is True:
                self.savedcol = self.col
                self.savedrow = self.row
                self.savedbuffer = []
                for row in range(0, self.rows):
                    for col in range(0, self.cols):
                        c = self.pad.inch(row, col)
                        self.savedbuffer.append(c)
                self.ansi_erase([2])
            else:
                # FIXME: save buffer rows,cols in case of resize
                for r in range(0, self.rows):
                    for c in range(0, self.cols):
                        try:
                            ch = self.savedbuffer[r * self.cols + c]
                            self.pad.addch(r, c, ch)
                        except Exception as exc:
                            self.log(f"todo: {exc} {r} {c} {ch}")
                self.savedbuffer = []
                self.col = self.savedcol
                self.row = self.savedrow
                self.move_cursor(self.row, self.col)

        elif opt == 2004:
            self.log(f"todo: dec: Set bracketed paste mode {val}")
            self.dec_bracketed_paste_mode = val
            # https://cirw.in/blog/bracketed-paste

        else:
            self.log(f"todo: dec {opt} {val}")

    def esc_code(self, g):  # vt100 ?
        opt = g[0]
        try:
            opt = int(opt)
        except Exception:
            pass

        if opt == 7:
            self.log(f"vt100: save cursor")
            self.saved_row = self.row
            self.saved_col = self.col

        elif opt == 8:
            self.log(f"vt100: restore cursor")
            self.row = self.saved_row
            self.col = self.saved_col

        else:
            self.log(f"todo: vt100: {opt}")

    def xterm_set_window_title(self, g):
        # self.log(f"window title: {g[0]}")
        # self.p_out.write(f"\x1b]0;clash: {g[0]}\x07".encode())
        pass

    def ansi_secondary_device(self, g):
        self.log("todo: dec: set secondary device attributes")

    def addansi(self, row, col, line):
        # https://espterm.github.io/docs/VT100%20escape%20codes.html
        # https://man7.org/linux/man-pages/man4/console_codes.4.html
        # https://xtermjs.org/docs/api/vtfeatures/
        # https://invisible-island.net/xterm/ctlseqs/ctlseqs.html

        ansi = {
                r"\[([;\d]*)m": self.ansi_color,

                r"(\d)": self.esc_code,
                r"\[;?\?1c": self.ansi_hide_cursor,
                r"\[;?\?0c": self.ansi_show_cursor,
                r"(\)0)": self.ansi_unhandled,  # )0 Start / (0 Select VT100 graphics mapping
                r"\[;?(\d+);(\d+)r": self.ansi_set_margin,
                r"\[;?(\d+)n": self.ansi_report,
                r"\[;?(\d+)d": self.ansi_move_row,
                r"\[;?\?(\d+)([hl])": self.dec_private_modes,
                r"\[(\d+)([hl])": self.csi_set_mode,
                r"(\[;??1000l)": self.ansi_unhandled,  # X11 Mouse Reporting
                r"(\[;??2004h)": self.ansi_unhandled,
                r"(\[;?\?(\d);(\d)l)": self.ansi_unhandled,
                r"\[;?(\d*)A": self.ansi_move_up,
                r"\[;?(\d*)B": self.ansi_move_down,
                r"\[;?(\d*)C": self.ansi_move_right,
                r"\[;?(\d*)D": self.ansi_move_left,
                r"\[;?(\d*)G": self.ansi_position_col,
                r"\[;?(\d+);(\d+)H": self.ansi_position,
                r"\[;?(\d+)H": self.ansi_position,
                r"\[;?H": self.ansi_pos_home,
                r"\[;?(\d*)J": self.ansi_erase,
                r"\[;?(\d*)([XK])": self.ansi_erase_line,
                r"\[;?(\d*)L": self.ansi_insert_lines,
                r"\[;?(\d+)M": self.ansi_append_lines,
                r"\[;?(\d*)P": self.ansi_delete_chars,
                r"(\[;?(\d)S)": self.ansi_scroll_up,
                r"\[;?(\d+)T": self.ansi_unhandled,  # CSI Ps T  Scroll down Ps lines (default = 1) (SD), VT420.
                r"\[;?(\d+)@": self.insert_chars,  # CSI Ps @  Insert Ps (Blank) Character(s) (default = 1) (ICH).
                r"M": self.ansi_move_up,   # https://www.aivosto.com/articles/control-characters.html
                r"(c)": self.ansi_unhandled,  # Reset
                r"(\]R)": self.ansi_unhandled,  # Reset Palette
                r"\]0;([^\a]+)\a": self.xterm_set_window_title,
                r"(\[;?>c)": self.ansi_secondary_device,
                r"(\]1;([^\x07]+)\x07)": self.ansi_unhandled,  # set icon name
                r"(\]2;([^\x07]+)\x07)": self.ansi_unhandled,  # set window title
                r"(\]10;\?\x07)": self.ansi_unhandled,
                r"(\]11;\?\x07)": self.ansi_unhandled,
                r"(\]12;([^\x07]+)\x07)": self.ansi_unhandled,
                r"(\[;?2(\d);(\d)t)": self.ansi_unhandled,     # Window manipulation (XTWINOPS)
                r"(\[;?2(\d);(\d);(\d)t)": self.ansi_unhandled,
                r"(\[;?>(\d);(\d?)m)": self.ansi_unhandled,
                r"(=)": self.ansi_keypad,
                r"(>)": self.ansi_keypad,
                r"\((.)": self.ansi_charset,
                r"(\](\d+)\x07)": self.ansi_unhandled,
                r"(\[;?!p)": self.ansi_unhandled,
                r"(\(0)": self.ansi_unhandled,
        }

        if self.remainder:
            line = self.remainder + line
            self.remainder = ""

        while line:
            parts = line.split(b"\033", 1)
            if parts[0] != "":
                try:
                    self.puts(parts[0].decode(errors="replace"))
                except Exception:
                    self.log(f"err: puts {parts[0]}")
                    self.log(traceback.format_exc())

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
                    self.log(f"todo: error compiling {a}")
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
                    self.log(f"todo: unknown esc seq: {part}")
                    line = part

    def input(self, data):
        self.addansi(self.row, self.col, data)
        self.refresh()

    def move_cursor(self, row, col):
        if row >= self.rows or col >= self.cols:
            curses.curs_set(0)
        else:  # FIXME: if was enabled before
            curses.curs_set(1)

        try:
            self.pad.move(row, col)
        except Exception:
            pass

    def refresh(self):
        self.screen.refresh()
        h = self.height - 2
        w = self.width - 2
        if h > self.rows:
            h = self.rows - 1
        if w > self.cols:
            w = self.cols - 1
        try:
            self.pad.refresh(0, 0, 0, 0, h, w)
        except Exception as exc:
            self.log(f"todo: err: pad.refresh")
            self.log(exc)

    def resize(self, full=False, inner=True, rows=None, cols=None):
        if full:
            height, width, _, _ = unpack('HHHH', ioctl(0, TIOCGWINSZ, pack('HHHH', 0, 0, 0, 0)))
            self.log(f"resize: screen {width}x{height}")
            self.height = height
            self.width = width
            curses.resize_term(self.height, self.width)
            if inner:
                self.cols = self.width - 1
                self.rows = self.height - 1
        elif rows is None or cols is None:
            return
        else:
            self.cols = cols
            self.rows = rows

        if inner:
            self.pad.resize(self.rows, self.cols)

        self.screen.clear()
        self.update_border()
        self.refresh()
        return self.width, self.height

    def dump(self):
        msg = {"rows": self.rows,
               "cols": self.cols,
               "col": self.col,
               "row": self.row,
               "color_fg": self.color_fg,
               "color_bg": self.color_bg,
               "color_flags": self.flags,
               "dump": [],
               "colors": self.colors}
        for row in range(0, self.rows):
            for col in range(0, self.cols):
                c = self.pad.inch(row, col)
                msg["dump"].append(c)
        return msg

    def restore(self, scrinit):
        for clr in scrinit["colors"]:
            c = int(clr)
            fg = c % 256
            bg = (c - fg) // 256
            curses.init_pair(scrinit["colors"][clr] + 1, fg, bg)

        for r in range(0, scrinit['rows']):
            for c in range(0, scrinit['cols']):
                ch = scrinit['dump'][r * scrinit['cols'] + c]
                try:
                    self.pad.addch(r, c, ch)
                except Exception as exc:
                    self.log(f"todo: {exc} {r} {c} {ch}")

        self.color_fg = scrinit['color_fg']
        self.color_bg = scrinit['color_bg']
        self.color_flags = scrinit['color_flags']
        self.col = scrinit['col']
        self.row = scrinit['row']
        self.log(f"mov: {self.row}, {self.col}")
        self.move_cursor(self.row, self.col)
        self.refresh()

    def set_title(self, title):
        self.title = title
        self.update_border()
        self.refresh()
