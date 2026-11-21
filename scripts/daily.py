"""Unattended collection -> Gemini critique/rewrite -> QA -> render/verify -> publish.

No unverified fixtures or stale/malformed assets are marked publishable.
Errors leave machine-readable QA details; transient failures retry at next cron.
"""
import datetime as dt
import json
import os
from pathlib import Path

import analyze
import collect
import notify
import quality
import render
import rules_analysis

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"


def already_complete_today():
    status_path = OUT / "status.json"
    analysis_path = OUT / "analysis.json"
    qa_path = OUT / "qa_report.json"
    poster = OUT / "poster.png"
    copy = OUT / "xiaohongshu.txt"
    if not all(p.is_file() for p in (status_path, analysis_path, qa_path, poster, copy)):
        return False
    try:
        state = json.loads(status_path.read_text(encoding="utf-8"))
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        data = json.loads(analysis_path.read_text(encoding="utf-8"))
        today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
        if state.get("status") != "analysis_ready" or not state.get("window_start", "").startswith(today):
            return False
        if qa.get("status") != "passed" or not qa.get("publish_allowed"):
            return False
        if data.get("self_check", {}).get("independent_ai_review") != "passed":
            return False
        if quality.safe_issues(data, data.get("matches", [])):
            return False
        if quality.asset_issues(data, copy, poster):
            return False
        return True
    except (OSError, ValueError, TypeError, KeyError):
        return False


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if already_complete_today():
        print("Today has already passed all source/AI/assets QA checks. No duplicate delivery.")
        return

    for filename in ("analysis.json", "poster.png", "xiaohongshu.txt", "qa_report.json"):
        (OUT / filename).unlink(missing_ok=True)

    report = collect.collect()
    checks = {
        "fixture_source": "pending",
        "asian_and_total_odds": "pending",
        "gemini_generation": "pending",
        "independent_ai_review": "pending",
        "scores_and_language": "pending",
        "poster_and_copy": "pending",
    }
    errors = []
    repair_log = []
    attempts = 0
    engine = "gemini"

    if report["status"] == "verified_ready_for_ai":
        try:
            source = json.loads(analyze.INPUT.read_text(encoding="utf-8"))
            failures = quality.input_issues(source, report)
            if failures:
                raise ValueError("; ".join(failures[:8]))
            checks["fixture_source"] = "passed"
            checks["asian_and_total_odds"] = "passed"
        except (OSError, ValueError, TypeError) as exc:
            errors.append("Source QA: " + str(exc)[:350])
            report["status"] = "source_quality_failed"
            report["message"] = "Source data could not pass fresh fixture/odds validation."

        if not errors:
            try:
                ai = analyze.main()  # up to 3 Gemini revision rounds with independent AI review
                attempts = ai["attempts"]
                repair_log.extend(ai.get("repair_log", []))
                checks["gemini_generation"] = "passed"
                checks["independent_ai_review"] = ai["ai_review"]
                data = json.loads(analyze.OUTPUT.read_text(encoding="utf-8"))
                failures = quality.safe_issues(data, source["matches"])
                if failures:
                    raise ValueError("; ".join(failures[:8]))
                checks["scores_and_language"] = "passed"
            except Exception as exc:
                # Outage recovery: a clearly labeled rule-based market reading,
                # still backed by the same verified source and deterministic QA.
                gemini_reason = type(exc).__name__ + ": " + str(exc)[:380]
                repair_log.append("Gemini unavailable: " + gemini_reason)
                (OUT / "analysis.json").unlink(missing_ok=True)
                try:
                    fallback = rules_analysis.main(source["matches"])
                    engine = "rules_fallback"
                    attempts = fallback["attempts"]
                    checks["gemini_generation"] = "unavailable_fallback_used"
                    checks["independent_ai_review"] = "not_run_rules_only"
                    data = json.loads(analyze.OUTPUT.read_text(encoding="utf-8"))
                    issues = quality.safe_issues(data, source["matches"])
                    if issues:
                        raise ValueError("; ".join(issues[:8]))
                    checks["scores_and_language"] = "passed_rule_based"
                except Exception as fallback_exc:
                    errors.append("Gemini failure: " + gemini_reason)
                    errors.append("Rules fallback failure: " + type(fallback_exc).__name__ + ": " + str(fallback_exc)[:650])
                    report["status"] = "ai_quality_failed"
                    report["message"] = "Gemini unavailable and verified fallback also failed."
                    (OUT / "analysis.json").unlink(missing_ok=True)

        if not errors:
            for render_attempt in range(1, 3):
                try:
                    render.main()
                    failures = quality.asset_issues(data, OUT / "xiaohongshu.txt",
                                                    OUT / "poster.png")
                    if failures:
                        raise ValueError("; ".join(failures[:8]))
                    checks["poster_and_copy"] = "passed"
                    break
                except Exception as exc:
                    errors.append("Render QA attempt %d: %s: %s" %
                                  (render_attempt, type(exc).__name__, str(exc)[:250]))
            if checks["poster_and_copy"] == "passed":
                # Fixed after verification, not merely after an AI response.
                report["status"] = "analysis_ready" if engine == "gemini" else "analysis_ready_rules"
                report["analysis_engine"] = engine
                report["message"] = (
                    "Gemini self-reviewed analysis, copy and 1080x1920 PNG verified."
                    if engine == "gemini" else
                    "Gemini unavailable: rule-based verified odds analysis, copy and 1080x1920 PNG passed deterministic QA (NOT AI)."
                )
                report["assets"] = ["poster.png", "xiaohongshu.txt"]
                repair_log.extend(errors)
                errors = []  # successful repair is the durable outcome
            else:
                report["status"] = "asset_quality_failed"
                report["message"] = "Image/copy failed two regeneration checks; publishing blocked."
                (OUT / "poster.png").unlink(missing_ok=True)
                (OUT / "xiaohongshu.txt").unlink(missing_ok=True)

    elif report["status"] == "schedule_only_no_titan_odds":
        checks["fixture_source"] = "schedule_only"
        checks["asian_and_total_odds"] = "blocked"
        errors = ["No validated Titan opening/current odds for this schedule. AI deliberately skipped."]
    else:
        checks["fixture_source"] = "unavailable"
        checks["asian_and_total_odds"] = "blocked"
        errors = [report.get("message", "No eligible verified Titan fixture data")]

    qa_status = "passed" if report["status"] in ("analysis_ready", "analysis_ready_rules") else "blocked"
    qa = quality.report(qa_status, checks, errors, attempts, repairs=repair_log)
    report["quality"] = {
        "status": qa["status"],
        "checked_at": qa["checked_at"],
        "ai_attempts": attempts,
        "repairs": len(qa["repairs"]),
        "errors": len(qa["errors"]),
        "publish_allowed": qa["publish_allowed"],
    }
    report["github_run_id"] = os.environ.get("GITHUB_RUN_ID", "")
    report["telegram"] = notify.notify(report["status"])
    report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    (OUT / "status.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Daily pipeline:", report["status"])
    print("QA:", qa["status"], "Gemini attempts:", attempts, "errors:", len(errors))
    print("Window fixtures:", report.get("window_fixture_count", 0))
    print("Verified odds:", report.get("complete_odds_count", 0))


if __name__ == "__main__":
    main()
