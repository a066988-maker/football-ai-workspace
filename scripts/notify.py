"""Optional free Telegram post delivery; never log secrets or bot-token URLs."""
import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"


def send_text(token, chat_id, message):
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message[:4000],
        "disable_web_page_preview": True,
    }, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendMessage",
        data=payload, headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return bool(json.load(response).get("ok"))


def send_png(token, chat_id, path):
    """Use the Bot API's multipart form to deliver the auto-generated actual PNG."""
    boundary = "----football-ai-post-boundary"
    data = path.read_bytes()
    if len(data) > 8_000_000:
        raise ValueError("PNG too large for Telegram image delivery")
    parts = []
    for key, value in (("chat_id", chat_id), ("caption", "今日足球前瞻｜已核实盘口；仅供赛事交流")):
        parts.append(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + key +
                      "\"\r\n\r\n" + value + "\r\n").encode("utf-8"))
    parts.append(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"photo\";" +
                  " filename=\"football-poster.png\"\r\nContent-Type: image/png\r\n\r\n").encode("utf-8"))
    parts.append(data)
    parts.append(("\r\n--" + boundary + "--\r\n").encode("ascii"))
    request = urllib.request.Request(
        "https://api.telegram.org/bot" + token + "/sendPhoto",
        data=b"".join(parts),
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return bool(json.load(response).get("ok"))


def notify(status):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return "not_configured"
    if status != "analysis_ready":
        return "no_verified_analysis_to_send"
    data = json.loads((OUTPUT / "analysis.json").read_text(encoding="utf-8"))
    lines = ["今日足球前瞻（已核实球探盘线）"]
    for i, match in enumerate(data["matches"], 1):
        lines.append(str(i) + ". " + match["league"] + "｜" + match["home"] + " vs " + match["away"])
        lines.append("趋势：" + match["trend"] + "｜比分：" + " / ".join(match["scores"]))
    lines.append("编辑及下载素材：https://a066988-maker.github.io/football-ai-workspace/")
    lines.append("仅供赛事交流，不构成投注建议。")
    try:
        if not send_text(token, chat_id, "\n".join(lines)):
            return "text_rejected"
    except Exception:
        return "text_delivery_error"
    png = OUTPUT / "poster.png"
    if not png.exists():
        return "text_sent_png_missing"
    try:
        return "text_and_png_sent" if send_png(token, chat_id, png) else "text_sent_png_rejected"
    except Exception:
        return "text_sent_png_error"


if __name__ == "__main__":
    report = json.loads((OUTPUT / "status.json").read_text(encoding="utf-8"))
    print("Telegram:", notify(report["status"]))
