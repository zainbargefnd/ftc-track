#!/usr/bin/env python3
"""
FTC Pulse - the full tool
=========================
Combines everything:
  1. Tracks a WATCHLIST of teams (your team + whoever you want to follow).
  2. Detects NEW records by remembering the last run (saved to a small file).
  3. Writes a real webpage (ftc_pulse_feed.html) from the live data.

Run it:
    pip3 install requests
    python3 ftc_pulse.py

First run sets the baseline (no alerts yet). Run it again after a new event
and it will flag anything that beat the old records.

No API key needed. Be kind to the free API: keep the watchlist modest.
"""

import os
import time
import json
import html
import datetime
import requests

# ----------------------------- Settings -----------------------------
BASE    = "https://api.ftcscout.org/rest/v1"
SEASON  = 2025                       # DECODE season

# Teams to follow. Your team + a few rivals from your events. Edit freely.
WATCHLIST = [16481, 19505, 16887, 8404, 26121]

STATE_FILE = "ftc_pulse_state.json"  # remembers last run's records
HTML_FILE  = "index.html"            # the webpage GitHub Pages serves
PAUSE      = 0.3                      # seconds between API calls (be polite)


# --------------------------- API helpers ----------------------------
def get(path):
    """Fetch a path. Returns parsed JSON, or None on any problem."""
    try:
        r = requests.get(BASE + path, timeout=15)
    except requests.RequestException as e:
        print(f"  [network error] {e}")
        return None
    if r.status_code != 200:
        return None
    return r.json()


def team_name(num):
    t = get(f"/teams/{num}")
    return (t.get("name") if t else None) or f"Team {num}"


def team_highs(num):
    """
    Return a team's season highs + OPR for this season:
      { total, totalWhere, auto, autoWhere, opr, oprRank }
    Scores are the ALLIANCE score in matches this team played.
    """
    result = {"total": 0, "totalWhere": "", "auto": 0, "autoWhere": "",
              "opr": None, "oprRank": None}

    # OPR + world rank (informational, shown on the page)
    qs = get(f"/teams/{num}/quick-stats?season={SEASON}")
    if qs and isinstance(qs.get("tot"), dict):
        result["opr"] = round(qs["tot"].get("value", 0), 1)
        result["oprRank"] = qs["tot"].get("rank")

    # Which events did they attend? (derive from their match list)
    tmatches = get(f"/teams/{num}/matches?season={SEASON}")
    if not tmatches:
        return result
    codes = sorted({m["eventCode"] for m in tmatches})

    for code in codes:
        time.sleep(PAUSE)
        matches = get(f"/events/{SEASON}/{code}/matches")
        if not matches:
            continue
        ev = get(f"/events/{SEASON}/{code}")
        name = (ev.get("name") if ev else None) or code

        for m in matches:
            if not m.get("hasBeenPlayed"):
                continue
            alliance = None
            for t in m.get("teams", []):
                if t.get("teamNumber") == num:
                    alliance = t.get("alliance")
                    break
            if not alliance:
                continue
            side = m.get("scores", {}).get(alliance.lower())
            if not side:
                continue

            label = f"{name} - {m.get('tournamentLevel')} match {m.get('id')}"
            total = side.get("totalPoints")
            auto  = side.get("autoPoints")
            if total is not None and total > result["total"]:
                result["total"], result["totalWhere"] = total, label
            if auto is not None and auto > result["auto"]:
                result["auto"], result["autoWhere"] = auto, label

    return result


# --------------------------- Persistence ----------------------------
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ------------------------ Record detection --------------------------
def build_alerts(num, name, current, previous):
    """
    Compare this run vs the last. Return a list of NEW-record alerts.
    (Only score records are alerted - OPR rank shifts constantly even when a
    team isn't playing, so it would create noise. Rank is shown, not alerted.)
    """
    alerts = []
    if previous is None:
        return alerts  # first run = baseline, nothing to compare

    if current["total"] > previous.get("total", 0):
        alerts.append({
            "kind": "total", "num": num, "name": name,
            "text": "set a new season-high total score",
            "value": str(current["total"]), "label": "Pts Total",
            "where": current["totalWhere"],
            "delta": f"+{current['total'] - previous.get('total', 0)}",
        })
    if current["auto"] > previous.get("auto", 0):
        alerts.append({
            "kind": "auto", "num": num, "name": name,
            "text": "set a new season-high auto score",
            "value": str(current["auto"]), "label": "Pts Auto",
            "where": current["autoWhere"],
            "delta": f"+{current['auto'] - previous.get('auto', 0)}",
        })
    return alerts


# --------------------------- HTML output ----------------------------
def write_html(alerts, snapshots):
    def esc(s):
        return html.escape(str(s))

    updated = datetime.datetime.now().strftime("%b %d, %Y at %I:%M %p")

    if alerts:
        alert_cards = "".join(f"""
        <article class="card kind-{a['kind']}">
          <div class="stripe"></div>
          <div class="body">
            <div class="main">
              <span class="badge">New Record</span>
              <div class="headline"><b>{esc(a['name'])}</b> <span class="tn">#{a['num']}</span> {esc(a['text'])}.</div>
              <div class="where">{esc(a['where'])}</div>
            </div>
            <div class="stat">
              <div class="val">{esc(a['value'])}</div>
              <div class="lbl">{esc(a['label'])}</div>
              <div class="delta">{esc(a['delta'])}</div>
            </div>
          </div>
        </article>""" for a in alerts)
    else:
        alert_cards = """<div class="empty">No new records since the last run.
        Run this again after your next event to catch new highs.</div>"""

    rows = "".join(f"""
        <article class="snap">
          <div class="snap-team"><b>{esc(s['name'])}</b> <span class="tn">#{s['num']}</span></div>
          <div class="snap-stats">
            <span><i>Best total</i> {esc(s['total'])}</span>
            <span><i>Best auto</i> {esc(s['auto'])}</span>
            <span><i>OPR</i> {esc(s['opr'])}{' (rank #' + esc(s['oprRank']) + ')' if s['oprRank'] else ''}</span>
          </div>
        </article>""" for s in snapshots)

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FTC Pulse</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0F141A;--panel:#171F28;--line:#2A333E;--text:#E9EEF4;--muted:#8593A1;
--brand:#FF8A3D;--total:#4DA3FF;--auto:#FFCE45;--mono:ui-monospace,Menlo,monospace;}}
*{{box-sizing:border-box;}}body{{margin:0;background:var(--bg);color:var(--text);
font-family:Inter,system-ui,sans-serif;line-height:1.5;}}
.wrap{{max-width:740px;margin:0 auto;padding:28px 16px 60px;}}
.head{{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;
border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:24px;}}
h1{{font-family:'Space Grotesk',sans-serif;font-size:24px;margin:0;}}h1 span{{color:var(--brand);}}
.upd{{font-family:var(--mono);font-size:11.5px;color:var(--muted);}}
h2{{font-family:'Space Grotesk',sans-serif;font-size:13px;letter-spacing:.04em;
text-transform:uppercase;color:var(--muted);margin:28px 0 12px;}}
.card{{display:grid;grid-template-columns:4px 1fr;background:var(--panel);
border:1px solid var(--line);border-radius:12px;overflow:hidden;margin-bottom:10px;}}
.kind-total .stripe{{background:var(--total);}}.kind-auto .stripe{{background:var(--auto);}}
.body{{padding:14px 16px;display:flex;gap:14px;align-items:flex-start;}}
.main{{flex:1;min-width:0;}}
.badge{{font-family:'Space Grotesk',sans-serif;font-weight:700;font-size:10px;
letter-spacing:.07em;text-transform:uppercase;padding:3px 8px;border-radius:5px;
background:rgba(255,138,61,.15);color:var(--brand);}}
.headline{{font-size:14.5px;margin-top:7px;}}.headline b{{font-weight:600;}}
.tn{{font-family:var(--mono);font-size:12px;color:var(--muted);}}
.where{{font-family:var(--mono);font-size:11.5px;color:var(--muted);margin-top:4px;}}
.stat{{text-align:right;flex:0 0 auto;min-width:72px;}}
.val{{font-family:var(--mono);font-weight:700;font-size:22px;}}
.lbl{{font-size:9.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:4px;}}
.delta{{font-family:var(--mono);font-size:12px;font-weight:700;color:#36D399;margin-top:4px;}}
.empty{{color:var(--muted);text-align:center;padding:30px;border:1px dashed var(--line);
border-radius:12px;font-size:14px;}}
.snap{{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:12px 14px;margin-bottom:8px;}}
.snap-team{{font-size:14px;margin-bottom:6px;}}
.snap-stats{{display:flex;gap:18px;flex-wrap:wrap;font-family:var(--mono);font-size:12.5px;color:var(--text);}}
.snap-stats i{{color:var(--muted);font-style:normal;margin-right:5px;}}
.foot{{text-align:center;color:var(--muted);font-size:11px;font-family:var(--mono);margin-top:30px;}}
</style></head><body><div class="wrap">
<div class="head"><h1>FTC <span>Pulse</span></h1><div class="upd">Updated {updated}</div></div>
<h2>New since last run</h2>{alert_cards}
<h2>Watchlist</h2>{rows}
<div class="foot">Live data from FTCScout - {len(snapshots)} teams tracked</div>
</div></body></html>"""

    with open(HTML_FILE, "w") as f:
        f.write(page)


# ------------------------------- Main -------------------------------
def main():
    print(f"== FTC Pulse: scanning {len(WATCHLIST)} teams for season {SEASON} ==\n")
    state = load_state()
    first_run = not state
    all_alerts, snapshots = [], []

    for num in WATCHLIST:
        name = team_name(num)
        print(f"  scanning {name} (#{num})...")
        current = team_highs(num)
        prev = state.get(str(num))
        all_alerts += build_alerts(num, name, current, prev)
        snapshots.append({"num": num, "name": name, **current})
        state[str(num)] = current
        time.sleep(PAUSE)

    save_state(state)
    write_html(all_alerts, snapshots)

    print()
    if first_run:
        print("Baseline saved. Run me again after a new event to see NEW-record alerts.\n")
    elif all_alerts:
        print(f"** {len(all_alerts)} NEW record(s)! **")
        for a in all_alerts:
            print(f"   {a['name']} #{a['num']}: {a['text']} - {a['value']} {a['label']} ({a['where']})")
        print()
    else:
        print("No new records since last run.\n")

    print(f"Wrote the feed page to:  {os.path.abspath(HTML_FILE)}")
    print("Open it in your browser to see the FTC Pulse feed.")


if __name__ == "__main__":
    main()
