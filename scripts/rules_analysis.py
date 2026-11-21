"""Offline deterministic fallback when all Gemini routes are unavailable.

Uses ONLY independently verified Titan match/odds inputs. This is not AI and
must be labeled as a rules-based pre-match observation in every output.
"""
import json
from pathlib import Path

import analyze
import quality

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "analysis.json"


def simple_number(n):
    return ("%g" % float(n))


def rank_side(euro):
    home, draw, away = euro
    # Compare actual 1X2 prices only; no invented results or team form.
    if home <= min(draw, away):
        return "home"
    if away <= min(home, draw):
        return "away"
    return "draw"


def scores_for(direction, line, side):
    # Generate a realistic cluster near the observed market total, then
    # reject scenarios that contradict the nominated totals direction.
    candidates = []
    for home in range(0, 6):
        for away in range(0, 6):
            goals = home + away
            if direction == "大" and goals <= line:
                continue
            if direction == "小" and goals >= line:
                continue
            preferred = (home > away if side == "home" else
                         home < away if side == "away" else home == away)
            # Minimize distance from total line, prefer the favored side;
            # make scores conservative rather than using extreme 5-5 scorelines.
            target = line + (0.65 if direction == "大" else -0.65)
            rank = (not preferred, abs(goals - target), goals,
                    abs(home-away), home, away)
            candidates.append((rank, f"{home}-{away}"))
    candidates.sort(key=lambda row: row[0])
    picks = []
    for _, score in candidates:
        if score not in picks:
            picks.append(score)
        if len(picks) >= 3:
            return picks
    raise ValueError("Unable to create three internally consistent score scenarios")


def pick_market(match):
    opening = match["ou_open"]
    live = match["ou_live"]
    old_line, line = float(opening[1]), float(live[1])
    if line > old_line:
        direction = "大"
        rationale = "大小球从%s球调整至%s球，盘线向上" % (simple_number(old_line), simple_number(line))
    elif line < old_line:
        direction = "小"
        rationale = "大小球从%s球调整至%s球，盘线向下" % (simple_number(old_line), simple_number(line))
    elif float(live[0]) + 0.04 < float(live[2]):
        direction = "大"
        rationale = "大小球维持%s球，大球一侧水位相对较低" % simple_number(line)
    elif float(live[2]) + 0.04 < float(live[0]):
        direction = "小"
        rationale = "大小球维持%s球，小球一侧水位相对较低" % simple_number(line)
    else:
        # Even without a price edge, produce a low-confidence directional
        # scenario while explicitly labeling it as a weak statistical signal.
        direction = "小"
        rationale = "大小球维持%s球，双方水位接近，方向信号偏弱" % simple_number(line)
    return direction, rationale


def build(matches):
    originals = analyze.validate_input({"matches": matches})
    out = []
    for match in originals:
        direction, rationale = pick_market(match)
        side = rank_side(match["euro_live"])
        home, draw, away = [simple_number(v) for v in match["euro_live"]]
        scores = scores_for(direction, float(match["ou_live"][1]), side)
        analysis = (
            "%s。即时欧赔主胜%s、平局%s、客胜%s，"
            "价格仅代表当前市场报价，不能直接当作赛果概率。"
            "依已取得的盘线和水位制作%s球方向的情景推演，"
            "没有核实阵容或伤停，因此不作相关判断。"
            "此为规则模型的赛前观察，不是人工智能生成，也无法保证命中。"
        ) % (rationale, home, draw, away, direction)
        # Wording on unavailable injury context is factual self-limitation, not
        # a claim that a particular player is injured.
        analysis = analysis.replace("没有核实阵容或伤停，因此不作相关判断。",
                                    "未获得阵容及人员资料，不对这些因素下结论。")
        out.append({
            **match, "trend": direction + " " + simple_number(match["ou_live"][1]),
            "scores": scores, "analysis": analysis,
        })
    result = {
        "source": "Titan007 live public football feed",
        "verified_at": matches[0]["odds_checked_at"],
        "matches": out,
        "analysis_engine": "rules_fallback",
        "headline_disclosure": "盘口规则分析，非 Gemini AI 生成",
        "self_check": {"rule_validation": "passed", "independent_ai_review": "unavailable",
                       "attempts": 0, "model": None},
    }
    issues = quality.safe_issues(result, originals)
    if issues:
        raise ValueError("Rules fallback quality failure: " + "; ".join(issues[:6]))
    return result


def main(matches):
    result = build(matches)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Published verified deterministic-rule analysis for", len(result["matches"]), "matches")
    return {"attempts": 0, "ai_review": "unavailable", "engine": "rules_fallback"}


if __name__ == "__main__":
    source = json.loads(analyze.INPUT.read_text(encoding="utf-8"))
    main(source["matches"])
