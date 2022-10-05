todo: =
    altkeypad             Enter alternate keypad mode            ^[=

todo: >
    numkeypad             Exit alternate keypad mode             ^[>

todo: (0
    setspecg0             Set G0 special chars. & line set       ^[(0

todo: ]10;?
    ESC ] 10 ; txt ST       Set dynamic text color to txt.

todo: [?3;4l
    DECRST	DEC Private Reset Mode	CSI ? Pm l	Reset various terminal attributes
    3	132 Column Mode (DECCOLM).
    ?? 4	Replace Mode (IRM). (default)

todo: ['[3J', '3']
    DECSED	Selective Erase In Display	CSI ? Ps J	Currently the same as ED.

todo: [4l
     ESC [ 4 h DECIM (default off): Set insert mode.

todo: [1P
todo: [2P
todo: [4P
    DCH	Delete Character	CSI Ps P	Delete Ps characters (default=1)

todo: [5S
    SU	Scroll Up	CSI Ps S	Scroll Ps lines up (default=1).

todo: (B
    setusg0               Set United States G0 character set     ^[(B

todo: [>c
    DA2	Secondary Device Attributes

todo: dec 2004
    DECSET	DEC Private Set Mode	CSI ? Pm h	Set various terminal attributes
    2004	Set bracketed paste mode.

todo: dec 7
    Auto-wrap Mode (DECAWM).

todo: dec 1
    Application Cursor Keys (DECCKM).

todo: ['[J', '']
    ED	Erase In Display	CSI Ps J	Erase various parts of the viewport.
    0	Erase from the cursor through the end of the viewport.
    1	Erase from the beginning of the viewport through the cursor.
    2	Erase complete viewport.
    3	Erase scrollback.

todo: [!p
    DECSTR	Soft Terminal Reset	CSI ! p	Reset several terminal attributes to initial state

todo: ]104
todo: ]11;?
todo: [22;0;0t
todo: [22;1t
todo: [22;2t
todo: [23;0;0t
todo: [23;1t
todo: [23;2t
todo: [>4;m
todo: [>4;2m
todo: ]10;?
todo: [6@
todo: [2@


vim: search, history up
put: 31x21:  clash/terminal.py
chr: CR
chr: LF
pos: scroll up
clr: ['']
clr: ['38;5;245']
clr: #8: 245 -1 0
put: 31x0: /qwe


vim: scroll down over flake8 err

pty: b'\x1b[?25l\x1b[2;33r\x1b[m\x1b[38;5;245m\x1b[33;1H\r\n\x1b[1;35r\x1b[33;1H\x1b[38;5;245m\x1b[48;5;242m  \x1b[m\x1b[38;5;245m\x1b[38;5;240m\x1b[48;5;235m 92 \x1b[m\x1b[38;5;245m\x1b[8C\x1b[38;5;64mif\x1b[m\x1b[38;5;245m self.col + length > self.cols:\x1b[34;128H\x1b[1m\x1b[38;5;230m\x1b[48;5;245m2/\x1b[33;19H\x1b[?25h'
cur: hide
scroll margin: 1 32
pos: 32 0
chr: CR 32
chr: LF
pos: scroll up
scroll margin: 0 34
pos: 32 0
mov: right 8 from 6
pos: 33 127
pos: 32 18
cur: show

pty: b'\x1b[?25l\x1b[2;33r\x1b[m\x1b[38;5;245m\x1b[33;1H\r\n\x1b[1;35r\x1b[33;1H\x1b[1m\x1b[38;5;124m>>\x1b[m\x1b[38;5;245m\x1b[38;5;240m\x1b[48;5;235m 93 \x1b[m\x1b[38;5;245m\x1b[12Cself.log(f\x1b[38;5;37m"err: truncating {length} to {self.cols - self.col - 1} rest: {bytes(text[self.cols - self.col - 1:].encode(\x1b[m\x1b[38;5;245m\x1b]12;%p1%s\x07\x1b[38;5;37m)\x1b[m\x1b[38;5;245m\x1b[38;5;37m)}"\x1b[m\x1b[38;5;245m)\x1b[34;128H\x1b[1m\x1b[38;5;230m\x1b[48;5;245m3/\x1b[33;19H\x1b[?25h'
cur: hide
scroll margin: 1 32
pos: 32 0
chr: CR 32
chr: LF
pos: scroll up
scroll margin: 0 34
pos: 32 0
mov: right 12 from 6
todo: esc seq '\x1b]12;%p1%s'
pos: 33 127
pos: 32 18
cur: show
pty: b'\x1b[?25l\r\n\r\n\x1b[m\x1b[38;5;245m:\x1b[?2004hechomsg a:message\r[flake8] line too long (135 > 130 characters) [E]\x1b[33;19H\x1b[?25h'
cur: hide
chr: CR 32
chr: LF
chr: CR 33
chr: LF
pos: scroll up
todo: dec: Set bracketed paste mode True
chr: CR 33
pos: 32 18
cur: show



