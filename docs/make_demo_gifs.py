#!/usr/bin/env python3
"""
Generate the README demo GIFs:  docs/cli.gif  and  docs/web.gif

These are *illustrations* of the tools (a typed terminal session and a mock of
the web UI) rendered with Pillow — no network, no credentials, no real booking
data. Re-run after a UI change:

    pip install Pillow
    python3 docs/make_demo_gifs.py

Fonts are looked up by path with fallbacks; tuned for macOS (Menlo / SF).
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

MONO_CANDIDATES = ["/System/Library/Fonts/Menlo.ttc",
                   "/System/Library/Fonts/Monaco.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
SANS_CANDIDATES = ["/System/Library/Fonts/HelveticaNeue.ttc",
                   "/System/Library/Fonts/Supplemental/Arial.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
SANSB_CANDIDATES = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                    "/System/Library/Fonts/HelveticaNeue.ttc",
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]


def _font(cands, size):
    for p in cands:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


MONO = _font(MONO_CANDIDATES, 20)
SANS = _font(SANS_CANDIDATES, 20)
SANS_S = _font(SANS_CANDIDATES, 16)
SANS_B = _font(SANSB_CANDIDATES, 20)
SANS_BS = _font(SANSB_CANDIDATES, 15)


def save_gif(path, frames, default_ms=90):
    """frames: list of (RGB Image, duration_ms)."""
    imgs = [f[0].convert("P", palette=Image.ADAPTIVE, colors=128) for f in frames]
    durs = [f[1] for f in frames]
    imgs[0].save(path, save_all=True, append_images=imgs[1:],
                 duration=durs, loop=0, disposal=2, optimize=True)
    kb = os.path.getsize(path) // 1024
    print("wrote %s  (%d frames, %d KB)" % (path, len(frames), kb))


# =========================================================================== CLI
TBG = (30, 33, 39)          # terminal background
TFG = (216, 222, 233)       # default text
BLUE = (122, 162, 247)      # prompt
WHITE = (240, 243, 245)     # typed command
GREEN = (158, 206, 106)
RED = (247, 118, 142)
DIM = (120, 130, 148)
CYAN = (125, 207, 255)
MUT = (138, 148, 166)

T_W, T_H = 960, 600
T_PAD = 26
T_TOP = 56                  # below window chrome
LH = 26                     # line height
CW = MONO.getlength("M")    # mono char width


def term_base():
    img = Image.new("RGB", (T_W, T_H), (18, 20, 24))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, T_W - 6, T_H - 6], radius=12, fill=TBG)
    # window chrome
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([22 + i * 22, 20, 36 + i * 22, 34], fill=c)
    d.text((T_W / 2, 27), "findroom — zsh", font=SANS_S, fill=(150, 158, 170), anchor="mm")
    d.line([6, 46, T_W - 6, 46], fill=(44, 48, 56))
    return img


def draw_lines(lines, typing=None, cursor=True):
    """lines: list of list-of-(text,color). typing: (segments, show_cursor)."""
    img = term_base()
    d = ImageDraw.Draw(img)
    y = T_TOP
    allrows = list(lines)
    if typing is not None:
        allrows.append(typing)
    for row in allrows:
        x = T_PAD
        for text, color in row:
            d.text((x, y), text, font=MONO, fill=color)
            x += MONO.getlength(text)
        y += LH
    if cursor and typing is not None:
        # block cursor at end of typing line
        x = T_PAD + sum(MONO.getlength(t) for t, _ in typing)
        yy = T_TOP + (len(allrows) - 1) * LH
        d.rectangle([x + 1, yy + 2, x + 1 + CW, yy + 20], fill=(200, 208, 220))
    return img


def cli_frames():
    frames = []
    committed = []     # list of rows

    def emit(img, ms):
        frames.append((img, ms))

    def type_cmd(cmd, step=2, ms=45):
        # typewriter: prompt + growing command
        for i in range(0, len(cmd) + 1, step):
            typing = [("$ ", BLUE), (cmd[:i], WHITE)]
            emit(draw_lines(committed, typing), ms)
        # commit the command line (freeze cursor off)
        committed.append([("$ ", BLUE), (cmd, WHITE)])
        emit(draw_lines(committed, None, cursor=False), 260)

    def out(row, ms=70):
        committed.append(row)
        emit(draw_lines(committed, None, cursor=False), ms)

    def blank(ms=40):
        committed.append([("", TFG)])
        emit(draw_lines(committed, None, cursor=False), ms)

    # ---- scene 1: login ----
    type_cmd("python3 siebel.py login")
    out([("", TFG)], 20)
    out([("To sign in, open:  ", TFG), ("https://login.microsoft.com/device", CYAN)], 120)
    out([("Enter code:        ", TFG), ("D4XC7HK9P", WHITE)], 120)
    out([("Waiting for sign-in…", DIM)], 700)
    out([("Signed in. Token cached in ", GREEN), (".token.json", WHITE)], 500)
    blank()

    # ---- scene 2: search ----
    type_cmd("python3 findroom.py 9 10")
    out([("Siebel Conference rooms — 2026-11-12  9:00-10:00 AM  (Central)", TFG)], 120)
    out([("8 free of 12", MUT)], 260)
    blank(20)

    def room(mark, mcol, name, addr):
        return [("  ", TFG), (mark, mcol), ("  " + name.ljust(24), TFG),
                ("[Conference] ", DIM), (addr, MUT)]

    frees = [("Siebel Center 2102", "siebel-2102@mx.uillinois.edu"),
             ("Siebel Center 2405", "siebel-2405@mx.uillinois.edu"),
             ("Siebel Center 3102", "siebel-3102@mx.uillinois.edu"),
             ("Siebel Center 3124", "siebel-3124@mx.uillinois.edu"),
             ("Siebel Center 4124", "siebel-4124@mx.uillinois.edu")]
    for nm, ad in frees:
        out(room("FREE", GREEN, nm, ad), 95)
    # a busy one with detail
    out(room("busy", RED, "Siebel Center 2124", "siebel-2124@mx.uillinois.edu"), 95)
    out([("        ", TFG), ("busy 8:00 AM-10:00 AM, busy 10:30 AM-12:00 PM, busy 2:00 PM-5:00 PM", DIM)], 95)
    out(room("busy", RED, "Siebel Center 4102", "siebel-4102@mx.uillinois.edu"), 95)
    out([("        ", TFG), ("busy 9:30 AM-10:00 AM, busy 11:00 AM-12:30 PM", DIM)], 120)

    # hold on final frame
    emit(draw_lines(committed, None, cursor=False), 2600)
    return frames


# =========================================================================== WEB
NAVY = (19, 41, 75)
LINE = (217, 220, 225)
INK = (26, 29, 34)
FREEBG = (230, 247, 238)
FREEFG = (22, 121, 75)
BUSYFG = (180, 35, 44)
CHIP = (238, 241, 245)

W_W, W_H = 1000, 640


def web_base():
    img = Image.new("RGB", (W_W, W_H), (225, 227, 231))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, W_W - 6, W_H - 6], radius=12, fill=(246, 247, 249))
    # browser chrome
    d.rounded_rectangle([6, 6, W_W - 6, 52], radius=12, fill=(237, 239, 242))
    d.rectangle([6, 30, W_W - 6, 52], fill=(237, 239, 242))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([22 + i * 22, 22, 36 + i * 22, 36], fill=c)
    d.rounded_rectangle([96, 16, W_W - 20, 42], radius=13, fill=(255, 255, 255), outline=(214, 217, 222))
    d.text((112, 29), "localhost:8765", font=SANS_S, fill=(110, 118, 130), anchor="lm")
    # app header
    d.rectangle([6, 52, W_W - 6, 104], fill=NAVY)
    d.text((26, 63), "Siebel Center — Room Scheduler", font=SANS_B, fill=(255, 255, 255))
    d.text((26, 85), "All times shown in America/Chicago (Central)", font=SANS_S, fill=(190, 200, 215))
    return img


def web_toolbar(d, type_val="Conference"):
    y = 118
    def field(x, w, label, val, bold=False):
        d.text((x, y), label.upper(), font=SANS_S, fill=(120, 128, 140))
        d.rounded_rectangle([x, y + 18, x + w, y + 46], radius=7, fill=(255, 255, 255), outline=LINE)
        d.text((x + 10, y + 32), val, font=SANS_BS if bold else SANS_S,
               fill=INK, anchor="lm")
    field(26, 150, "Date", "2026-11-12")
    field(190, 90, "Start", "09:00")
    field(292, 90, "End", "10:00")
    field(394, 150, "Type", type_val, bold=True)
    # dropdown caret (drawn, since the font lacks the glyph)
    d.polygon([(528, y + 28), (540, y + 28), (534, y + 36)], fill=(90, 98, 112))
    # Find button
    d.rounded_rectangle([556, 136, 636, 164], radius=7, fill=NAVY)
    d.text((596, 150), "Find", font=SANS_BS, fill=(255, 255, 255), anchor="mm")
    # nav buttons
    nx = 664
    for lab in ["« Wk", "‹ Day", "Today", "Day ›", "Wk »"]:
        w = SANS_S.getlength(lab) + 20
        d.rounded_rectangle([nx, 136, nx + w, 164], radius=7, fill=(255, 255, 255), outline=LINE)
        d.text((nx + w / 2, 150), lab, font=SANS_S, fill=(55, 65, 81), anchor="mm")
        nx += w + 8


# table rows: (status_free, room, bookings)
ROWS = [
    (True, "Siebel Center 2102", "No bookings all day"),
    (True, "Siebel Center 2405", "No bookings all day"),
    (True, "Siebel Center 3102", "busy 1:00 PM-2:00 PM"),
    (True, "Siebel Center 4124", "busy 12:00 PM-3:00 PM"),
    (False, "Siebel Center 2124", "busy 8:00 AM-10:00 AM, 2:00 PM-5:00 PM"),
    (False, "Siebel Center 4102", "busy 9:30 AM-10:00 AM, 11:00 AM-12:30 PM"),
]
COLS = [(26, "STATUS"), (150, "ROOM"), (420, "TYPE"), (560, "BOOKINGS (THIS DAY)")]
TY0 = 196
TRH = 58


def web_table(d, n_rows, count_text):
    d.text((26, 176), count_text, font=SANS_S, fill=(107, 114, 128))
    # table card
    bottom = TY0 + 40 + max(n_rows, 1) * TRH
    d.rounded_rectangle([26, TY0, W_W - 26, bottom], radius=10, fill=(255, 255, 255), outline=LINE)
    # header
    d.rectangle([27, TY0 + 1, W_W - 27, TY0 + 40], fill=(240, 242, 245))
    for x, lab in COLS:
        d.text((x + 12, TY0 + 20), lab, font=SANS_S, fill=(120, 128, 140), anchor="lm")
    y = TY0 + 40
    for i in range(n_rows):
        free, room, book = ROWS[i]
        if free:
            d.rectangle([27, y, W_W - 27, y + TRH], fill=FREEBG)
        d.line([27, y + TRH, W_W - 27, y + TRH], fill=(237, 239, 242))
        # status tag
        tag = "FREE" if free else "busy"
        tcol = FREEFG if free else BUSYFG
        tbg = FREEBG if free else (253, 232, 233)
        tw = SANS_BS.getlength(tag) + 18
        d.rounded_rectangle([38, y + TRH/2 - 13, 38 + tw, y + TRH/2 + 13], radius=12, fill=tbg)
        d.text((38 + tw/2, y + TRH/2), tag, font=SANS_BS, fill=tcol, anchor="mm")
        # room
        d.text((162, y + TRH/2), room, font=SANS, fill=INK, anchor="lm")
        # type chip
        d.rounded_rectangle([432, y + TRH/2 - 13, 432 + 92, y + TRH/2 + 13], radius=6, fill=CHIP)
        d.text((432 + 46, y + TRH/2), "Conference", font=SANS_S, fill=(55, 65, 81), anchor="mm")
        # bookings
        bcol = FREEFG if (free and book.startswith("No")) else (55, 65, 81)
        d.text((572, y + TRH/2), book, font=SANS_S, fill=bcol, anchor="lm")
        y += TRH


def web_frames():
    frames = []
    # 1) empty app with toolbar, "Loading…"
    img = web_base(); d = ImageDraw.Draw(img)
    web_toolbar(d); d.text((26, 176), "Loading…", font=SANS_S, fill=(107, 114, 128))
    frames.append((img, 700))
    # 2) rows reveal one by one
    free_total = sum(1 for r in ROWS if r[0])
    for n in range(1, len(ROWS) + 1):
        img = web_base(); d = ImageDraw.Draw(img)
        web_toolbar(d)
        shown_free = sum(1 for r in ROWS[:n] if r[0])
        count = "%d of 12 Conference rooms free for 9:00 AM–10:00 AM · America/Chicago (Central)" % free_total
        web_table(d, n, count)
        frames.append((img, 360))
    # 3) hold
    img = web_base(); d = ImageDraw.Draw(img)
    web_toolbar(d)
    web_table(d, len(ROWS),
              "%d of 12 Conference rooms free for 9:00 AM–10:00 AM · America/Chicago (Central)" % free_total)
    frames.append((img, 3000))
    return frames


if __name__ == "__main__":
    save_gif(os.path.join(HERE, "cli.gif"), cli_frames())
    save_gif(os.path.join(HERE, "web.gif"), web_frames())
