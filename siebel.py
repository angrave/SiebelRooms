#!/usr/bin/env python3
"""
Shared core for the Siebel room scheduler: auth, room list (with Type),
and concurrent Microsoft Graph free/busy lookups. No EWS; Graph only.

Used by app.py (web) and findroom.py (CLI).

Credentials live in ./.env  (USER=<service-account email>, PASS=<password>).
Room list + types live in ./allrooms.txt  (Name - address - Type).
"""
import os, json, time, threading, urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

GRAPH = "https://graph.microsoft.com"
PUBLIC_CLIENT = "d3590ed6-52b3-4102-aeff-aad2292ab01c"  # Microsoft Office public client
SLOT_MIN = 30                       # availabilityView granularity (minutes)
TIMEZONE = "America/Chicago"
TZ_LABEL = "America/Chicago (Central)"
HERE = os.path.dirname(os.path.abspath(__file__))

STATUS = {"0": "free", "1": "tentative", "2": "busy",
          "3": "out-of-office", "4": "elsewhere"}


# ----------------------------------------------------------------------------- env
def load_env(path=None):
    env = {}
    path = path or os.path.join(HERE, ".env")
    if not os.path.exists(path):
        return env
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

# Credentials are optional at import time (so pure-logic code and tests can run
# without them); a network call raises a clear error if they're missing.
_ENV = load_env()
USER = _ENV.get("USER") or os.environ.get("USER_UPN")
PASS = _ENV.get("PASS") or os.environ.get("PASS")
TENANT = USER.split("@")[-1] if USER and "@" in USER else None


# ----------------------------------------------------------------------------- rooms
def load_rooms(path=None):
    """Read allrooms.txt -> [{name, address, type}]. Format per line:
       `Name - address@domain - Type`  (Type optional, default Unknown)."""
    path = path or os.path.join(HERE, "allrooms.txt")
    rooms = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = [p.strip() for p in line.split(" - ")]
            if len(parts) < 2:
                continue
            name, addr = parts[0], parts[1]
            rtype = parts[2] if len(parts) >= 3 and parts[2] else "Unknown"
            if addr:
                rooms.append({"name": name, "address": addr, "type": rtype})
    rooms.sort(key=lambda r: r["name"])
    return rooms


# ----------------------------------------------------------------------------- graph
def _http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        return urllib.request.urlopen(req, timeout=30).read()
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %d: %s" % (e.code, e.read().decode("utf-8", "replace")[:400]))


class _Token:
    """Cached ROPC access token, refreshed a minute before expiry."""
    def __init__(self):
        self._lock = threading.Lock()
        self._value = None
        self._exp = 0

    def get(self):
        with self._lock:
            if self._value and time.time() < self._exp - 60:
                return self._value
            if not (USER and PASS and TENANT):
                raise RuntimeError(
                    "Missing credentials: create a .env with USER and PASS "
                    "(see .env.example).")
            form = urllib.parse.urlencode({
                "client_id": PUBLIC_CLIENT,
                "scope": GRAPH + "/.default",
                "grant_type": "password",
                "username": USER,
                "password": PASS,
            }).encode()
            tok = json.loads(_http(
                "https://login.microsoftonline.com/%s/oauth2/v2.0/token" % TENANT,
                form, {"Content-Type": "application/x-www-form-urlencoded"}))
            self._value = tok["access_token"]
            self._exp = time.time() + int(tok.get("expires_in", 3600))
            return self._value

TOKEN = _Token()


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def get_schedules(addresses, day):
    """availabilityView for the whole `day` (00:00-24:00 CT) for every address.
    getSchedule accepts <=20 schedules/call; chunks fan out concurrently."""
    start = "%sT00:00:00" % day
    end = "%sT00:00:00" % (datetime.strptime(day, "%Y-%m-%d").date() + timedelta(days=1))

    def fetch(chunk):
        body = {
            "schedules": chunk,
            "startTime": {"dateTime": start, "timeZone": TIMEZONE},
            "endTime": {"dateTime": end, "timeZone": TIMEZONE},
            "availabilityViewInterval": SLOT_MIN,
        }
        res = _http(GRAPH + "/v1.0/me/calendar/getSchedule",
                    json.dumps(body).encode(),
                    {"Authorization": "Bearer " + TOKEN.get(),
                     "Content-Type": "application/json"})
        return json.loads(res).get("value", [])

    out = {}
    groups = list(_chunks(addresses, 20))
    if not groups:
        return out
    with ThreadPoolExecutor(max_workers=len(groups)) as ex:
        for res in ex.map(fetch, groups):
            for item in res:
                out[item.get("scheduleId")] = item
    return out


# ----------------------------------------------------------------------------- slots
def _to_min(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _fmt_slot(idx):
    total = idx * SLOT_MIN
    return "%02d:%02d" % (total // 60, total % 60)


def fmt12(hhmm):
    h, m = map(int, hhmm.split(":"))
    ap = "AM" if h < 12 else "PM"
    return "%d:%02d %s" % (h % 12 or 12, m, ap)


def window_free(av_view, start_hhmm, end_hhmm):
    """True if every 30-min slot overlapping [start, end) is free ('0')."""
    if not av_view:
        return True
    a = _to_min(start_hhmm) // SLOT_MIN
    b = -(-_to_min(end_hhmm) // SLOT_MIN)          # ceil end to slot boundary
    a = max(0, min(a, len(av_view)))
    b = max(a, min(b, len(av_view)))
    return all(c == "0" for c in av_view[a:b])


def busy_blocks(av_view):
    """Collapse availabilityView into human busy intervals for display."""
    blocks, i, n = [], 0, len(av_view or "")
    while i < n:
        c = av_view[i]
        if c == "0":
            i += 1
            continue
        j = i
        while j < n and av_view[j] == c:
            j += 1
        blocks.append({"start": _fmt_slot(i), "end": _fmt_slot(j),
                       "status": STATUS.get(c, "busy")})
        i = j
    return blocks


def query(day, start, end, type_filter=None):
    """High-level: return room records with free/busy for the given window.
    type_filter: None/'All' = every room; else keep only that Type."""
    rooms = load_rooms()
    if type_filter and type_filter.lower() != "all":
        rooms = [r for r in rooms if r["type"].lower() == type_filter.lower()]
    addrs = [r["address"] for r in rooms]
    sched = get_schedules(addrs, day)
    out = []
    for r in rooms:
        av = sched.get(r["address"], {}).get("availabilityView", "")
        out.append({
            "name": r["name"], "address": r["address"], "type": r["type"],
            "free": window_free(av, start, end), "busy": busy_blocks(av),
        })
    return out
