"""Generate Xiaohongshu match analysis only from verified Titan fixture/odds records."""
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

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
        if not re.fullmatch(r"\d{5,10}", str(item["id"])):
            raise ValueError("Invalid Titan match ID")
        if item["id"] in seen:
            raise ValueError("Duplicate fixture ID")
        seen.add(item["id"])
        if item["source_url"] != "https://zq.titan007.com/analysis/" + str(item["id"]) + "cn.htm":
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


def gemini(matches):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY repository secret is unavailable")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    if not re.fullmatch(r"gemini-[\w.\-]+", model):
        raise ValueError("Invalid model")
    instructions = """你是足球数据审核与小红书赛前分析作者。只基于输入的Titan007赛程、欧赔、亚盘、大小球，绝不编造伤停、阵容、交锋、新闻或水位。所有输出必须为简体中文并使用中国大陆常用足球队名，但不要修改输入球队/联赛的客观字段。
输入盘口数组：[左侧赔率,盘口原始数值,右侧赔率]。亚洲盘口的正负号与主客方向尚未独立验证，因此本次推荐方向仅允许使用大小球（"大 X" 或 "小 X"），X必须等于对应比赛ou_live[1]的真实盘口数值；禁止主胜/客胜/平局作为趋势。预测分数需给三个不同的合理剧本，首选比分的总球数需与推荐大小方向不矛盾。结合盘路变化与已提供的欧赔做谨慎分析，不保证准确。分析每场约70-100个简体汉字。只输出JSON对象，结构：{"picks":[{"id":"比赛id原样字符串","analysis":"一段赛前分析","trend":"大 2.5","scores":["2-1","1-2","1-1"]}]}，逐场按输入顺序对应，不要补充其他键。以下为唯一输入数据：
"""
    payload = json.dumps({
        "contents": [{"parts": [{"text": instructions + json.dumps(matches, ensure_ascii=False)}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.25}
    }, ensure_ascii=False).encode("utf-8")
    url = "https://generativelanguage.googleapis.com/v1beta/models/" + model + ":generateContent"
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as reply:
            result = json.load(reply)
    except urllib.error.HTTPError as exc:
        # Never print API keys or entire provider payloads.
        raise ValueError("Gemini HTTP %s (quota, credentials or model issue)" % exc.code) from exc
    return json.loads(response_text(result))


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


def main():
    if not INPUT.exists():
        raise ValueError("No verified fixture input; analysis skipped")
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    matches = validate_input(data)
    response = gemini(matches)
    result = {"source": data["source"], "verified_at": data["verified_at"],
              "matches": validate_picks(matches, response)}
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Verified analysis written for", len(result["matches"]), "matches")


if __name__ == "__main__":
    main()
