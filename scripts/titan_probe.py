"""Conservative Titan007 connectivity and candidate discovery probe.

Does not infer odds, kickoff date or injury status from snippets.
Outputs unverified candidates for review, never feeds them to AI.
"""
import datetime as dt
import html
import json
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
URLS = [
    "https://www.titan007.com/index.htm",
    "https://zq.titan007.com/",
]
AGENT = "FootballWorkspaceResearch/0.1 (personal research; low-frequency fetch)"

class MatchLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.href = None
        self.label = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href", "")
            self.label = []
    def handle_data(self, data):
        if self.href is not None:
            self.label.append(data)
    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            label = " ".join(" ".join(self.label).split())[:140]
            if self.href and label:
                self.links.append({"href": html.unescape(self.href), "label": label})
            self.href = None
            self.label = []

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=18) as res:
        raw = res.read(2_000_000)
        encoding = res.headers.get_content_charset() or "utf-8"
        try:
            content = raw.decode(encoding)
        except (UnicodeError, LookupError):
            content = raw.decode("gb18030", errors="replace")
        return {"http_status": res.status, "final_url": res.url,
                "bytes": len(raw), "html": content}

def main():
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    report = {"checked_at_utc": now, "source": "Titan007",
              "status": "not_verified", "pages": [], "candidate_links": [],
              "warnings": ["Candidates are NOT validated fixtures; no kickoff, odds, or injury information is asserted."]}
    seen = set()
    for url in URLS:
        entry = {"url": url}
        try:
            r = fetch(url)
            entry.update({k:v for k,v in r.items() if k != "html"})
            parser = MatchLinkParser()
            parser.feed(r["html"])
            entry["link_count"] = len(parser.links)
            entry["has_match_id_patterns"] = bool(re.search(r"(?:analysis/|oddslist/)[0-9]{5,}",r["html"],re.I))
            for link in parser.links:
                match = re.search(r"(?:analysis/|oddslist/)([0-9]{5,})",link["href"],re.I)
                if match and match.group(1) not in seen:
                    seen.add(match.group(1))
                    report["candidate_links"].append({
                        "match_id": match.group(1),
                        "label": link["label"],
                        "source_page": url,
                        "link": link["href"],
                        "verified": False
                    })
        except (OSError, urllib.error.URLError, ValueError) as exc:
            entry["error"] = type(exc).__name__ + ": " + str(exc)[:250]
        report["pages"].append(entry)
    if any(x.get("http_status") == 200 for x in report["pages"]):
        report["status"] = "reachable_unverified"
    report["candidate_count"] = len(report["candidate_links"])
    report["candidate_links"] = report["candidate_links"][:50]
    output = BASE / "output" / "titan_probe.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Probe:",report["status"],"candidate links:",report["candidate_count"])
    for page in report["pages"]:
        print(page["url"],page.get("http_status"),page.get("error",""))
    if report["status"] != "reachable_unverified":
        raise SystemExit("STOP: Titan007 was not reachable; no analysis generated")

if __name__ == "__main__":
    main()
