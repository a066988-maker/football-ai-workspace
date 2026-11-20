"""Titan007 stage-2 diagnostic: inspect a small sample of match-detail pages.

Untrusted page text is evidence, not a verified fixture. No AI calls.
"""
import datetime as dt
import html
import json
import re
import urllib.parse
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = "https://www.titan007.com/index.htm"
MAX_DETAIL_PAGES = 3
ALLOWED_HOSTS = {"www.titan007.com", "titan007.com", "vip.titan007.com", "zq.titan007.com"}
UA = "FootballWorkspaceResearch/0.2 (low-frequency diagnostic)"

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links=[]
        self.href=None
        self.parts=[]
        self.title=False
        self.title_parts=[]
    def handle_starttag(self,tag,attrs):
        if tag=="a":
            self.href=dict(attrs).get("href","")
            self.parts=[]
        if tag=="title":
            self.title=True
    def handle_data(self,data):
        if self.href is not None:
            self.parts.append(data)
        if self.title:
            self.title_parts.append(data)
    def handle_endtag(self,tag):
        if tag=="a" and self.href is not None:
            self.links.append({"href":self.href,"text":" ".join(" ".join(self.parts).split())[:160]})
            self.href=None
        if tag=="title":
            self.title=False

def request(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html"})
    with urllib.request.urlopen(req,timeout=18) as res:
        raw=res.read(1_500_000)
        charset=res.headers.get_content_charset()
        # Titan007 pages can use GBK even when no charset header is present.
        if not charset:
            m=re.search(br"charset\s*=\s*['\"]?([\w-]+)",raw[:5000],re.I)
            charset=m.group(1).decode("ascii","ignore") if m else "gb18030"
        try:
            content=raw.decode(charset,errors="replace")
        except LookupError:
            content=raw.decode("gb18030",errors="replace")
        return {"status":res.status,"url":res.url,"html":content,"bytes":len(raw)}

def candidate_urls(index_html):
    parser=Links()
    parser.feed(index_html)
    found={}
    for link in parser.links:
        url=urllib.parse.urljoin(INDEX,html.unescape(link["href"]))
        parsed=urllib.parse.urlparse(url)
        if parsed.scheme not in ("https","http") or parsed.hostname not in ALLOWED_HOSTS:
            continue
        m=re.search(r"(?:analysis/|oddslist/)(\d{5,})",parsed.path,re.I)
        if not m:
            continue
        found.setdefault(m.group(1),{"match_id":m.group(1),"url":url,"link_label":link["text"]})
    return list(found.values())

def summarize(candidate):
    item={**candidate,"verified":False}
    try:
        response=request(candidate["url"])
        parser=Links()
        parser.feed(response["html"])
        title=" ".join(" ".join(parser.title_parts).split())
        plain=re.sub(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>"," ",response["html"],flags=re.I|re.S)
        plain=re.sub(r"<[^>]+>"," ",plain)
        plain=html.unescape(plain)
        plain=" ".join(plain.split())
        item.update({"http_status":response["status"],"final_url":response["url"],
                     "page_title":title[:200],"html_bytes":response["bytes"],
                     "visible_text_excerpt":plain[:600],
                     "has_asian_keywords":bool(re.search("亚盘|亞盤|让球|讓球",plain)),
                     "has_euro_keywords":bool(re.search("欧赔|歐賠|胜平负|勝平負",plain)),
                     "has_ou_keywords":bool(re.search("大小球|进球数|進球數",plain))})
    except (OSError,ValueError) as e:
        item["error"]=type(e).__name__+": "+str(e)[:250]
    return item

def main():
    report={"checked_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),
            "source":INDEX,"status":"unverified","detail_pages":[],"candidate_count":0,
            "note":"Page titles, text excerpts and keyword flags are diagnostics only; no odds or fixture has been validated."}
    try:
        response=request(INDEX)
        report["index_status"]=response["status"]
        candidates=candidate_urls(response["html"])
        parser=Links()
        parser.feed(response["html"])
        report["total_anchor_links"]=len(parser.links)
        report["link_samples"]=[{"href":link["href"][:240],"label":link["text"][:100]} for link in parser.links[:80]]
        report["numeric_link_samples"]=[{"href":link["href"][:240],"label":link["text"][:100]} for link in parser.links if re.search(r"\d{5,}",link["href"])][:60]
        report["football_link_samples"]=[{"href":link["href"][:240],"label":link["text"][:100]} for link in parser.links if re.search(r"analysis|odds|match|live|detail|football|score|亚盘|欧赔",link["href"]+" "+link["text"],re.I)][:60]
        report["matching_raw_links"]=[link for link in parser.links if re.search(r"(?:analysis/|oddslist/)\\d{5,}",link["href"],re.I)][:12]
        report["matching_raw_count"]=sum(bool(re.search(r"(?:analysis/|oddslist/)\\d{5,}",link["href"],re.I)) for link in parser.links)
        report["raw_html_match_count"]=len(re.findall(r"(?:analysis/|oddslist/)\\d{5,}",response["html"],re.I))
        report["candidate_count"]=len(candidates)
        for candidate in candidates[:MAX_DETAIL_PAGES]:
            report["detail_pages"].append(summarize(candidate))
        report["status"]="sampled" if report["detail_pages"] else "no_detail_candidates"
    except (OSError,ValueError) as e:
        report["error"]=type(e).__name__+": "+str(e)[:250]
    output=ROOT/"output"/"titan_details_diagnostic.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print("Status:",report["status"])
    print("Candidate IDs:",report["candidate_count"])
    for item in report["detail_pages"]:
        print("ID:",item["match_id"],"HTTP:",item.get("http_status"),"Title:",item.get("page_title","")[:90],"Error:",item.get("error",""))
    if report["status"]!="sampled":
        print("DIAGNOSTIC ONLY: no detail pages sampled; see artifact for raw link examples")
if __name__=="__main__":
    main()
