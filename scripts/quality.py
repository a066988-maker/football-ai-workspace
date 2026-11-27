"""Deterministic production QA. Source provenance is checked separately from AI prose.

Never infer an absent injury, fixture, odds or result. An error blocks publishing.
AI can revise its own text, but cannot modify verified source fields.
"""
import datetime as dt
import json
import os
import re
import struct
from pathlib import Path
from slate import ZONE, slate_window

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
IMMUTABLE = ("id", "league", "home", "away", "kickoff", "source_url",
             "odds_checked_at", "asian_open", "asian_live", "euro_live",
             "ou_open", "ou_live", "euro_open", "odds_provider", "odds_book_id")
# No team form, injuries or table positions are supplied by the current feed.
UNSOURCED = re.compile(
    r"伤停|伤缺|伤病|停赛|缺阵|首发|伤情|伤员|复出|主力缺席|"
    r"历史交锋|交锋记录|近[一二三四五六七八九十0-9]+场|"
    r"积分榜|联赛排名|排名第[一二三四五六七八九十0-9]+"
)
TRADITIONAL = re.compile(r"[賽隊讓進預測機會應該強勢優擊對戰關觀獲穩險轉爭盤數兩萬後來貫]")
PNG_SIG = b"\x89PNG\r\n\x1a\n"


def safe_issues(data, originals):
    """Compare every output row to the source before AI content is published."""
    issues = []
    if not isinstance(data, dict) or not isinstance(data.get("matches"), list):
        return ["Analysis JSON has no match list"]
    rows = data["matches"]
    if not 3 <= len(rows) <= 5 or len(rows) != len(originals):
        return ["Match count differs from the 3-5 verified source fixtures"]
    ids = set()
    for i, (m, orig) in enumerate(zip(rows, originals), 1):
        if not isinstance(m, dict) or not isinstance(orig, dict):
            issues.append("match " + str(i) + ": invalid fixture structure")
            continue
        p = "match " + str(i) + ": "
        for field in IMMUTABLE:
            if m.get(field) != orig.get(field):
                issues.append(p + "AI changed original " + field)
        mid = str(m.get("id"))
        if mid in ids:
            issues.append(p + "duplicate match ID")
        ids.add(mid)
        try:
            when = dt.datetime.fromisoformat(m["kickoff"])
            if when.tzinfo is None:
                raise ValueError("missing timezone")
        except (ValueError, TypeError, KeyError):
            issues.append(p + "invalid kickoff timestamp")
        text = m.get("analysis", "")
        if not isinstance(text, str) or len(text.strip()) < 25 or len(text) > 380:
            issues.append(p + "analysis too short, too long, or missing")
            continue
        if UNSOURCED.search(text):
            issues.append(p + "unsupported injuries, form, rankings or H2H claims")
        if TRADITIONAL.search(text):
            issues.append(p + "analysis contains Traditional Chinese characters")
        if re.search(r"包中|稳赚|必胜|100%|绝对命中|保本", text, re.I):
            issues.append(p + "unsupported certainty or guaranteed outcome")
        scores = m.get("scores", [])
        if not isinstance(scores, list) or len(scores) != 3 or not all(isinstance(x, str) for x in scores) or len(set(scores)) != 3:
            issues.append(p + "three distinct scorelines required")
        elif any(not isinstance(score, str) or not re.fullmatch(r"\d{1,2}-\d{1,2}", score) for score in scores):
            issues.append(p + "bad scoreline formatting")
        trend = str(m.get("trend", "")).replace(" ", "")
        mtrend = re.fullmatch(r"(大|小)(\d+(?:\.\d+)?)", trend)
        line = orig.get("ou_live")
        target = line[1] if isinstance(line, list) and len(line) == 3 else None
        if not mtrend or not isinstance(target, (int, float)) or abs(float(mtrend.group(2)) - float(target)) > 1e-6:
            issues.append(p + "recommendation is not source-linked totals line")
        elif isinstance(scores, list) and len(scores) == 3 and all(isinstance(x, str) and re.fullmatch(r"\d{1,2}-\d{1,2}", x) for x in scores):
            goals = sum(map(int, scores[0].split("-")))
            target = float(line[1])
            if (mtrend.group(1) == "大" and goals <= target) or (mtrend.group(1) == "小" and goals >= target):
                issues.append(p + "main score conflicts with totals pick")
    return issues


def full_odds_sop_issues(matches):
    """Publish four upcoming games only with actual opening paired to current."""
    if len(matches) != 4:
        return ["Daily production requires exactly four matches"]
    issues = []
    for i, match in enumerate(matches, 1):
        if not isinstance(match, dict):
            issues.append(f"match {i}: missing market record")
            continue
        opening = match.get("euro_open")
        if not isinstance(opening, list) or len(opening) != 3 or not all(
            type(price) in (int, float) and 1.01 <= price <= 500 for price in opening
        ):
            issues.append(f"match {i}: missing source-labelled opening 1X2 prices")
        # Only the existing AiScore adapter proves matching book identity for
        # both columns in all three markets. Titan's numeric triples do not.
        if match.get("odds_provider") != "AiScore" or not re.fullmatch(
            r"[0-9a-f]{20}", str(match.get("odds_book_id", ""))
        ):
            issues.append(f"match {i}: opening/current bookmaker provenance unverified")
    return issues


def input_issues(source, status, now=None, window=None):
    """Check scope, traceability and freshness before spending a Gemini call."""
    import collect
    import analyze

    now = now or dt.datetime.now(ZONE)
    issues = []
    try:
        matches = analyze.validate_input(source)
    except (ValueError, KeyError, TypeError) as exc:
        return [type(exc).__name__ + ": " + str(exc)[:180]]
    method = status.get("collection_method", "")
    provider = str(source.get("source", ""))
    if method == "aiscore_public_backup":
        if provider != "AiScore public pre-match odds backup" or len(matches) != 4:
            issues.append("AiScore backup requires four fully verified fixtures from the same provider")
    elif method not in ("direct_public_feed", "browser_loaded_public_source", "titan_dated_and_live", "titan_dated_schedule") or not provider.startswith("Titan007"):
        issues.append("Only verified Titan data or the explicitly listed AiScore backup is allowed")
    start, end = window if window is not None else slate_window(now)
    seen = set()
    for i, m in enumerate(matches, 1):
        label = "match " + str(i) + ": "
        mid = str(m["id"])
        if mid in seen:
            issues.append(label + "duplicate match ID")
        seen.add(mid)
        try:
            when = dt.datetime.fromisoformat(m["kickoff"])
            checked = dt.datetime.fromisoformat(m["odds_checked_at"])
            if when.tzinfo is None or not start <= when < end:
                issues.append(label + "kickoff outside the target Taiwan slate")
            if checked.tzinfo is None or abs((now - checked).total_seconds()) > 6 * 3600:
                issues.append(label + "odds timestamp not fresh")
        except (ValueError, TypeError, KeyError):
            issues.append(label + "invalid time fields")
        if not collect.usable_odds({
            k: m.get(k) for k in ("asian_open", "asian_live",
                                   "euro_live", "ou_open", "ou_live")
        }):
            issues.append(label + "odds incomplete or out of range")
    return issues


def asset_issues(data, post_path, png_path):
    issues = []
    if not post_path.is_file():
        issues.append("Simplified-Chinese copy file missing")
    else:
        text = post_path.read_text(encoding="utf-8")
        if len(text) < 200 or "#足球" not in text or "不构成投注建议" not in text:
            issues.append("Post incomplete or missing disclaimer and hashtags")
        for i, m in enumerate(data["matches"], 1):
            if m["home"] not in text or m["away"] not in text:
                issues.append("Post omitted team names for match " + str(i))
            if "趋势：" + m["trend"] not in text:
                issues.append("Post omitted trend for match " + str(i))
            if "比分：" + " / ".join(m["scores"]) not in text:
                issues.append("Post omitted score scripts for match " + str(i))
    if not png_path.is_file():
        issues.append("Vertical PNG missing")
    else:
        raw = png_path.read_bytes()
        if len(raw) < 10_000 or raw[:8] != PNG_SIG or len(raw) < 33:
            issues.append("PNG missing or too small to be a finished poster")
        else:
            width, height = struct.unpack(">II", raw[16:24])
            if (width, height) != (1080, 1920):
                issues.append("Poster dimensions are not 1080x1920")
    return issues


def report(status, checks, errors, attempts=0, repairs=None):
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "checked_at": dt.datetime.now(ZONE).isoformat(timespec="seconds"),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "status": status,
        "checks": checks,
        "errors": errors[:30],
        "ai_attempts": attempts,
        "repairs": (repairs or [])[:12],
        "publish_allowed": status == "passed" and not errors,
    }
    (OUT / "qa_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload
