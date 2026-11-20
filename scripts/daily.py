"""Daily unattended job. A source/API failure is published as a failure, never fake picks."""
import datetime as dt
import json
from pathlib import Path

import collect
import analyze
import notify

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "analysis.json").unlink(missing_ok=True)
    report = collect.collect()
    if report["status"] == "verified_ready_for_ai":
        try:
            analyze.main()
            report["status"] = "analysis_ready"
            report["message"] = "Titan fixture/odds source validated and Gemini output checked."
        except Exception as exc:
            report["status"] = "ai_error"
            report["message"] = type(exc).__name__ + ": " + str(exc)[:200]
            (OUT / "analysis.json").unlink(missing_ok=True)
    report["telegram"] = notify.notify(report["status"])
    report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    (OUT / "status.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Daily pipeline:", report["status"])
    print("Fixture count:", report.get("window_fixture_count", 0))
    print("Verified odds:", report.get("complete_odds_count", 0))
    # Data unavailable is not a pipeline/programming failure; public status
    # distinguishes it from an analysis with reliable inputs.


if __name__ == "__main__":
    main()
