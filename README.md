# SiebelRooms

Find free conference rooms (and classrooms) in the Thomas M. Siebel Center for
Computer Science at UIUC, using Microsoft Graph free/busy data.

Two front-ends over one shared core:

- **`findroom.py`** — a terminal tool. *"What conference room is open 9–10 today?"*
- **`app.py`** — a tiny local web app with a table, Type column, type filter,
  and day/week navigation.

Both read the room list and types from [`allrooms.txt`](allrooms.txt) and talk
to Microsoft Graph (not EWS). Python 3.9+, **no third-party dependencies** —
standard library only.

---

## Setup

1. **Credentials.** Copy the template and fill in an Exchange service-account
   mailbox that can read room free/busy:

   ```bash
   cp .env.example .env
   # edit .env:  USER=<service-account email>   PASS=<password>
   ```

   `.env` is gitignored — do not commit it.

2. That's it. No `pip install` needed.

> **Auth note:** the tools use the OAuth2 ROPC (username/password) flow against
> your tenant with the Microsoft Office public client ID, then call Graph's
> `getSchedule`. The account must allow ROPC (no MFA / conditional-access block
> on that sign-in).

---

## CLI — `findroom.py`

Defaults to **Conference** rooms, today, 9–10 AM, free rooms listed first.
Times accept `HH`, `H:MM`, or `HH:MM` (24-hour, Central).

```bash
python3 findroom.py                          # conf rooms free, today 9–10
python3 findroom.py 14:00 15:00              # today 2–3 PM
python3 findroom.py --date 2026-11-12 9 10   # specific date, 9–10 AM
python3 findroom.py --type Class 13 14       # classrooms instead
python3 findroom.py --all --free-only        # every room, only the free ones
python3 findroom.py --json                   # machine-readable output
```

Options: `--date YYYY-MM-DD`, `--type Conference|Class|Research|Admin|Unknown|All`,
`--all` (= `--type All`), `--free-only`, `--json`.

Sample:

```
Siebel Conference rooms — 2026-11-10  9:00 AM-10:00 AM  (America/Chicago (Central))
8 free of 12

  FREE  Siebel Center 2102         [Conference] siebel-2102@mx.uillinois.edu
  ...
  busy  Siebel Center 2124         [Conference] siebel-2124@mx.uillinois.edu
        busy 8:00 AM-10:00 AM, busy 10:30 AM-12:00 PM, busy 2:00 PM-5:00 PM
```

---

## Web app — `app.py`

```bash
python3 app.py                # http://localhost:8765
PORT=9000 python3 app.py      # custom port
```

- Table of rooms with a **Status**, **Room**, **Type**, **Bookings**, and
  **Address** column.
- **Type filter** (defaults to Conference) and a **free-only** checkbox.
- Pick a date, start, and end time; free rooms are highlighted and sorted first.
- Navigate with « Week / ‹ Day / Today / Day › / Week ».
- All times shown in Central (America/Chicago).

Binds to `127.0.0.1` only (local use).

---

## Rooms & types — `allrooms.txt`

One room per line:

```
Name - address@domain - Type
```

`Type` is one of `Conference | Class | Research | Admin | Unknown`. Edit this
file to add rooms or fix a type; both tools pick it up immediately. See
[`sources.txt`](sources.txt) for how the current classifications were derived
and how much to trust each one.

---

## Files

| File | Purpose |
|---|---|
| `siebel.py` | Shared core: auth, room loading, concurrent Graph free/busy. |
| `findroom.py` | Command-line tool. |
| `app.py` | Local web app. |
| `allrooms.txt` | Room list + types (data). |
| `sources.txt` | Provenance/notes for the room classifications. |
| `test.py` | Offline tests for the pure logic (no network/credentials). |
| `.env.example` | Credential template (copy to `.env`). |

---

## Tests

```bash
python3 test.py
```

Covers the pure logic (slot math, free/busy window detection, room/type
parsing) with no network calls and no credentials required. See
[`test.py`](test.py).

---

## License

MIT — see [LICENSE](LICENSE).
