#!/usr/bin/env python3
"""
Siebel conference-room scheduler — a tiny stdlib-only web app.

- Reads rooms + types from allrooms.txt.
- Concurrently queries every room's Microsoft Graph free/busy for a date.
- Highlights rooms FREE for the start/end window; shows a Type column and a
  type filter (defaults to Conference, which is what most people want).
- Navigate by day / week or jump to any date. All times Central. No EWS.

Run:   python3 app.py            # then open http://localhost:8765
       PORT=9000 python3 app.py  # custom port

For a terminal version, see findroom.py.
"""
import os, json, urllib.parse
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import siebel

TYPES = ["Conference", "Class", "Research", "Admin", "Unknown", "All"]

INDEX_HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Siebel Room Scheduler</title>
<style>
  :root{--free:#16794b;--freebg:#e6f7ee;--busy:#b4232c;--line:#d9dce1;--ink:#1a1d22;--mut:#6b7280;}
  *{box-sizing:border-box}
  body{font:15px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;margin:0;color:var(--ink);background:#f6f7f9}
  header{background:#13294b;color:#fff;padding:14px 20px}
  header h1{margin:0;font-size:18px}
  header .tz{opacity:.8;font-size:12px;margin-top:2px}
  .bar{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;padding:14px 20px;background:#fff;border-bottom:1px solid var(--line)}
  .bar label{display:block;font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px}
  .bar input,.bar select{padding:7px 8px;border:1px solid var(--line);border-radius:7px;font-size:14px}
  button{padding:7px 11px;border:1px solid var(--line);background:#fff;border-radius:7px;cursor:pointer;font-size:14px}
  button:hover{background:#eef1f5}
  button.go{background:#13294b;color:#fff;border-color:#13294b}
  .nav{display:flex;gap:6px;align-items:center}
  .wrap{padding:16px 20px}
  .day{font-weight:600;font-size:16px;margin:0 0 4px}
  .count{color:var(--mut);font-size:13px;margin:0 0 12px}
  table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}
  th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);font-size:14px;vertical-align:top}
  thead th{background:#f0f2f5;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}
  tbody th{font-weight:600;color:var(--ink)}
  tr.free td,tr.free th{background:var(--freebg)}
  tbody tr:last-child td,tbody tr:last-child th{border-bottom:none}
  .tag{display:inline-block;font-size:12px;font-weight:600;padding:2px 8px;border-radius:999px;white-space:nowrap}
  .tag.free{background:var(--freebg);color:var(--free)}
  .tag.busy{background:#fde8e9;color:var(--busy)}
  .ty{display:inline-block;font-size:12px;padding:2px 8px;border-radius:6px;background:#eef1f5;color:#374151}
  .addr{color:var(--mut);font-size:12.5px;word-break:break-all}
  .blk{font-size:12.5px;color:#374151}
  .blk .s{color:var(--busy);font-weight:600}
  .none{font-size:12.5px;color:var(--free)}
  .err{background:#fde8e9;color:var(--busy);padding:10px 12px;border-radius:8px;margin:10px 0}
  .load{color:var(--mut)}
  .chk{display:flex;align-items:center}
  .chk label{display:flex;align-items:center;gap:6px;font-size:13px}
  /* visible keyboard focus for all interactive controls */
  a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid #1d4ed8;outline-offset:2px}
  /* visually hidden but available to screen readers */
  .sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
</style></head>
<body>
<header><h1>Siebel Center — Room Scheduler</h1>
<div class="tz">All times shown in __TZ__</div></header>

<div class="bar" role="search">
  <div><label for="date">Date</label><input type="date" id="date"></div>
  <div><label for="start">Start</label><input type="time" id="start" value="09:00" step="1800"></div>
  <div><label for="end">End</label><input type="time" id="end" value="10:00" step="1800"></div>
  <div><label for="type">Type</label><select id="type">__TYPES__</select></div>
  <div class="chk"><label><input type="checkbox" id="freeonly"> Free only</label></div>
  <button class="go" id="go">Find</button>
  <div class="nav" role="group" aria-label="Change date" style="margin-left:auto">
    <button data-j="-7" aria-label="Previous week"><span aria-hidden="true">&laquo;</span> Week</button>
    <button data-j="-1" aria-label="Previous day"><span aria-hidden="true">&lsaquo;</span> Day</button>
    <button data-j="0">Today</button>
    <button data-j="1" aria-label="Next day">Day <span aria-hidden="true">&rsaquo;</span></button>
    <button data-j="7" aria-label="Next week">Week <span aria-hidden="true">&raquo;</span></button>
  </div>
</div>

<main class="wrap">
  <h2 class="day" id="dayLabel"></h2>
  <p class="count" id="count"></p>
  <p id="status" class="sr-only" role="status" aria-live="polite"></p>
  <div id="out" class="load" aria-busy="true">Loading…</div>
</main>

<script>
const $ = s => document.querySelector(s);
function fmt12(hhmm){let[h,m]=hhmm.split(":").map(Number);let ap=h<12?"AM":"PM";let hh=h%12||12;return hh+":"+String(m).padStart(2,"0")+" "+ap;}
function todayISO(){return new Date().toLocaleDateString("en-CA",{timeZone:"America/Chicago"});}
if(!$("#date").value) $("#date").value = todayISO();

function shift(days){
  if(days===0){$("#date").value=todayISO();return load();}
  let d=new Date($("#date").value+"T12:00:00");
  d.setDate(d.getDate()+days);
  $("#date").value=d.toISOString().slice(0,10);
  load();
}
document.querySelectorAll(".nav button").forEach(b=>b.onclick=()=>shift(+b.dataset.j));
$("#go").onclick=load;
["date","start","end","type","freeonly"].forEach(id=>$("#"+id).addEventListener("change",load));

async function load(){
  const date=$("#date").value, start=$("#start").value, end=$("#end").value, type=$("#type").value;
  const dl=new Date(date+"T12:00:00");
  $("#dayLabel").textContent=dl.toLocaleDateString("en-US",{weekday:"long",year:"numeric",month:"long",day:"numeric"});
  $("#count").textContent="";
  $("#status").textContent="Loading rooms…";
  $("#out").className="load"; $("#out").setAttribute("aria-busy","true"); $("#out").textContent="Loading…";
  try{
    const r=await fetch(`/api/schedule?date=${date}&start=${start}&end=${end}&type=${encodeURIComponent(type)}`);
    const j=await r.json();
    if(!r.ok||j.error){throw new Error(j.error||("HTTP "+r.status));}
    render(j,start,end);
  }catch(e){
    $("#out").className=""; $("#out").setAttribute("aria-busy","false");
    $("#out").innerHTML=`<div class="err" role="alert">${e.message}</div>`;
    $("#status").textContent="Error: "+e.message;
  }
}

function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}

function render(j,start,end){
  let rooms=j.rooms;
  const free=rooms.filter(x=>x.free).length;
  const label=j.date;
  const summary=`${free} of ${rooms.length} ${j.type==="All"?"":j.type+" "}rooms free for ${fmt12(start)}–${fmt12(end)} · ${j.timezone}`;
  $("#count").textContent=summary;
  const out=$("#out"); out.className=""; out.setAttribute("aria-busy","false");
  rooms.sort((a,b)=> (b.free-a.free) || a.name.localeCompare(b.name));
  if($("#freeonly").checked) rooms=rooms.filter(x=>x.free);
  if(!rooms.length){
    out.innerHTML=`<p class="none">No matching rooms.</p>`;
    $("#status").textContent="No matching rooms for "+summary;
    return;
  }
  out.innerHTML=`<table><caption class="sr-only">Rooms for ${esc(label)}, ${esc(fmt12(start))} to ${esc(fmt12(end))} (${esc(j.timezone)})</caption>
    <thead><tr>
      <th scope="col">Status</th><th scope="col">Room</th><th scope="col">Type</th><th scope="col">Bookings (this day)</th><th scope="col">Address</th>
    </tr></thead><tbody>`+rooms.map(x=>{
    const blocks=x.busy.length
      ? x.busy.map(b=>`<div class="blk"><span class="s">${esc(b.status)}</span> ${fmt12(b.start)}–${fmt12(b.end)}</div>`).join("")
      : `<span class="none">No bookings all day</span>`;
    return `<tr class="${x.free?"free":""}">
      <td><span class="tag ${x.free?"free":"busy"}">${x.free?"FREE":"busy"}</span></td>
      <th scope="row">${esc(x.name)}</th>
      <td><span class="ty">${esc(x.type)}</span></td>
      <td>${blocks}</td>
      <td class="addr">${esc(x.address)}</td></tr>`;
  }).join("")+`</tbody></table>`;
  $("#status").textContent=summary;
}
load();
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            opts = "".join(
                '<option%s>%s</option>' % (" selected" if t == "Conference" else "", t)
                for t in TYPES)
            html = (INDEX_HTML.replace("__TZ__", siebel.TZ_LABEL)
                              .replace("__TYPES__", opts))
            return self._send(200, html, "text/html; charset=utf-8")
        if parsed.path == "/api/schedule":
            return self._api(urllib.parse.parse_qs(parsed.query))
        return self._send(404, json.dumps({"error": "not found"}))

    def _api(self, q):
        try:
            day = q.get("date", [date.today().isoformat()])[0]
            start = q.get("start", ["09:00"])[0]
            end = q.get("end", ["10:00"])[0]
            rtype = q.get("type", ["Conference"])[0]
            datetime.strptime(day, "%Y-%m-%d")  # validate
            rooms = siebel.query(day, start, end, rtype)
            return self._send(200, json.dumps({
                "date": day, "start": start, "end": end, "type": rtype,
                "timezone": siebel.TZ_LABEL, "rooms": rooms,
            }))
        except Exception as e:
            return self._send(500, json.dumps({"error": str(e)}))


def main():
    port = int(os.environ.get("PORT", "8765"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("Siebel room scheduler on http://localhost:%d  (%s)" % (port, siebel.TZ_LABEL))
    print("Service account: %s   Tenant: %s" % (siebel.USER, siebel.TENANT))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
