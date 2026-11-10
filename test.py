#!/usr/bin/env python3
"""
Offline tests for SiebelRooms pure logic.

No network, no credentials: these exercise slot math, free/busy window
detection, availability-block collapsing, and allrooms.txt parsing.

Run:  python3 test.py          (exit 0 = all passed)
"""
import os, sys, tempfile
import siebel

_fail = 0


def check(name, got, want):
    global _fail
    ok = got == want
    print("%s %s" % ("ok  " if ok else "FAIL", name))
    if not ok:
        _fail += 1
        print("      got:  %r" % (got,))
        print("      want: %r" % (want,))


def section(t):
    print("\n== %s ==" % t)


# --- time / slot helpers -----------------------------------------------------
section("fmt12")
check("midnight", siebel.fmt12("00:00"), "12:00 AM")
check("noon", siebel.fmt12("12:00"), "12:00 PM")
check("9am", siebel.fmt12("09:00"), "9:00 AM")
check("1:30pm", siebel.fmt12("13:30"), "1:30 PM")

# --- window_free -------------------------------------------------------------
# availabilityView: one char per 30 min from 00:00; '0'=free, '2'=busy, etc.
# 48 slots in a day. Build one that's busy only 09:00-10:00 (slots 18,19).
section("window_free")
av = ["0"] * 48
av[18] = av[19] = "2"            # 09:00-10:00 busy
av = "".join(av)

check("free before busy (08:00-09:00)", siebel.window_free(av, "08:00", "09:00"), True)
check("busy exact (09:00-10:00)", siebel.window_free(av, "09:00", "10:00"), False)
check("busy overlap start (08:30-09:30)", siebel.window_free(av, "08:30", "09:30"), False)
check("busy overlap end (09:30-10:30)", siebel.window_free(av, "09:30", "10:30"), False)
check("free after busy (10:00-11:00)", siebel.window_free(av, "10:00", "11:00"), True)
check("empty view = free", siebel.window_free("", "09:00", "10:00"), True)
check("non-30 window ceils to slot (09:15-09:45 busy)",
      siebel.window_free(av, "09:15", "09:45"), False)

# all-free day
check("all-free day", siebel.window_free("0" * 48, "13:00", "17:00"), True)

# --- busy_blocks -------------------------------------------------------------
section("busy_blocks")
blocks = siebel.busy_blocks(av)
check("one block found", len(blocks), 1)
check("block start", blocks[0]["start"], "09:00")
check("block end", blocks[0]["end"], "10:00")
check("block status", blocks[0]["status"], "busy")
check("no blocks when all free", siebel.busy_blocks("0" * 48), [])

# tentative + out-of-office distinct, adjacent different statuses stay separate
av2 = "0" * 48
av2 = av2[:4] + "1" + "3" + av2[6:]   # 02:00 tentative, 02:30 out-of-office
blocks2 = siebel.busy_blocks(av2)
check("adjacent differing statuses -> 2 blocks", len(blocks2), 2)
check("tentative mapped", blocks2[0]["status"], "tentative")
check("oof mapped", blocks2[1]["status"], "out-of-office")

# --- allrooms.txt parsing ----------------------------------------------------
section("load_rooms (real allrooms.txt)")
rooms = siebel.load_rooms()
check("33 rooms", len(rooms), 33)
types = {}
for r in rooms:
    types[r["type"]] = types.get(r["type"], 0) + 1
check("12 conference", types.get("Conference"), 12)
check("12 class", types.get("Class"), 12)
check("9 unknown", types.get("Unknown"), 9)
check("every room has an @ address", all("@" in r["address"] for r in rooms), True)
check("sorted by name", [r["name"] for r in rooms], sorted(r["name"] for r in rooms))
has_4124 = any(r["address"].startswith("siebel-4124@") and r["type"] == "Conference"
               for r in rooms)
check("4124 present & Conference", has_4124, True)

# --- load_rooms parsing edge cases (synthetic file) --------------------------
section("load_rooms (parsing rules)")
tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
tmp.write("# a comment\n")
tmp.write("\n")
tmp.write("Room A - a@x.edu - Conference\n")
tmp.write("Room B - b@x.edu\n")                 # no type -> Unknown
tmp.write("Room C - c@x.edu - Research\n")
tmp.close()
try:
    rs = siebel.load_rooms(tmp.path if hasattr(tmp, "path") else tmp.name)
finally:
    pass
check("skips comments/blanks -> 3 rooms", len(rs), 3)
by = {r["name"]: r for r in rs}
check("explicit type kept", by["Room A"]["type"], "Conference")
check("missing type defaults Unknown", by["Room B"]["type"], "Unknown")
check("research type kept", by["Room C"]["type"], "Research")
os.unlink(tmp.name)

# --- credentials optional at import ------------------------------------------
section("no-credential safety")
check("module imported without network", hasattr(siebel, "query"), True)

# -----------------------------------------------------------------------------
print()
if _fail:
    print("%d test(s) FAILED" % _fail)
    sys.exit(1)
print("all tests passed")
