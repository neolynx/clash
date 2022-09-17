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

todo: c
    ?? cursorrt              Move cursor right one char             ^[C

todo: dec 2004
    DECSET	DEC Private Set Mode	CSI ? Pm h	Set various terminal attributes
    2004	Set bracketed paste mode.

todo: dec 1049
    1049	Save cursor and switch to alternate buffer clearing it.

todo: dec 7
    Auto-wrap Mode (DECAWM).

todo: dec 12
    Start Blinking Cursor.

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
todo: [>c
