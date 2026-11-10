#!/usr/bin/env python3
"""
findroom — find a free Siebel room for a date + time window, from the terminal.

Most people just want: "what conference room is open at 9-10 tomorrow?"
So it defaults to Conference rooms and shows the free ones first.

Examples:
  python3 findroom.py                         # conf rooms free now-ish today
  python3 findroom.py 14:00 15:00             # today 2-3pm
  python3 findroom.py --date 2026-11-12 9 10  # specific date, 9-10am
  python3 findroom.py --type Class 13 14      # classrooms instead
  python3 findroom.py --all --free-only       # every room, only the free ones
  python3 findroom.py --json                  # machine-readable

Times accept HH, HH:MM, or H:MM (24-hour). All times are Central.
"""
import sys, json, argparse
from datetime import datetime
import siebel


def norm_time(s):
    if ":" not in s:
        s = s + ":00"
    h, m = s.split(":")
    return "%02d:%02d" % (int(h), int(m))


def today_ct():
    # The service tenant is Central; use local wall date (good enough for CLI).
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Find a free Siebel room for a date and time window (Central time).")
    p.add_argument("start", nargs="?", default="09:00", help="start time, e.g. 9 or 09:00")
    p.add_argument("end", nargs="?", default="10:00", help="end time, e.g. 10 or 10:00")
    p.add_argument("--date", default=today_ct(), help="YYYY-MM-DD (default: today)")
    p.add_argument("--type", default="Conference",
                   help="room type filter: Conference (default), Class, Research, Admin, Unknown, or All")
    p.add_argument("--all", action="store_true", help="shortcut for --type All")
    p.add_argument("--free-only", action="store_true", help="show only rooms free for the window")
    p.add_argument("--json", action="store_true", help="output JSON")
    args = p.parse_args(argv)

    start, end = norm_time(args.start), norm_time(args.end)
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        p.error("bad --date %r (use YYYY-MM-DD)" % args.date)
    tfilter = "All" if args.all else args.type

    try:
        rooms = siebel.query(args.date, start, end, tfilter)
    except Exception as e:
        print("Error: %s" % e, file=sys.stderr)
        return 2

    # free first, then by name
    rooms.sort(key=lambda r: (not r["free"], r["name"]))
    if args.free_only:
        rooms = [r for r in rooms if r["free"]]

    if args.json:
        print(json.dumps({"date": args.date, "start": start, "end": end,
                          "timezone": siebel.TZ_LABEL, "type": tfilter,
                          "rooms": rooms}, indent=2))
        return 0

    free = [r for r in rooms if r["free"]]
    scope = "all rooms" if tfilter.lower() == "all" else "%s rooms" % tfilter
    print("Siebel %s — %s  %s-%s  (%s)" % (
        scope, args.date, siebel.fmt12(start), siebel.fmt12(end), siebel.TZ_LABEL))
    print("%d free of %d\n" % (len(free), len(rooms)))

    GREEN, RED, DIM, RST = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
    if not sys.stdout.isatty():
        GREEN = RED = DIM = RST = ""

    for r in rooms:
        mark = GREEN + "FREE" + RST if r["free"] else RED + "busy" + RST
        print("  %s  %-26s %-11s %s" % (mark, r["name"], "[" + r["type"] + "]", r["address"]))
        if not r["free"] and r["busy"]:
            bits = ", ".join("%s %s-%s" % (b["status"], siebel.fmt12(b["start"]),
                                           siebel.fmt12(b["end"])) for b in r["busy"])
            print("        %s%s%s" % (DIM, bits, RST))
    return 0


if __name__ == "__main__":
    sys.exit(main())
