"""Analyze user-verified match data with Gemini. No invented fixtures or odds."""
import json, os, sys, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "verified_matches.json"
OUTPUT = ROOT / "output" / "analysis.json"
REQUIRED = ("league","home","away","kickoff","source_url","odds_checked_at","asian_open","asian_live","euro_live","ou_open","ou_live","analysis")

def main():
    if not INPUT.exists():
        raise SystemExit("STOP: data/verified_matches.json missing. No fixtures were invented.")
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    matches = data.get("matches", [])
    if not 3 <= len(matches) <= 5:
        raise SystemExit("STOP: exactly 3–5 verified fixtures required")
    for i, m in enumerate(matches, 1):
        missing = [k for k in REQUIRED if not m.get(k)]
        if missing or not str(m.get("source_url","")).startswith("https://"):
            raise SystemExit(f"STOP: fixture {i} missing verified fields: {missing}")
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("STOP: GEMINI_API_KEY secret missing")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    prompt = """你是足球賽事資料審核與分析助理。只使用下列提供的已核實資料，不得聲稱自己已瀏覽網站，不得編造賽程、盤口、傷停、新聞或概率。資料不足時明確標記資料不足。輸出純 JSON，結構為 {matches:[{league,home,away,kickoff,source_url,odds_checked_at,asian_open,asian_live,euro_live,ou_open,ou_live,analysis,trend,scores}]}，保留輸入賽事與來源欄位原值，analysis 使用簡體中文，trend 必須是亞洲讓球盤或大小球方向，格式如「主队 -0.5」或「大 2.5」，盤口數值必須直接來自輸入已驗證的 asian_live 或 ou_live，不得自行推定。scores 是三個如 1-0 的比分，按可能性排序。禁止投注保證語。輸入：\n""" + json.dumps(data, ensure_ascii=False)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = json.dumps({"contents":[{"parts":[{"text":prompt}]}],"generationConfig":{"responseMimeType":"application/json","temperature":0.2}}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json","x-goog-api-key":key}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            result = json.load(response)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Gemini API failed HTTP {e.code}: {e.read().decode()[:300]}")
    answer = result["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(answer)
    generated = parsed.get("matches",[])
    if len(generated) != len(matches):
        raise SystemExit("STOP: output fixture count mismatch")
    for i,(original,m) in enumerate(zip(matches,generated),1):
        for field in ("league","home","away","kickoff","source_url","odds_checked_at","asian_open","asian_live","euro_live","ou_open","ou_live"):
            if m.get(field) != original.get(field):
                raise SystemExit(f"STOP: AI modified source field {field} in fixture {i}")
        scores=m.get("scores",[])
        if len(scores)!=3:
            raise SystemExit(f"STOP: fixture {i} must have three scores")
        try:
            h,a=map(int,scores[0].split("-"))
        except (ValueError,AttributeError):
            raise SystemExit(f"STOP: invalid score fixture {i}")
        if not all(isinstance(score,str) and __import__("re").fullmatch(r"\d{1,2}-\d{1,2}",score) for score in scores):
            raise SystemExit(f"STOP: invalid scores fixture {i}")
        trend=str(m.get("trend","")).strip()
        if not trend or trend in ("主勝","客勝","平局"):
            raise SystemExit(f"STOP: fixture {i} trend must be Asian handicap or over/under")
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(parsed,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Output:", OUTPUT)

if __name__ == "__main__":
    main()
