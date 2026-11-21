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
    # Keep the first verified result for this local calendar day: later hourly
    # retries cannot overwrite successful analysis with a transient outage.
    status_path = OUT / "status.json"
    analysis_path = OUT / "analysis.json"
    if status_path.exists() and analysis_path.exists():
        try:
            old = json.loads(status_path.read_text(encoding="utf-8"))
            today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
            if old.get("status") == "analysis_ready" and old.get("window_start", "").startswith(today):
                print("Verified daily analysis already published; retry skipped.")
                return
        except (OSError, ValueError):
            pass
    analysis_path.unlink(missing_ok=True)
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
