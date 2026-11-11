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
# Two public clients, because first-party clients can't freely request Graph
# delegated scopes in every flow:
#   ROPC  -> Microsoft Office client (works with grant_type=password + .default)
#   device-> Microsoft Graph Command Line Tools client (designed for device-code
#            against Graph; avoids the AADSTS65002 pre-authorization block)
ROPC_CLIENT = os.environ.get("AUTH_ROPC_CLIENT_ID", "d3590ed6-52b3-4102-aeff-aad2292ab01c")
DEVICE_CLIENT = os.environ.get("AUTH_CLIENT_ID", "14d82eec-204b-4c2f-b7e8-296a70dab67e")
PUBLIC_CLIENT = ROPC_CLIENT          # back-compat alias
SLOT_MIN = 30                       # availabilityView granularity (minutes)
TIMEZONE = "America/Chicago"
TZ_LABEL = "America/Chicago (Central)"
HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_CACHE = os.path.join(HERE, ".token.json")   # stores the refresh token
# Delegated scopes for device-code / refresh. (ROPC uses .default instead.)
DEVICE_SCOPES = "offline_access https://graph.microsoft.com/Calendars.Read"

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
# Tenant for the login endpoint. From the account domain if known, else an env
# override, else "organizations" (lets any work/school account resolve itself).
TENANT = ((USER.split("@")[-1] if USER and "@" in USER else None)
          or _ENV.get("TENANT") or os.environ.get("AUTH_TENANT") or "organizations")

# Auth mode:
#   password  -> ROPC, fully headless (needs USER+PASS in .env)
#   device    -> device-code, one-time browser login, refresh token cached
# Defaults to password when a PASS is present, otherwise device.
AUTH_MODE = (_ENV.get("AUTH_MODE") or os.environ.get("AUTH_MODE")
             or ("password" if PASS else "device")).lower()


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


def _token_url():
    return "https://login.microsoftonline.com/%s/oauth2/v2.0/token" % TENANT


def _post_form(fields):
    return json.loads(_http(_token_url(),
                            urllib.parse.urlencode(fields).encode(),
                            {"Content-Type": "application/x-www-form-urlencoded"}))


def _load_refresh():
    try:
        with open(TOKEN_CACHE) as f:
            return json.load(f).get("refresh_token")
    except Exception:
        return None


def _save_refresh(rt):
    if not rt:
        return
    try:
        with open(TOKEN_CACHE, "w") as f:
            json.dump({"refresh_token": rt}, f)
        os.chmod(TOKEN_CACHE, 0o600)
    except Exception:
        pass


def device_login(print_fn=print):
    """Interactive device-code login. Prints a URL + code, waits for sign-in,
    caches the refresh token, and returns an access token."""
    dc = json.loads(_http(
        "https://login.microsoftonline.com/%s/oauth2/v2.0/devicecode" % TENANT,
        urllib.parse.urlencode({"client_id": DEVICE_CLIENT,
                                "scope": DEVICE_SCOPES}).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"}))
    print_fn("\nTo sign in, open:  %s" % dc["verification_uri"])
    print_fn("Enter code:        %s\n" % dc["user_code"])
    print_fn("Waiting for sign-in…")
    interval = int(dc.get("interval", 5))
    deadline = time.time() + int(dc.get("expires_in", 900))
    while time.time() < deadline:
        time.sleep(interval)
        try:
            tok = _post_form({
                "client_id": DEVICE_CLIENT,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": dc["device_code"],
            })
        except RuntimeError as e:
            msg = str(e)
            if "authorization_pending" in msg:
                continue
            if "slow_down" in msg:
                interval += 5
                continue
            raise
        _save_refresh(tok.get("refresh_token"))
        print_fn("Signed in. Token cached in %s" % os.path.basename(TOKEN_CACHE))
        return tok["access_token"], time.time() + int(tok.get("expires_in", 3600))
    raise RuntimeError("Device-code login timed out; run `python3 siebel.py login` again.")


class _Token:
    """Access-token cache. Acquires via (1) a cached refresh token,
    (2) ROPC password, or (3) device-code login — in that order of preference
    for the active AUTH_MODE. Refreshed a minute before expiry."""
    def __init__(self):
        self._lock = threading.Lock()
        self._value = None
        self._exp = 0

    def _from_refresh(self, rt):
        tok = _post_form({
            "client_id": DEVICE_CLIENT,
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "scope": DEVICE_SCOPES,
        })
        _save_refresh(tok.get("refresh_token", rt))
        return tok["access_token"], time.time() + int(tok.get("expires_in", 3600))

    def _from_password(self):
        tok = _post_form({
            "client_id": ROPC_CLIENT,
            "scope": GRAPH + "/.default",
            "grant_type": "password",
            "username": USER,
            "password": PASS,
        })
        return tok["access_token"], time.time() + int(tok.get("expires_in", 3600))

    def get(self, allow_interactive=True):
        with self._lock:
            if self._value and time.time() < self._exp - 60:
                return self._value
            # 1) ROPC when explicitly in password mode and creds present
            if AUTH_MODE == "password" and USER and PASS:
                self._value, self._exp = self._from_password()
                return self._value
            # 2) cached refresh token (device mode, headless after first login)
            rt = _load_refresh()
            if rt:
                try:
                    self._value, self._exp = self._from_refresh(rt)
                    return self._value
                except RuntimeError:
                    pass  # expired/revoked -> fall through
            # 3) ROPC fallback if a password is available
            if USER and PASS:
                self._value, self._exp = self._from_password()
                return self._value
            # 4) interactive device-code login
            if allow_interactive:
                self._value, self._exp = device_login()
                return self._value
            raise RuntimeError(
                "Not authenticated. Run `python3 siebel.py login` for a one-time "
                "device-code sign-in, or set USER/PASS in .env.")

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


# ----------------------------------------------------------------------------- cli
def _main(argv):
    cmd = argv[1] if len(argv) > 1 else "login"
    if cmd == "login":
        device_login()                      # prompts, caches refresh token
        print("Auth mode: %s   Tenant: %s" % (AUTH_MODE, TENANT))
    elif cmd == "logout":
        try:
            os.remove(TOKEN_CACHE)
            print("Removed cached token (%s)." % os.path.basename(TOKEN_CACHE))
        except FileNotFoundError:
            print("No cached token to remove.")
    elif cmd == "whoami":
        me = json.loads(_http(GRAPH + "/v1.0/me",
                              None, {"Authorization": "Bearer " + TOKEN.get()}))
        print("Signed in as: %s <%s>" % (me.get("displayName"),
              me.get("userPrincipalName") or me.get("mail")))
    else:
        print("usage: python3 siebel.py [login|logout|whoami]")
        return 2
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv))
