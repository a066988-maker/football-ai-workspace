"""Read Titan007's public football live feed. Do not invent fixtures or odds.

Outputs a complete fixtures list and, only when at least 3 matches have complete
opening/current Asian and totals plus European odds, a Gemini-ready verified file.
The feed can fail or restrict GitHub Actions access; missing means missing.
"""
import datetime as dt
import html
import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from slate import ZONE, slate_window

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "output"
FEED_BASE = "https://livestatic.titan007.com/vbsxml/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PersonalFootballResearch/1.0)",
    "Referer": "https://live.titan007.com/",
    "Accept": "text/javascript,text/plain,*/*",
}
LEAGUE_PRIORITY = ("英超", "西甲", "意甲", "德甲", "法甲", "欧冠", "歐冠", "欧联", "歐聯", "欧罗巴", "歐霸", "欧协联", "歐協聯",
                   "英冠", "葡超", "荷甲", "日职", "日職", "澳超", "美职", "美職")


def fetch(name):
    if name not in ("bfdata_ut.js", "sbOddsData.js"):
        raise ValueError("Unsupported endpoint")
    req = urllib.request.Request(FEED_BASE + name, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=18) as response:
        if response.status != 200:
            raise ValueError("Source HTTP " + str(response.status))
        raw = response.read(5_000_000)
    if not raw:
        raise ValueError("Empty source: " + name)
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeError:
            pass
    raise ValueError("Cannot decode source: " + name)


def stamp(value):
    """Titan feed timestamp: year, zero-based-month, day, hour, minute, second."""
    try:
        p = [int(x) for x in value.split(",")]
        if len(p) < 5:
            return None
        return dt.datetime(p[0], p[1] + 1, p[2], p[3], p[4],
                           p[5] if len(p) > 5 else 0, tzinfo=ZONE)
    except (ValueError, IndexError, OverflowError):
        return None


def clean(value):
    return html.unescape(re.sub(r"<[^>]*>", "", value or "")).strip()


def fixture_rows(source):
    """Each A[i] field is caret-separated. Field positions follow the public feed."""
    pattern = r'A\[\d+\]\s*=\s*"([^"\r\n]*)"\.split\(\s*["\x27]\^["\x27]\s*\)'
    items = {}
    for match in re.finditer(pattern, source):
        f = match.group(1).split("^")
        if len(f) < 18 or not f[0].isdigit():
            continue
        when = stamp(f[11])
        if not when:
            continue
        home, away, league = clean(f[5] or f[4]), clean(f[8] or f[7]), clean(f[2])
        if not (home and away and league) or home == away:
            continue
        try:
            state = int(f[13])
        except ValueError:
            continue
        items[f[0]] = {
            "id": f[0], "league": league, "home": home, "away": away,
            "kickoff": when.isoformat(timespec="minutes"),
            "state": state,
            "source_url": "https://zq.titan007.com/analysis/" + f[0] + "cn.htm",
        }
    return list(items.values())


def number(value):
    try:
        result = float(str(value).strip().strip('"').strip("'"))
        return result if result == result and abs(result) < 1_000_000 else None
    except (ValueError, TypeError):
        return None


def triple(group, offset):
    fields = [x.strip() for x in group.split(",")]
    if len(fields) < offset + 3:
        return None
    values = [number(x) for x in fields[offset:offset + 3]]
    if any(x is None for x in values):
        return None
    return values


def odds_rows(source):
    """Parse sData[id]=[asian,europe,total,...]; each market has open and current triples."""
    rows = {}
    for match in re.finditer(r"sData\[(\d+)\]\s*=\s*\[([\s\S]*?)\]\s*;", source):
        groups = re.findall(r"\[([^\[\]]*)\]", match.group(2))
        if len(groups) < 3:
            continue
        values = {}
        for name, group in zip(("asian", "euro", "ou"), groups[:3]):
            values[name + "_open"] = triple(group, 0)
            values[name + "_live"] = triple(group, 3)
        rows[match.group(1)] = values
    return rows


def valid(price, lo=0.1, hi=100):
    return price is not None and lo <= price <= hi


def usable_odds(odds):
    if not odds:
        return False
    for market in ("asian", "euro", "ou"):
        for phase in (("live",) if market == "euro" else ("open", "live")):
            data = odds.get(market + "_" + phase)
            if not data or len(data) != 3:
                return False
            left, line, right = data
            if market == "euro":
                if not all(valid(x, 1.01, 500) for x in data):
                    return False
            elif market == "asian":
                if not (valid(left) and valid(right) and isinstance(line, (int, float)) and -7 <= line <= 7):
                    return False
            else:
                if not (valid(left) and valid(right) and isinstance(line, (int, float)) and 0.25 <= line <= 10):
                    return False
    return True


def selection_rank(m):
    priority = next((i for i, name in enumerate(LEAGUE_PRIORITY)
                     if name in m["league"]), len(LEAGUE_PRIORITY))
    return (priority, m["kickoff"], m["id"])




ASIAN_LINES = {
    "平手": 0, "平/半": 0.25, "半球": 0.5, "半/一": 0.75,
    "一球": 1, "一/球半": 1.25, "球半": 1.5, "球半/两": 1.75,
    "两球": 2, "两/两球半": 2.25, "两球半": 2.5,
    "两球半/三": 2.75, "三球": 3,
}


def asian_line(raw):
    value = str(raw or "").strip()
    negative = value.startswith("*")
    line = ASIAN_LINES.get(value.lstrip("*").strip())
    return -line if negative and line is not None else line


def total_line(raw):
    values = [number(v) for v in str(raw or "").split("/")]
    if not values or any(v is None for v in values):
        return None
    return sum(values) / len(values)


def browser_market_rows(payload):
    """Use explicitly displayed Chinese goal lines, never assume implied scores."""
    rows = {}
    for group in payload:
        mid = str(group.get("id", ""))
        entries = group.get("items") or []
        if not re.fullmatch(r"\d{5,10}", mid) or not entries:
            continue
        pre = next((e for e in reversed(entries) if not str(e.get("ID", "")).startswith("3_")), entries[0])
        rows[mid] = {
            "asian_open": [number(pre.get("homeOdds_f")), asian_line(pre.get("letgoal_f")), number(pre.get("guestOdds_f"))],
            "asian_live": [number(pre.get("homeOdds")), asian_line(pre.get("letgoal")), number(pre.get("guestOdds"))],
            "ou_open": [number(pre.get("upOdds_f")), total_line(pre.get("totalScore_f")), number(pre.get("downOdds_f"))],
            "ou_live": [number(pre.get("upOdds")), total_line(pre.get("totalScore")), number(pre.get("downOdds"))],
            # European odds require a separate live 1x2 detail source.
            "euro_open": None, "euro_live": None,
        }
    return rows



def detail_market(kind, cells):
    """Parse actual source company row, never synthesize an opening/current line."""
    if kind == "euro":
        if len(cells) < 5:
            return None
        values = [number(x) for x in cells[2:5]]
        return {"euro_live": values} if all(valid(x, 1.01, 500) for x in values) else None
    if len(cells) < 9:
        return None
    line = asian_line if kind == "asian" else total_line
    opening = [number(cells[3]), line(cells[4]), number(cells[5])]
    current = [number(cells[6]), line(cells[7]), number(cells[8])]
    if any(x is None for x in opening + current):
        return None
    if kind == "asian":
        if not (-7 <= opening[1] <= 7 and -7 <= current[1] <= 7):
            return None
    elif not (0.25 <= opening[1] <= 10 and 0.25 <= current[1] <= 10):
        return None
    if not all(valid(x) for x in (opening[0], opening[2], current[0], current[2])):
        return None
    return {kind + "_open": opening, kind + "_live": current}



DATED_BASE = "https://bf.titan007.com/football/"


class TitanScheduleTable(HTMLParser):
    """Read labelled match rows, including the data provider's own match ID."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.row = None
        self.cell = None
        self.in_order = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            mid = attrs.get("sid") or ""
            self.row = (mid, []) if re.fullmatch(r"\d{5,10}", mid) else None
            self.cell = None
            self.in_order = False
        elif self.row and tag == "td":
            self.cell = []
        elif self.cell is not None and tag == "span" and attrs.get("name") == "order":
            self.in_order = True

    def handle_data(self, data):
        if self.cell is not None and not self.in_order:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.cell is not None and tag == "span":
            self.in_order = False
        elif self.cell is not None and tag == "td":
            self.row[1].append("".join(self.cell).strip())
            self.cell = None
            self.in_order = False
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = None
            self.cell = None


def dated_fixture_rows(source, page_date, start, end):
    # Verify the server returned the requested date rather than e.g. a homepage.
    marker = re.search(r"""\bcurrDate\s*=\s*['"](\d{4}-\d{2}-\d{2})['"]""", source)
    if not marker or marker[1] != page_date.isoformat():
        return []
    parser = TitanScheduleTable()
    parser.feed(source)
    matches = {}
    for mid, cells in parser.rows:
        if len(cells) < 10 or cells[4] not in ("-", "－"):
            continue
        time = re.fullmatch(r"(\d{2})-(\d{2})\s+(\d{2}):(\d{2})", cells[1])
        if not time:
            continue
        month, day, hour, minute = map(int, time.groups())
        date = next((d for d in (page_date, page_date + dt.timedelta(days=1))
                     if (d.month, d.day) == (month, day)), None)
        if not date:
            continue
        try:
            kickoff = dt.datetime.combine(date, dt.time(hour, minute), ZONE)
        except ValueError:
            continue
        league, home, away = cells[0], cells[3], cells[5]
        if not (start <= kickoff < end and league and home and away and home != away):
            continue
        matches[mid] = {"id": mid, "league": league, "home": home, "away": away,
                        "kickoff": kickoff.isoformat(timespec="minutes"), "state": 0,
                        "source_url": "https://bf.titan007.com/detail/" + mid + ".htm"}
    return list(matches.values())


def dated_schedule(start, end):
    def read(date):
        url = DATED_BASE + "Next_" + date.strftime("%Y%m%d") + ".htm"
        try:
            req = urllib.request.Request(url, headers={
                **HEADERS, "Accept": "text/html", "Referer": DATED_BASE})
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status != 200:
                    return [], f"HTTP {response.status}"
                raw = response.read(2_500_000)
            try:
                source = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                source = raw.decode("gb18030")
            rows = dated_fixture_rows(source, date, start, end)
            return rows, f"{len(rows)} eligible rows"
        except (OSError, ValueError) as exc:
            return [], type(exc).__name__ + ": " + str(exc)[:100]

    dates = (start.date(), end.date())
    rows, diagnostics = {}, {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for date, (found, message) in zip(dates, pool.map(read, dates)):
            diagnostics[date.isoformat()] = message
            for match in found:
                rows.setdefault(match["id"], match)
    return list(rows.values()), diagnostics


def detail_candidates(fixtures, start, end, now):
    return sorted((m for m in fixtures
                   if m["state"] in (-1, 0)
                   and start <= dt.datetime.fromisoformat(m["kickoff"]) < end
                   and dt.datetime.fromisoformat(m["kickoff"]) > now + dt.timedelta(minutes=5)),
                  key=selection_rank)


def browser_source(dated_fixtures=(), now=None):
    """Use the public site's loaded JS if direct feed connections are blocked.

    Never infer market data from the presence of a UI element. Read actual
    global source arrays only, and leave missing market groups incomplete.
    """
    from playwright.sync_api import sync_playwright
    import shutil

    with sync_playwright() as p:
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        options = {"executable_path": chrome} if chrome else {}
        browser = p.chromium.launch(headless=True,
                                    args=["--no-sandbox", "--disable-dev-shm-usage"], **options)
        try:
            page = browser.new_page(locale="zh-CN", timezone_id="Asia/Taipei")
            payload = {"title": "", "schedule": [], "markets": [], "flashMarkets": []}
            try:
                page.goto("https://live.titan007.com/", wait_until="domcontentloaded", timeout=35000)
                page.wait_for_function("Array.isArray(window.A) && window.A.length > 2",
                                       timeout=25000)
                try:
                    page.evaluate("() => { if (typeof window.loadBfOdds === 'function') window.loadBfOdds(); }")
                except Exception:
                    pass
                page.wait_for_timeout(2500)
                payload = page.evaluate(r"""() => {
                    const schedule = Array.isArray(window.A) ? window.A.slice(1) : [];
                    const markets = (typeof window.sData === 'object' && window.sData)
                      ? Object.entries(window.sData).filter(([id, rows]) =>
                          /^\d{5,10}$/.test(id) && Array.isArray(rows)).slice(0, 3000)
                      : [];
                    const oddsGroups = window.flashData?.bfOddsList?.items || [];
                    const example = oddsGroups.find(g => g?.oddsList?.items?.length);
                    return {schedule, markets, title: document.title,
                        flashMarkets: oddsGroups.map(g => ({id: g.sId, items: (g.oddsList?.items || []).slice(-8)})),
                        sample: schedule.filter(Array.isArray).slice(0, 2).map(r => r.slice(0, 20)),
                        pendingSample: schedule.filter(Array.isArray).filter(r => Number(r[13]) <= 0).slice(0, 8).map(r => ({length:r.length, fields:r.slice(0,32)})),
                        pendingDom: schedule.filter(Array.isArray).filter(r=>Number(r[13])<=0).slice(0,2).map(r=>({id:r[0],html:document.getElementById("tr1_"+r[0])?.outerHTML.slice(0,2500)||""})),
                        flashType: typeof window.flashData,
                        oddsGroupCount: oddsGroups.length,
                        oddsExample: example ? {id: example.sId,
                            entries: example.oddsList.items.length,
                            first: example.oddsList.items[0]} : null};
                }""")
            except Exception as exc:
                payload["homepage_error"] = type(exc).__name__ + ": " + str(exc)[:140]
            # Check up to eight upcoming fixtures against separate match-specific
            # Titan European, Asian and totals pages. Every visited page must
            # have the expected home AND away names, or its odds are rejected.
            now = now or dt.datetime.now(ZONE)
            begin, finish = slate_window(now)
            # Dated pages use the provider's own match IDs; never match ESPN by name.
            choices = {m["id"]: m for m in dated_fixtures}
            live_choices = {}
            for source_row in payload["schedule"]:
                if not isinstance(source_row, list) or len(source_row) < 14:
                    continue
                sid = str(source_row[0])
                scheduled = stamp(str(source_row[12])) or stamp(str(source_row[11]))
                state = int(source_row[13]) if str(source_row[13]).lstrip("-").isdigit() else -99
                if not (scheduled and sid.isdigit()):
                    continue
                home = clean(str(source_row[5] or source_row[4] or ""))
                away = clean(str(source_row[8] or source_row[7] or ""))
                league = clean(str(source_row[2] or ""))
                if not (home and away and league and home != away):
                    continue
                live_choices[sid] = {"id": sid, "league": league, "home": home,
                                     "away": away, "state": state,
                                     "kickoff": scheduled.isoformat(timespec="minutes")}
            choices.update(live_choices)
            candidates = detail_candidates(choices.values(), begin, finish, now)
            payload["dated_candidates"] = len(dated_fixtures)
            payload["homepage_candidates"] = len(detail_candidates(live_choices.values(), begin, finish, now))
            payload["detailOdds"] = {}
            payload["euro_candidates"] = len(candidates)
            payload["euro_attempted"] = 0
            payload["market_results"] = {}
            for match in candidates[:8]:
                sid = match["id"]
                markets = {}
                endpoints = (
                    ("euro", "https://1x2.titan007.com/oddslist/" + sid + ".htm"),
                    ("asian", "https://vip.titan007.com/AsianOdds_n.aspx?id=" + sid + "&l=0"),
                    ("ou", "https://vip.titan007.com/OverDown_n.aspx?id=" + sid + "&l=0"),
                )
                for kind, url in endpoints:
                    try:
                        payload["euro_attempted"] += 1
                        response = page.goto(url, wait_until="domcontentloaded", timeout=10000)
                        if response is None or response.status != 200:
                            outcome = f"HTTP {response.status}" if response else "no response"
                        else:
                            title = re.sub(r"\s+|[（(]中[)）]", "", page.title())
                            names = [re.sub(r"\s+|[（(]中[)）]", "", match[side]) for side in ("home", "away")]
                            if not all(name and name in title for name in names):
                                outcome = "title_mismatch"
                            else:
                                row = page.locator("tr").filter(has_text=re.compile("Crow", re.I)).first
                                if not row.count():
                                    row = page.locator('tr[id^="oddstr_"]').first
                                if row.count() and row.is_visible():
                                    cells = [v.strip() for v in row.locator("td").all_inner_texts()]
                                    parsed = detail_market(kind, cells)
                                else:
                                    parsed = None
                                if parsed:
                                    markets.update(parsed)
                                outcome = "parsed" if parsed else "no_visible_complete_market"
                    except Exception as exc:
                        outcome = type(exc).__name__
                    payload["market_results"].setdefault(sid, {})[kind] = outcome
                if markets:
                    payload["detailOdds"][sid] = markets
            payload["euro_success"] = sum(
                1 for item in payload["detailOdds"].values()
                if item.get("euro_live") and item.get("asian_open") and item.get("asian_live")
                and item.get("ou_open") and item.get("ou_live")
            )
            # Diagnostic: check whether a genuine 1x2 detail page is reachable.
            eid = (payload.get("oddsExample") or {}).get("id")
            if not candidates and eid and str(eid).isdigit():
                try:
                    page.goto("https://1x2.titan007.com/Oddslist/" + str(eid) + ".htm",
                              wait_until="domcontentloaded", timeout=16000)
                    row = page.locator("tr").filter(has_text=re.compile("Crow", re.I)).first
                    payload["euroProbe"] = {
                        "id": eid, "title": page.title()[:120],
                        "crow_cells": [x.strip() for x in row.locator("td").all_text_contents()][:16],
                    }
                except Exception as detail_exc:
                    payload["euroProbe"] = {"id": eid, "error": type(detail_exc).__name__ + ": " + str(detail_exc)[:120]}
        finally:
            browser.close()
    fixtures = []
    for row in payload["schedule"]:
        if not isinstance(row, list) or len(row) < 18:
            continue
        fields = [str(x) if x is not None else "" for x in row]
        if not fields[0].isdigit():
            continue
        # Reuse the same source-field interpretation as the direct-feed parser.
        time = stamp(fields[12]) or stamp(fields[11])
        try:
            state = int(fields[13])
        except ValueError:
            continue
        if not time:
            continue
        home, away, league = clean(fields[5] or fields[4]), clean(fields[8] or fields[7]), clean(fields[2])
        if not (home and away and league) or home == away:
            continue
        fixtures.append({
            "id": fields[0], "league": league, "home": home, "away": away,
            "kickoff": time.isoformat(timespec="minutes"), "state": state,
            "source_url": "https://zq.titan007.com/analysis/" + fields[0] + "cn.htm",
        })
    odds = {}
    for match_id, groups in payload["markets"]:
        if not isinstance(groups, list) or len(groups) < 3:
            continue
        parsed = {}
        for name, group in zip(("asian", "euro", "ou"), groups[:3]):
            if not isinstance(group, list) or len(group) < 6:
                continue
            nums = [number(x) for x in group[:6]]
            parsed[name + "_open"] = nums[:3]
            parsed[name + "_live"] = nums[3:6]
        odds[match_id] = parsed
    for match_id, market in browser_market_rows(payload.get("flashMarkets", [])).items():
        odds.setdefault(match_id, market)
    for match_id, details in payload.get("detailOdds", {}).items():
        odds.setdefault(match_id, {}).update(details)
    return fixtures, odds, {"title": payload["title"][:100],
                             "homepage_error": payload.get("homepage_error"),
                             "dated_candidates": payload.get("dated_candidates"),
                             "homepage_candidates": payload.get("homepage_candidates"),
                             "browser_rows": len(payload["schedule"]),
                             "browser_market_arrays": len(payload["markets"]),
                             "schedule_sample": payload.get("sample", []),
                             "pending_sample": payload.get("pendingSample", []),
                             "pending_dom": payload.get("pendingDom", []),
                             "flash_type": payload.get("flashType"),
                             "odds_group_count": payload.get("oddsGroupCount"),
                             "odds_example": payload.get("oddsExample"),
                             "euro_probe": payload.get("euroProbe"),
                             "euro_candidates": payload.get("euro_candidates"),
                             "euro_success": payload.get("euro_success"),
                             "market_results": payload.get("market_results"),
                             "detail_pages_requested": payload.get("euro_attempted")}



ESPN_LEAGUES = {
    "eng.1": "英超", "eng.2": "英冠", "esp.1": "西甲",
    "ita.1": "意甲", "ger.1": "德甲", "fra.1": "法甲",
    "uefa.champions": "欧冠", "uefa.europa": "欧联",
    "ned.1": "荷甲", "por.1": "葡超", "jpn.1": "日职",
    "aus.1": "澳超", "usa.1": "美职联",
}


def parse_espn_events(data, league, start, end):
    """Independent schedule-only fallback. ESPN IDs are never Titan IDs."""
    found = []
    for event in data.get("events", []):
        try:
            when = dt.datetime.fromisoformat(event["date"].replace("Z", "+00:00")).astimezone(ZONE)
            if not start <= when < end:
                continue
            competitors = event["competitions"][0]["competitors"]
            names = {row["homeAway"]: clean(row["team"]["displayName"]) for row in competitors}
            home, away = names["home"], names["away"]
            eid = str(event["id"])
            if not eid.isdigit() or not home or not away or home == away:
                continue
            if event.get("status", {}).get("type", {}).get("completed"):
                continue
            urls = [link.get("href", "") for link in event.get("links", [])]
            source_url = next((u for u in urls if u.startswith("https://www.espn.com/")), "")
            if not source_url:
                source_url = "https://www.espn.com/soccer/match/_/gameId/" + eid
            found.append({
                "id": "espn-" + eid, "league": league, "home": home, "away": away,
                "kickoff": when.isoformat(timespec="minutes"), "state": -1,
                "source_url": source_url,
            })
        except (KeyError, IndexError, TypeError, ValueError):
            continue
    return found


def espn_schedule(start, end):
    """Used only to show schedules when Titan is unreachable; never creates odds."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    days = sorted({start.date(), end.date()})
    jobs = [(slug, label, day) for slug, label in ESPN_LEAGUES.items() for day in days]

    def task(job):
        slug, label, day = job
        url = "https://site.api.espn.com/apis/site/v2/sports/soccer/" + slug + "/scoreboard?dates=" + day.strftime("%Y%m%d")
        req = urllib.request.Request(url, headers={"User-Agent": "python-urllib/3.11",
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            return parse_espn_events(json.load(response), label, start, end)

    fixtures, failures = {}, 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(task, job) for job in jobs]
        for future in as_completed(futures):
            try:
                for fixture in future.result():
                    fixtures[fixture["id"]] = fixture
            except Exception:
                failures += 1
    if not fixtures and failures == len(jobs):
        raise ValueError("Titan and ESPN schedule sources unavailable")
    return list(fixtures.values()), {"espn_requests": len(jobs), "espn_failures": failures}


def collect(now=None):
    OUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)
    # Each attempt must rebuild verified inputs for the target slate.
    verified_path = DATA / "verified_matches.json"
    verified_path.unlink(missing_ok=True)
    now = now or dt.datetime.now(ZONE)
    start, end = slate_window(now)
    report = {
        "updated_at": now.isoformat(timespec="seconds"),
        "status": "fetching",
        "window_start": start.isoformat(timespec="minutes"),
        "window_end": end.isoformat(timespec="minutes"),
        "source": "https://livestatic.titan007.com/vbsxml/",
        "source_note": "Public Titan007 football feed; no invented matches/odds",
    }
    try:
        fixtures, odds = [], {}
        try:
            schedule_text = fetch("bfdata_ut.js")
            fixtures = fixture_rows(schedule_text)
            odds = odds_rows(fetch("sbOddsData.js"))
            report["collection_method"] = "direct_public_feed"
        except (OSError, ValueError) as exc:
            report["direct_error"] = type(exc).__name__ + ": " + str(exc)[:160]

        initial = detail_candidates(fixtures, start, end, now)
        if sum(usable_odds(odds.get(m["id"])) for m in initial) < 4:
            dated, diagnostics = dated_schedule(start, end)
            report["dated_schedule"] = diagnostics
            combined = {m["id"]: m for m in dated}
            combined.update({m["id"]: m for m in fixtures})
            if dated:
                report["collection_method"] = "titan_dated_schedule"
                report["source"] = DATED_BASE
                report["source_note"] = "Titan007 dated football schedule plus verified public markets when available."
            try:
                browser_fixtures, browser_odds, diagnostics = browser_source(dated, now)
                report["browser_diagnostics"] = diagnostics
                if browser_fixtures or browser_odds:
                    report["collection_method"] = "titan_dated_and_live" if dated else "browser_loaded_public_source"
                combined.update({m["id"]: m for m in browser_fixtures})
                for mid, market in browser_odds.items():
                    existing = odds.get(mid)
                    if usable_odds(market) or not existing:
                        odds[mid] = market
                    elif not usable_odds(existing):
                        for keys in (("asian_open", "asian_live"), ("ou_open", "ou_live"), ("euro_live",)):
                            if all(market.get(key) and all(v is not None for v in market[key])
                                   for key in keys):
                                existing.update({key: market[key] for key in keys})
            except Exception as exc:
                report["browser_error"] = type(exc).__name__ + ": " + str(exc)[:160]
            fixtures = list(combined.values())

        window = [m for m in fixtures
                  if start <= dt.datetime.fromisoformat(m["kickoff"]) < end
                  and m["state"] in (-1, 0)]
        if not window:
            alternate, diagnostics = espn_schedule(start, end)
            fixtures, odds = alternate, {}
            window = [m for m in alternate
                      if start <= dt.datetime.fromisoformat(m["kickoff"]) < end
                      and m["state"] in (-1, 0)]
            report["collection_method"] = "espn_auxiliary_schedule_only"
            report["schedule_diagnostics"] = diagnostics
            report["source"] = "https://site.api.espn.com/apis/site/v2/sports/soccer/"
            report["source_note"] = "ESPN schedule only. Titan odds unavailable; no AI predictions."
        window.sort(key=lambda m: (m["kickoff"], m["id"]))
        available = []
        for fixture in window:
            market = odds.get(fixture["id"])
            fixture["has_complete_odds"] = usable_odds(market)
            if not fixture["has_complete_odds"]:
                continue
            # These numbers are direct source values; Asian sign conventions are
            # not interpreted as a home/away side without a second check.
            record = dict(fixture)
            record.update({
                "odds_checked_at": now.isoformat(timespec="seconds"),
                "asian_open": market["asian_open"],
                "asian_live": market["asian_live"],
                "euro_live": market["euro_live"],
                "ou_open": market["ou_open"],
                "ou_live": market["ou_live"],
            })
            available.append(record)
        upcoming = [m for m in available
                    if dt.datetime.fromisoformat(m["kickoff"]) > now + dt.timedelta(minutes=5)]
        ranked = sorted(upcoming, key=selection_rank)[:4]
        provider = "Titan007 live public football feed"
        # The hosted runner received an access challenge. Retain the adapter
        # for a permitted source environment, but do not retry that challenge.
        report["aiscore_backup_state"] = "disabled_after_hosted_access_challenge"
        if os.environ.get("ENABLE_AISCORE_BACKUP") == "1" and len(ranked) < 4 and any("欧联" in m["league"] or "欧罗巴" in m["league"] for m in window):
            try:
                from aiscore_backup import run
                backup, diagnostics = run(start, end, dt.datetime.now(ZONE))
                report["aiscore_backup"] = diagnostics
                backup = [m for m in backup if usable_odds(m)]
                if len(backup) == 4:
                    ranked = sorted(backup, key=selection_rank)
                    provider = "AiScore public pre-match odds backup"
                    report["odds_provider"] = "AiScore"
                    report["titan_verified_count"] = len(available)
                    report["collection_method"] = "aiscore_public_backup"
                    report["source_note"] = "Fixtures retain original source. Analysis prices are separately sourced from AiScore."
            except Exception as exc:
                report["aiscore_backup_error"] = type(exc).__name__ + ": " + str(exc)[:120]
        counts = dict(sorted(Counter(m["league"] for m in window).items()))
        (OUT / "fixtures.json").write_text(
            json.dumps({
                "date": start.date().isoformat(), "source": report["source"],
                "window_start": report["window_start"], "window_end": report["window_end"],
                "league_counts": counts, "fixtures": window
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        report.update({
            "feed_fixture_count": len(fixtures),
            "feed_market_count": len(odds),
            "window_fixture_count": len(window),
            "complete_odds_count": len(ranked) if provider.startswith("AiScore") else len(available),
            "selected_count": len(ranked),
        })
        if len(ranked) >= 3:
            verified_payload = json.dumps({
                "source": provider,
                "verified_at": now.isoformat(timespec="seconds"),
                "matches": ranked,
            }, ensure_ascii=False, indent=2)
            verified_path.write_text(verified_payload, encoding="utf-8")
            (OUT / "verified_matches.json").write_text(verified_payload, encoding="utf-8")
            report["status"] = "verified_ready_for_ai"
        else:
            (OUT / "verified_matches.json").unlink(missing_ok=True)
            report["status"] = "schedule_only_no_titan_odds" if report.get("collection_method") == "espn_auxiliary_schedule_only" else "insufficient_verified_odds"
            report["message"] = "Fewer than three scheduled matches have all opening/current Titan odds; AI analysis not run."
    except Exception as exc:
        (OUT / "verified_matches.json").unlink(missing_ok=True)
        report["status"] = "source_error"
        report["message"] = type(exc).__name__ + ": " + str(exc)[:240]
        (OUT / "fixtures.json").unlink(missing_ok=True)
    (OUT / "status.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    collect()
