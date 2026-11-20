"""Optional Telegram delivery. Never print secrets, URLs containing the bot token, or chat IDs."""
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"


def notify(status):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return "not_configured"
    if status != "analysis_ready":
        return "no_verified_analysis_to_send"
    data = json.loads((OUTPUT / "analysis.json").read_text(encoding="utf-8"))
    lines = ["今日足球前瞻（已核实球探数据）"]
    for i, m in enumerate(data["matches"], 1):
        lines.extend([
            str(i) + ". " + m["league"] + "｜" + m["home"] + " vs " + m["away"],
            "趋势：" + m["trend"] + "｜比分：" + " / ".join(m["scores"]),
        ])
    lines.append("查看/编辑图文：https://a066988-maker.github.io/football-ai-workspace/")
    lines.append("仅供赛事交流，不构成投注建议。")
    payload = json.dumps({
        "chat_id": chat_id,
        "text": "\n".join(lines)[:4000],
        "disable_web_page_preview": True,
    }, ensure_ascii=False).encode("utf-8")
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    request = urllib.request.Request(url, data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
        return "sent" if result.get("ok") else "provider_rejected"
    except Exception:
        return "delivery_error"


if __name__ == "__main__":
    report = json.loads((OUTPUT / "status.json").read_text(encoding="utf-8"))
    print("Telegram:", notify(report["status"]))
