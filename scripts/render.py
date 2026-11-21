"""Produce real PNG and copyable Simplified Chinese Xiaohongshu copy automatically.

Only called after both the source-odds and AI-response validators succeeded.
Canvas is rendered by locally installed headless Chrome; no external image API.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
DATA = OUT / "analysis.json"


def post_text(data):
    matches = data["matches"]
    if not 3 <= len(matches) <= 5:
        raise ValueError("Poster requires three to five verified analyzed fixtures")
    first = matches[0]
    title = first["home"] + "坐镇，" + first["away"] + "迎战：盘路暗藏哪些变化？"
    lines = [title, "", "先看盘口变化，再谈比赛剧本。临场水位随时可能调整，以下仅作赛前交流。", ""]
    for i, match in enumerate(matches, 1):
        lines.extend([
            "【%d｜%s】%s vs %s" % (i, match["league"], match["home"], match["away"]),
            "开球：" + match["kickoff"][5:16].replace("T", " "),
            match["analysis"].strip(),
            "趋势：" + match["trend"],
            "比分：" + " / ".join(match["scores"]),
            "",
        ])
    lines.extend(["仅供赛事交流，不构成投注建议。", "#足球 #足球分析 #赛事前瞻"])
    return "\n".join(lines)


CANVAS_SCRIPT = r"""
(data) => {
  const canvas = document.querySelector('canvas');
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height;
  ctx.fillStyle = '#0c1525';
  ctx.fillRect(0, 0, W, H);
  const f = (px, weight=700) => {
    ctx.font = weight + ' ' + px + 'px "Noto Sans CJK SC","Noto Sans SC","Microsoft YaHei",sans-serif';
  };
  function drawFit(t, x, y, max, size, color) {
    t = String(t);
    f(size);
    while (ctx.measureText(t).width > max && size > 22) f(size-=2);
    ctx.fillStyle = color;
    ctx.fillText(t, x, y);
  }
  ctx.fillStyle = '#68e4b4';
  ctx.fillRect(50, 55, 6, 126);
  const first = data.matches[0];
  drawFit(first.kickoff.slice(0,10).replace(/-/g,'/'),82,107,900,40,'#68e4b4');
  drawFit(first.home+'坐镇，'+first.away+'迎战',68,179,940,58,'#f3f9fa');
  const n=data.matches.length, start=229, per=1440/n;
  data.matches.forEach((m,i) => {
    const y=start+i*per;
    ctx.fillStyle=i%2?'#162940':'#20354e';
    ctx.beginPath();
    ctx.roundRect(42,y,995,per-19,16);
    ctx.fill();
    drawFit(m.league+'  '+m.kickoff.slice(5,16).replace('T',' '),73,y+60,905,33,'#69e5b9');
    drawFit(m.home+' VS '+m.away,73,y+129,910,48,'#eff7fc');
    drawFit('比分 '+m.scores.join(' / '),73,y+189,906,35,'#dbe7f3');
    drawFit('趋势 '+m.trend,73,y+243,900,37,'#fbd18b');
  });
  drawFit('赛前盘口观察 · 理性交流',65,1765,930,37,'#c2d4e0');
  drawFit('仅供赛事交流，不构成投注建议',65,1842,930,31,'#91abc0');
}
"""


def render_png(data, destination):
    from playwright.sync_api import sync_playwright
    import shutil

    with sync_playwright() as playwright:
        chrome = shutil.which("google-chrome") or shutil.which("chromium")
        kwargs = {"executable_path": chrome} if chrome else {}
        browser = playwright.chromium.launch(headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"], **kwargs)
        try:
            page = browser.new_page(viewport={"width": 1150, "height": 2100}, device_scale_factor=1)
            page.set_content('<!doctype html><html><head><meta charset="utf-8"><style>body{margin:0;background:#0c1525}canvas{display:block}</style></head><body><canvas width="1080" height="1920"></canvas></body></html>')
            page.evaluate(CANVAS_SCRIPT, data)
            page.locator("canvas").screenshot(path=str(destination))
        finally:
            browser.close()


def main():
    if not DATA.exists():
        raise ValueError("No validated Gemini analysis exists")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    if not 3 <= len(data.get("matches", [])) <= 5:
        raise ValueError("Refusing to render an empty or incomplete analysis")
    OUT.mkdir(exist_ok=True)
    (OUT / "xiaohongshu.txt").write_text(post_text(data), encoding="utf-8")
    render_png(data, OUT / "poster.png")
    print("Produced verified-analysis Xiaohongshu copy and PNG (1080x1920).")


def selftest():
    """Render dummy test-only matches; never publish sample matches as predictions."""
    import struct
    import tempfile
    fixture = {
        "league": "测试联赛", "home": "甲队", "away": "乙队",
        "kickoff": "2026-11-21T20:30+08:00",
        "scores": ["2-1", "1-0", "2-0"], "trend": "大 2.5",
        "analysis": "仅用于排版测试的虚构文字，不能用于赛事推荐。",
    }
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "test-poster.png"
        render_png({"matches": [fixture] * 3}, path)
        raw = path.read_bytes()
        if raw[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError("PNG generation failed")
        dimensions = struct.unpack(">II", raw[16:24])
        if dimensions != (1080, 1920):
            raise RuntimeError("PNG dimensions incorrect: " + str(dimensions))
        print("Render browser selftest:", dimensions)


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
