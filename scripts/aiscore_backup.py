"""Bounded public-page backup for a verified competition. Never combine companies."""
import datetime as dt
import json
import re

BASE = "https://m.aiscore.com"
LEAGUES = {"欧联": "/tournament-uefa-europa-league/2jr7owi6es1q0em/matches"}
NAMES = {
    "Marseille": "马赛", "Levski Sofia": "索菲亚列夫斯基",
    "Olympiacos Piraeus": "奥林匹亚科斯", "AC Milan": "AC米兰",
    "Dinamo Zagreb": "萨格勒布迪纳摩", "Bayer 04 Leverkusen": "勒沃库森",
    "RC Celta": "塞尔塔", "Bournemouth AFC": "伯恩茅斯",
    "Besiktas JK": "贝西克塔斯", "Hapoel Beer Sheva": "贝尔谢巴工人",
    "FC Viktoria Plzeň": "比尔森胜利", "Benfica": "本菲卡",
    "Union Saint-Gilloise": "圣吉罗斯联合", "Lech Poznan": "波兹南莱赫",
    "Red Bull Salzburg": "萨尔茨堡红牛", "Ararat-Armenia FC": "阿拉拉特亚美尼亚",
    "Crystal Palace": "水晶宫", "Real Sociedad": "皇家社会",
    "Juventus": "尤文图斯", "Omonia Nicosia FC": "尼科西亚团结",
    "TSG Hoffenheim": "霍芬海姆", "Sturm Graz": "格拉茨风暴",
    "Lyon": "里昂", "Lillestrom": "利勒斯特罗姆",
}
LINK = re.compile(r"/match-[a-z0-9-]+/([a-z0-9]{12,22})/h2h")
BOOK = re.compile(r"https://img[0-9]\.aiscore\.com/other/([0-9a-f]{20})\.png")
TABS = {"eu": "1 X 2", "ah": "Asian Handicap", "ou": "Total Goals"}


def line(raw):
    # The minus applies to both legs of displays such as -1/1.5.
    m = re.fullmatch(r"([+-]?)(\d+(?:\.\d+)?)(?:/(\d+(?:\.\d+)?))?", raw)
    if not m:
        raise ValueError("Unrecognised goal line")
    n = float(m[2]) if m[3] is None else (float(m[2]) + float(m[3])) / 2
    if not 0 <= n <= 10 or not n * 4 == round(n * 4):
        raise ValueError("Not a valid quarter line")
    return -n if m[1] == "-" else n


def decimal(raw, hong_kong=False):
    if not re.fullmatch(r"\d+(?:\.\d+)?", raw):
        raise ValueError("Unrecognised decimal price")
    value = float(raw)
    if not 1.01 <= value <= 500:
        raise ValueError("Out of range")
    return round(value - 1, 3) if hong_kong else value


def complete_row(pages):
    for book in pages["eu"]:
        if book not in pages["ah"] or book not in pages["ou"]:
            continue
        try:
            euro, handicap, total = [pages[k][book] for k in ("eu", "ah", "ou")]
            if list(map(len, (euro, handicap, total))) != [6, 8, 6]:
                continue
            result = {"odds_book_id": book}
            for phase, i in (("open", 0), ("live", 1)):
                a, b, c = euro[i * 3:i * 3 + 3]
                h, hp, v, vp = handicap[i * 4:i * 4 + 4]
                g, op, up = total[i * 3:i * 3 + 3]
                if abs(line(h) + line(v)) > 1e-6 or line(g) < .25:
                    raise ValueError("Sides or totals inconsistent")
                result["euro_" + phase] = [decimal(x) for x in (a, b, c)]
                result["asian_" + phase] = [decimal(hp, True), line(h), decimal(vp, True)]
                result["ou_" + phase] = [decimal(op, True), line(g), decimal(up, True)]
            return result
        except ValueError:
            continue
    return None


def markets(page):
    result = {}
    for key, name in TABS.items():
        if key != "eu":
            page.get_by_text(name, exact=True).first.click(timeout=4000)
        result[key] = {}
        rows = page.locator(".oddsBox:has(> .oddsBoxContent)")
        for row in rows.all()[:12]:
            logo = row.locator("img").first.get_attribute("src", timeout=1500) or ""
            book = BOOK.fullmatch(logo)
            if book and row.is_visible():
                result[key][book[1]] = row.locator(".oddsBoxContent").inner_text(timeout=1800).split()
    return complete_row(result)


def event_record(page, league, expected, mid, url, start, end, now):
    scripts = page.locator('script[type="application/ld+json"]').all_text_contents()
    data = [json.loads(x) for x in scripts]
    e = next((x for x in data if isinstance(x, dict) and x.get("@type") == "SportsEvent"), {})
    if e.get("sport") != "Football" or e.get("eventStatus") != "EventScheduled":
        return None
    a = e.get("homeTeam", {}).get("name")
    b = e.get("awayTeam", {}).get("name")
    if (a, b) != expected or a not in NAMES or b not in NAMES:
        return None
    kickoff = dt.datetime.fromisoformat(e["startDate"])
    if kickoff.tzinfo is None or not (start <= kickoff < end and kickoff > now + dt.timedelta(minutes=5)):
        return None
    return {"id": "aiscore-" + mid, "league": league, "home": NAMES[a], "away": NAMES[b],
            "state": 0, "kickoff": kickoff.astimezone(start.tzinfo).isoformat(timespec="minutes"),
            "source_url": url, "odds_provider": "AiScore"}


def collect_backup(browser, start, end, now):
    ctx = browser.new_context(locale="en-US", timezone_id="Asia/Taipei")
    page = ctx.new_page()
    records, diag = [], {}
    try:
        for league, address in LEAGUES.items():
            response = page.goto(BASE + address, wait_until="domcontentloaded", timeout=12000)
            if not response or not response.ok:
                continue
            page.locator('a[itemprop="url"][href*="/match-"]').first.wait_for(timeout=7000)
            found = page.locator('a[itemprop="url"][href*="/match-"]').evaluate_all(r"""els => els.map(a => [
              a.getAttribute('href'), a.innerText.trim().split(/\n+/).map(s=>s.trim()).filter(Boolean)])""")
            dates = {d.strftime("%Y/%m/%d") for d in (start.date(), end.date())}
            candidates = {}
            for path, names in found:
                hit = LINK.fullmatch(path)
                if hit and len(names) >= 3 and names[0] in dates and names[1] in NAMES and names[2] in NAMES:
                    candidates.setdefault(hit[1], (path, (names[1], names[2])))
            for mid, (path, names) in list(candidates.items())[:8]:
                url = BASE + path.rsplit("/", 1)[0] + "/odds"
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=10000)
                    if not response or not response.ok or page.url != url:
                        diag[mid] = "page_unavailable"
                        continue
                    match = event_record(page, league, names, mid, url, start, end, now)
                    if not match:
                        diag[mid] = "fixture_not_verified"
                        continue
                    page.locator(".oddsBoxContent").first.wait_for(timeout=6500)
                    opening = page.get_by_role("checkbox", name="Opening odds")
                    if opening.get_attribute("aria-checked", timeout=3000) != "true":
                        opening.click(timeout=3000)
                    if opening.get_attribute("aria-checked", timeout=3000) != "true":
                        diag[mid] = "opening_column_unavailable"
                        continue
                    data = markets(page)
                    diag[mid] = "complete" if data else "no_single_complete_book"
                    if data:
                        records.append({**match, **data, "odds_checked_at": now.isoformat(timespec="seconds")})
                    if len(records) == 4:
                        return records, diag
                except Exception as exc:
                    diag[mid] = type(exc).__name__
    finally:
        ctx.close()
    return records, diag


def run(start, end, now):
    import shutil
    from playwright.sync_api import sync_playwright
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    options = {"executable_path": chrome} if chrome else {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"], **options)
        try:
            return collect_backup(browser, start, end, now)
        finally:
            browser.close()
