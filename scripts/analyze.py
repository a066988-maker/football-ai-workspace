"""Generate Xiaohongshu match analysis only from verified fixture/odds records."""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
import gemini_client

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "verified_matches.json"
OUTPUT = ROOT / "output" / "analysis.json"
FIELDS = ("id", "league", "home", "away", "kickoff", "source_url",
          "odds_checked_at", "asian_open", "asian_live", "euro_live",
          "ou_open", "ou_live")


def validate_input(data):
    matches = data.get("matches", [])
    if not 3 <= len(matches) <= 5:
        raise ValueError("Need 3–5 verified fixtures")
    seen = set()
    for i, item in enumerate(matches, 1):
        missing = [key for key in FIELDS if item.get(key) is None or item.get(key) == ""]
        if missing:
            raise ValueError("Fixture %s missing %s" % (i, missing))
        mid = str(item["id"])
        if mid in seen:
            raise ValueError("Duplicate fixture ID")
        seen.add(mid)
        if str(data.get("source", "")).startswith("AiScore"):
            match = re.fullmatch(r"aiscore-([a-z0-9]{12,22})", mid)
            if (not match or item.get("odds_provider") != "AiScore"
                    or not re.fullmatch(r"[0-9a-f]{20}", str(item.get("odds_book_id", "")))
                    or not re.fullmatch(r"https://m\.aiscore\.com/match-[a-z0-9-]+/" + match[1] + r"/odds",
                                        item["source_url"])
                    or not isinstance(item.get("euro_open"), list)
                    or len(item["euro_open"]) != 3
                    or not all(type(x) in (float, int) and 1.01 <= x <= 500 for x in item["euro_open"])):
                raise ValueError("Invalid AiScore fixture or opening odds provenance")
        elif not re.fullmatch(r"\d{5,10}", mid) or item["source_url"] not in (
                f"https://zq.titan007.com/analysis/{mid}cn.htm",
                f"https://bf.titan007.com/detail/{mid}.htm"):
            raise ValueError("Fixture URL does not match Titan ID")
        for key in ("asian_open", "asian_live", "euro_live", "ou_open", "ou_live"):
            if not isinstance(item[key], list) or len(item[key]) != 3:
                raise ValueError("Incomplete odds: " + key)
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in item[key]):
                raise ValueError("Non-numeric odds: " + key)
        if not 0.25 <= item["ou_live"][1] <= 10:
            raise ValueError("Invalid total goal line")
    return matches


def response_text(result):
    candidates = result.get("candidates") or []
    if not candidates:
        raise ValueError("Gemini returned no candidates")
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(part.get("text", "") for part in parts)
    if not text:
        raise ValueError("Gemini returned no text")
    return text


def gemini(matches, feedback=""):
    instructions = """你是足球数据审核与小红书赛前分析作者。只基于输入注明来源的赛程、欧赔、亚盘、大小球，绝不编造伤停、阵容、交锋、新闻或水位。所有输出必须为简体中文并使用中国大陆常用足球队名，但不要修改输入球队/联赛的客观字段。
输入盘口数组：[左侧赔率,盘口原始数值,右侧赔率]。亚洲盘口的正负号与主客方向尚未独立验证，因此本次推荐方向仅允许使用大小球（"大 X" 或 "小 X"），X必须等于对应比赛ou_live[1]的真实盘口数值；禁止主胜/客胜/平局作为趋势。预测分数需给三个不同的合理剧本，首选比分的总球数需与推荐大小方向不矛盾。结合盘路变化与已提供的欧赔做谨慎分析，不保证准确。分析每场约70-100个简体汉字。只输出JSON对象，结构：{"picks":[{"id":"比赛id原样字符串","analysis":"一段赛前分析","trend":"大 2.5","scores":["2-1","1-2","1-1"]}]}，逐场按输入顺序对应，不要补充其他键。以下为唯一输入数据：
"""
    if feedback:
        instructions += "\n上轮自动审校检测到以下错误，必须在重写时逐项修复，不得改动任何原始盘线、球队名或开球时间：" + feedback[:1200] + "\n"
    parsed, used_model = gemini_client.call(
        instructions + json.dumps(matches, ensure_ascii=False), temperature=0.25
    )
    if not isinstance(parsed, dict):
        raise ValueError("Gemini returned non-object analysis JSON")
    return parsed


def validate_picks(matches, result):
    picks = result.get("picks", [])
    if not isinstance(picks, list) or len(picks) != len(matches):
        raise ValueError("Gemini pick count mismatch")
    merged = []
    for original, pick in zip(matches, picks):
        if str(pick.get("id")) != str(original["id"]):
            raise ValueError("Gemini changed match IDs or order")
        trend = str(pick.get("trend", "")).strip().replace(" ", "")
        match = re.fullmatch(r"(大|小)(\d+(?:\.\d+)?)", trend)
        if not match:
            raise ValueError("Trend must be over/under the actual source line")
        direction, target = match.group(1), float(match.group(2))
        line = float(original["ou_live"][1])
        if abs(target - line) > 1e-6:
            raise ValueError("Gemini invented or changed totals line")
        scores = pick.get("scores")
        if not isinstance(scores, list) or len(scores) != 3 or len(set(scores)) != 3:
            raise ValueError("Need three different score scripts")
        for s in scores:
            if not isinstance(s, str) or not re.fullmatch(r"\d{1,2}-\d{1,2}", s):
                raise ValueError("Invalid score format")
        h, a = map(int, scores[0].split("-"))
        if (direction == "大" and h + a <= line) or (direction == "小" and h + a >= line):
            raise ValueError("First-choice score conflicts with totals recommendation")
        analysis = pick.get("analysis", "")
        if not isinstance(analysis, str) or len(analysis.strip()) < 15:
            raise ValueError("Empty or insufficient analysis")
        combined = {**original, "analysis": analysis.strip(),
                    "trend": direction + " " + str(original["ou_live"][1]).rstrip("0").rstrip(".") if isinstance(original["ou_live"][1], float) else direction + " " + str(original["ou_live"][1]),
                    "scores": scores}
        merged.append(combined)
    return merged


def ai_review(matches, generated):
    """Independent Gemini language/factual-consistency review; never adds odds."""
    instructions = (
        "你是独立的足球事实审校员。只能核对以下【输入盘线数据】与【分析输出】，"
        "没有外部网站访问能力，不得推断伤停、阵容、历史战绩、排名或球队近期表现。"
        "核查是否有：盘口与原始数值不同、赛程球队不符、胜负比分与大小球方向冲突、"
        "分析中凭空捏造事实、繁体中文、大陆球迷不常用的表述、投注保本或必中的承诺。"
        "如果发现问题，列出具体比赛ID和问题。若没有发现问题，返回passed=true。"
        "只能输出JSON对象：{\"passed\":true,\"issues\":[]}。"
        "不要要求输入不存在的事实，也不要修改资料。\n【输入盘线数据】\n"
        + json.dumps(matches, ensure_ascii=False)
        + "\n【分析输出】\n" + json.dumps(generated, ensure_ascii=False)
    )
    review, used_model = gemini_client.call(instructions, temperature=0.0)
    if not isinstance(review, dict) or not isinstance(review.get("passed"), bool):
        raise ValueError("Gemini review returned malformed result")
    issues = review.get("issues", [])
    if not isinstance(issues, list) or any(not isinstance(i, str) for i in issues):
        raise ValueError("Gemini review returned invalid issues")
    return bool(review["passed"]) and not issues, issues


def main():
    if not INPUT.exists():
        raise ValueError("No verified fixture input; analysis skipped")
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    matches = validate_input(data)
    # Three bounded attempts: deterministic checks -> independent Gemini
    # review -> targeted rewrite -> recheck. Provider quota/auth errors stop.
    import quality
    errors = []
    feedback = ""
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            response = gemini(matches, feedback=feedback)
            prepared = validate_picks(matches, response)
            issues = quality.safe_issues({"matches": prepared}, matches)
            if issues:
                raise ValueError("; ".join(issues[:8]))
            passed, issues = ai_review(matches, prepared)
            if not passed:
                raise ValueError("Independent Gemini reviewer: " + "; ".join(issues[:6])
                                 if issues else "Independent Gemini reviewer rejected output")
            result = {
                "source": data["source"],
                "verified_at": data["verified_at"],
                "matches": prepared,
                "self_check": {
                    "attempts": attempt,
                    "rule_validation": "passed",
                    "independent_ai_review": "passed",
                    "model": gemini_client.LAST_WORKING
                },
            }
            OUTPUT.parent.mkdir(exist_ok=True)
            OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print("Analysis double-checked and approved after", attempt, "attempt(s)")
            return {"attempts": attempt, "ai_review": "passed", "repair_log": errors}
        except (ValueError, KeyError, TypeError, IndexError, json.JSONDecodeError) as exc:
            summary = str(exc)[:350]
            errors.append("Attempt %d: %s" % (attempt, summary))
            if any(token in summary for token in ("HTTP 400", "HTTP 401", "HTTP 403", "HTTP 429", "model fallback exhausted")):
                break
            feedback = summary
    OUTPUT.unlink(missing_ok=True)
    raise ValueError("Automatic AI review/rewrite failed: " + " | ".join(errors)[-1100:])


if __name__ == "__main__":
    main()
