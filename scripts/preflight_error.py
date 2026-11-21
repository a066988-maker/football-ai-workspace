"""Persist preflight/setup failures so the Pages dashboard never claims fresh success."""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import quality

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
OUT.mkdir(parents=True, exist_ok=True)
now = dt.datetime.now(ZoneInfo("Asia/Taipei"))
data = {
    "status": "pipeline_preflight_error",
    "updated_at": now.isoformat(timespec="seconds"),
    "window_start": now.replace(hour=16, minute=0, second=0, microsecond=0).isoformat(timespec="minutes"),
    "message": "Daily GitHub Actions dependencies, tests or image-render self-check failed. Review job logs.",
}
# If the daily.py orchestration itself already published its status, preserve it.
current = OUT / "status.json"
try:
    existing = json.loads(current.read_text(encoding="utf-8")) if current.exists() else {}
except (OSError, ValueError):
    existing = {}
if not (existing.get("status") == "analysis_ready" and existing.get("window_start", "").startswith(now.date().isoformat())):
    # This job never publishes yesterday's successful analyses as today's result.
    (OUT / "analysis.json").unlink(missing_ok=True)
    (OUT / "poster.png").unlink(missing_ok=True)
    (OUT / "xiaohongshu.txt").unlink(missing_ok=True)
    current.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    quality.report("blocked", {"pipeline_preflight": "failed"}, [data["message"]])
print("Preflight error marker evaluated.")
