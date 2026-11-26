"""Persist preflight/setup failures so the Pages dashboard never claims fresh success."""
import datetime as dt
import json
import os
from pathlib import Path
import daily
import quality
from slate import ZONE, slate_window

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)
now = dt.datetime.now(ZONE)
start, end = slate_window(now)
data = {
    "status": "pipeline_preflight_error",
    "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
    "updated_at": now.isoformat(timespec="seconds"),
    "window_start": start.isoformat(timespec="minutes"),
    "window_end": end.isoformat(timespec="minutes"),
    "message": "Daily GitHub Actions dependencies, tests or image-render self-check failed. Review job logs.",
}
# Preserve already-audited deliverables for this slate, including rules fallback.
current = OUT / "status.json"
if not daily.already_complete_slate(now):
    (OUT / "analysis.json").unlink(missing_ok=True)
    (OUT / "poster.png").unlink(missing_ok=True)
    (OUT / "xiaohongshu.txt").unlink(missing_ok=True)
    current.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    quality.report("blocked", {"pipeline_preflight": "failed"}, [data["message"]])
print("Preflight error marker evaluated.")
