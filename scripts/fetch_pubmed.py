#!/usr/bin/env python3
"""
Emergency Medicine Weekly — PubMed 每週抓取腳本

只使用 Python 標準函式庫（不需 pip install）。
預設抓取「執行日前 7 天」(週一執行 → 上週一至週日) 新收錄於 PubMed 的文章，
依 12 個急診次專科分類，輸出：
    data/weeks/<週一日期>.json   當週文章
    data/index.json              週次清單（網頁用）

用法：
    python scripts/fetch_pubmed.py                       # 預設：前 7 天
    python scripts/fetch_pubmed.py --start 2026/11/09 --end 2026/11/15 --label 2026-11-16

環境變數（可選，建議設定以提高速率上限）：
    NCBI_API_KEY   NCBI API key
    NCBI_EMAIL     聯絡 email（NCBI 建議提供）
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEEKS = DATA / "weeks"

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
API_KEY = os.environ.get("NCBI_API_KEY", "").strip()
EMAIL = os.environ.get("NCBI_EMAIL", "").strip()
OPENALEX_KEY = os.environ.get("OPENALEX_API_KEY", "").strip()
OPENALEX = "https://api.openalex.org/sources"
METRICS = DATA / "journal_metrics.json"
TOOL = "em-weekly"
DELAY = 0.12 if API_KEY else 0.4  # NCBI: 10 req/s with key, 3 req/s without
TZ = dt.timezone(dt.timedelta(hours=8))  # Asia/Taipei

# --------------------------------------------------------------------------
# 查詢條件
# 注意：剛上線的新文章多半尚未有 MeSH 索引，因此每類都以 [tiab] 關鍵字為主，
# MeSH 只作輔助。
# --------------------------------------------------------------------------
def ta(*names: str) -> str:
    return "(" + " OR ".join(f'"{n}"[ta]' for n in names) + ")"


EM_JOURNALS = ta(
    "Ann Emerg Med", "Acad Emerg Med", "Am J Emerg Med", "Emerg Med J",
    "J Emerg Med", "Resuscitation", "Scand J Trauma Resusc Emerg Med",
    "West J Emerg Med", "Eur J Emerg Med", "CJEM", "Emerg Med Australas",
    "Intern Emerg Med", "Prehosp Emerg Care", "Pediatr Emerg Care",
    "J Am Coll Emerg Physicians Open", "BMC Emerg Med",
    "Emerg Med Clin North Am", "Clin Exp Emerg Med", "AEM Educ Train",
    "Int J Emerg Med", "Emerg Med Int", "Turk J Emerg Med",
)

EMERG_CTX = (
    "(" + EM_JOURNALS + " OR "
    '"Emergency Medicine"[mh] OR "Emergency Service, Hospital"[mh] OR '
    '"Emergency Medical Services"[mh] OR '
    '"emergency department*"[tiab] OR "emergency room*"[tiab] OR '
    '"emergency medicine"[tiab] OR "emergency physician*"[tiab] OR '
    '"emergency care"[tiab] OR "emergency unit*"[tiab] OR '
    "prehospital[tiab] OR \"pre-hospital\"[tiab])"
)


def topic(terms: str, extra_journals: str | None = None, standalone: str | None = None) -> str:
    """(terms AND emergency context) OR 專科期刊 OR 不需急診脈絡的專屬詞"""
    parts = [f"(({terms}) AND {EMERG_CTX})"]
    if extra_journals:
        parts.append(extra_journals)
    if standalone:
        parts.append(f"({standalone})")
    return "(" + " OR ".join(parts) + ")"


CATEGORIES: list[dict] = [
    {
        "id": "general",
        "name": "General Emergency Medicine",
        "zh": "一般急診醫學",
        "query": EM_JOURNALS,
    },
    {
        "id": "critical",
        "name": "Emergency Critical Care",
        "zh": "急診重症",
        "query": topic(
            '"critical care"[tiab] OR "critically ill"[tiab] OR resuscitat*[tiab] OR '
            'sepsis[tiab] OR septic[tiab] OR shock[tiab] OR "cardiac arrest"[tiab] OR '
            '"mechanical ventilation"[tiab] OR intubat*[tiab] OR "airway management"[tiab] OR '
            'vasopressor*[tiab] OR ECMO[tiab] OR "extracorporeal"[tiab] OR '
            '"respiratory failure"[tiab] OR "Critical Care"[mh] OR "Critical Illness"[mh] OR '
            '"Heart Arrest"[mh] OR "Cardiopulmonary Resuscitation"[mh] OR "Shock"[mh] OR "Sepsis"[mh]',
            extra_journals=ta("Resuscitation", "Resusc Plus"),
        ),
    },
    {
        "id": "pediatric",
        "name": "Pediatric Emergency Medicine",
        "zh": "兒童急診",
        "query": topic(
            "pediatric*[tiab] OR paediatric*[tiab] OR child*[tiab] OR infant*[tiab] OR "
            "neonat*[tiab] OR toddler*[tiab] OR adolescen*[tiab]",
            extra_journals=ta("Pediatr Emerg Care"),
        ),
    },
    {
        "id": "ems",
        "name": "Emergency Medical Services (EMS)",
        "zh": "到院前緊急醫療",
        "query": "("
        'prehospital[tiab] OR "pre-hospital"[tiab] OR "out-of-hospital"[tiab] OR '
        'paramedic*[tiab] OR ambulance*[tiab] OR "emergency medical service*"[tiab] OR '
        '"emergency medical technician*"[tiab] OR "dispatch*"[tiab] OR "HEMS"[tiab] OR '
        '"Emergency Medical Services"[mh:noexp] OR "Emergency Medical Technicians"[mh] OR '
        '"Ambulances"[mh] OR "Air Ambulances"[mh] OR '
        + ta("Prehosp Emerg Care", "Air Med J")
        + ")",
    },
    {
        "id": "toxicology",
        "name": "Medical Toxicology",
        "zh": "臨床毒物",
        "query": topic(
            "poison*[tiab] OR overdos*[tiab] OR intoxicat*[tiab] OR envenom*[tiab] OR "
            "antidote*[tiab] OR toxidrome*[tiab] OR ingestion*[tiab] OR "
            '"substance use"[tiab] OR opioid*[tiab] OR naloxone[tiab] OR toxicolog*[tiab] OR '
            '"Poisoning"[mh] OR "Drug Overdose"[mh] OR "Antidotes"[mh]',
            extra_journals=ta("Clin Toxicol (Phila)", "J Med Toxicol"),
        ),
    },
    {
        "id": "ultrasound",
        "name": "Emergency Ultrasound",
        "zh": "急診超音波",
        "query": topic(
            "ultraso*[tiab] OR sonograph*[tiab] OR echocardiograph*[tiab] OR "
            '"Ultrasonography"[mh]',
            extra_journals=ta("Ultrasound J", "Crit Ultrasound J"),
            standalone='"point-of-care ultrasound"[tiab] OR "point of care ultrasound"[tiab] OR '
            'POCUS[tiab] OR "bedside ultrasound"[tiab] OR '
            '"focused assessment with sonography"[tiab] OR "eFAST"[tiab]',
        ),
    },
    {
        "id": "disaster",
        "name": "Disaster Medicine",
        "zh": "災難醫學",
        "query": topic(
            "disaster*[tiab] OR earthquake*[tiab] OR flood*[tiab] OR hurricane*[tiab] OR "
            "typhoon*[tiab] OR terror*[tiab] OR pandemic*[tiab] OR surge[tiab] OR "
            '"Disasters"[mh] OR "Disaster Planning"[mh] OR "Civil Defense"[mh]',
            extra_journals=ta("Prehosp Disaster Med", "Disaster Med Public Health Prep"),
            standalone='"mass casualt*"[tiab] OR "mass-casualt*"[tiab] OR "mass gathering*"[tiab] OR '
            '"Mass Casualty Incidents"[mh] OR "disaster medicine"[tiab]',
        ),
    },
    {
        "id": "hyperbaric",
        "name": "Hyperbaric and Undersea Medicine",
        "zh": "高壓氧與潛水醫學",
        "query": "("
        'hyperbaric[tiab] OR "decompression sickness"[tiab] OR "decompression illness"[tiab] OR '
        '"arterial gas embolism"[tiab] OR scuba[tiab] OR divers[tiab] OR "diving"[tiab] OR '
        '"carbon monoxide poisoning"[tiab] OR "Hyperbaric Oxygenation"[mh] OR '
        '"Decompression Sickness"[mh] OR "Diving"[mh] OR "Carbon Monoxide Poisoning"[mh] OR '
        + ta("Undersea Hyperb Med", "Diving Hyperb Med")
        + ")",
    },
    {
        "id": "sports",
        "name": "Sports Medicine",
        "zh": "運動醫學",
        "query": topic(
            "athlet*[tiab] OR sport*[tiab] OR concussion*[tiab] OR exercise[tiab] OR "
            '"Athletic Injuries"[mh] OR "Brain Concussion"[mh] OR "Sports"[mh]',
            extra_journals=ta("Br J Sports Med", "Clin J Sport Med", "Curr Sports Med Rep"),
            standalone='"exertional heat stroke"[tiab] OR "return to play"[tiab] OR '
            '"sudden cardiac arrest in athlete*"[tiab]',
        ),
    },
    {
        "id": "geriatric",
        "name": "Geriatric Emergency Medicine",
        "zh": "老人急診",
        "query": topic(
            'geriatric*[tiab] OR "older adult*"[tiab] OR "older patient*"[tiab] OR '
            'elderly[tiab] OR "older people"[tiab] OR "older person*"[tiab] OR '
            '"nursing home*"[tiab] OR "long-term care"[tiab] OR frail*[tiab] OR delirium[tiab] OR '
            "dementia[tiab] OR falls[tiab] OR "
            '"Geriatric Assessment"[mh] OR "Frail Elderly"[mh] OR "Geriatrics"[mh]',
        ),
    },
    {
        "id": "neurology",
        "name": "Emergency Neurology",
        "zh": "急診神經學",
        "query": topic(
            "stroke[tiab] OR seizure*[tiab] OR \"status epilepticus\"[tiab] OR headache*[tiab] OR "
            "vertigo[tiab] OR dizziness[tiab] OR thrombolys*[tiab] OR "
            '"endovascular thrombectomy"[tiab] OR "large vessel occlusion"[tiab] OR '
            'subarachnoid[tiab] OR "intracerebral hemorrhage"[tiab] OR '
            '"intracranial hemorrhage"[tiab] OR meningitis[tiab] OR encephalitis[tiab] OR '
            '"altered mental status"[tiab] OR "transient ischemic attack"[tiab] OR '
            '"Stroke"[mh] OR "Seizures"[mh] OR "Status Epilepticus"[mh] OR "Headache"[mh] OR '
            '"Vertigo"[mh] OR "Intracranial Hemorrhages"[mh]',
        ),
    },
    {
        "id": "trauma",
        "name": "Emergency Trauma Medicine",
        "zh": "急診外傷",
        "query": topic(
            "trauma[tiab] OR traumatic[tiab] OR injuries[tiab] OR injured[tiab] OR "
            "fracture*[tiab] OR polytrauma[tiab] OR \"massive transfusion\"[tiab] OR "
            'REBOA[tiab] OR "hemorrhage control"[tiab] OR "haemorrhage control"[tiab] OR '
            "tourniquet*[tiab] OR gunshot*[tiab] OR firearm*[tiab] OR burn*[tiab] OR "
            '"motor vehicle"[tiab] OR "Wounds and Injuries"[mh] OR "Trauma Centers"[mh]',
            extra_journals=ta(
                "J Trauma Acute Care Surg", "Injury", "Eur J Trauma Emerg Surg",
                "World J Emerg Surg", "Trauma Surg Acute Care Open",
            ),
        ),
    },
]

EXCLUDE_PT = (
    "NOT (letter[pt] OR editorial[pt] OR comment[pt] OR news[pt] OR "
    '"published erratum"[pt] OR "retraction of publication"[pt] OR '
    '"retracted publication"[pt] OR "expression of concern"[pt] OR biography[pt] OR '
    "congress[pt] OR interview[pt] OR \"preprint\"[pt])"
)

EXCLUDE_TITLE = re.compile(
    r"^\s*(correction|erratum|corrigendum|retraction|retracted|reply|in reply|"
    r"response to|re:|author response|expression of concern|withdrawn)\b",
    re.I,
)
GUIDELINE_PT = {
    "Guideline", "Practice Guideline", "Consensus Development Conference",
    "Consensus Development Conference, NIH",
}
META_PT = {"Systematic Review", "Meta-Analysis", "Network Meta-Analysis"}
REVIEW_PT = {"Review", "Scoping Review"}
GUIDELINE_TITLE = re.compile(
    r"guideline|consensus|position statement|policy statement|scientific statement|"
    r"clinical policy|practice parameter|recommendations?\b|best practice statement",
    re.I,
)
META_TITLE = re.compile(r"systematic review|meta-?analy|umbrella review|pooled analysis", re.I)
REVIEW_TITLE = re.compile(
    r"scoping review|narrative review|rapid review|literature review|\breview\b|"
    r"state of the art|evidence synthesis",
    re.I,
)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
def _post(endpoint: str, params: dict, retries: int = 4) -> bytes:
    params = dict(params, tool=TOOL)
    if API_KEY:
        params["api_key"] = API_KEY
    if EMAIL:
        params["email"] = EMAIL
    body = urllib.parse.urlencode(params).encode()
    url = f"{EUTILS}/{endpoint}"
    for attempt in range(retries):
        try:
            time.sleep(DELAY)
            req = urllib.request.Request(url, data=body, headers={"User-Agent": TOOL})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            wait = 2 ** (attempt + 1)
            print(f"  ! {endpoint} failed ({e}); retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"{endpoint} failed after {retries} retries")


def esearch(term: str, mindate: str, maxdate: str, retmax: int = 2000) -> list[str]:
    raw = _post("esearch.fcgi", {
        "db": "pubmed", "term": f"({term}) {EXCLUDE_PT}", "retmode": "json",
        "retmax": retmax, "datetype": "edat", "mindate": mindate, "maxdate": maxdate,
        "sort": "pub_date",
    })
    res = json.loads(raw)["esearchresult"]
    if "ERROR" in res:
        raise RuntimeError(res["ERROR"])
    if res.get("warninglist", {}).get("phrasesnotfound"):
        print(f"  (phrases not found: {res['warninglist']['phrasesnotfound']})", file=sys.stderr)
    return res.get("idlist", [])


def efetch(pmids: list[str]) -> list[ET.Element]:
    out = []
    for i in range(0, len(pmids), 200):
        raw = _post("efetch.fcgi", {
            "db": "pubmed", "id": ",".join(pmids[i:i + 200]), "retmode": "xml",
        })
        out.extend(ET.fromstring(raw).findall("PubmedArticle"))
    return out


# --------------------------------------------------------------------------
# 解析
# --------------------------------------------------------------------------
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _text(el: ET.Element | None) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip() if el is not None else ""


def _date(el: ET.Element | None) -> str:
    if el is None:
        return ""
    y = el.findtext("Year") or ""
    if not y:
        md = el.findtext("MedlineDate") or ""
        m = re.search(r"\d{4}", md)
        return m.group(0) if m else ""
    mo = (el.findtext("Month") or "").strip()
    mo = MONTHS.get(mo[:3].lower(), mo) if mo else ""
    d = el.findtext("Day") or ""
    if mo and d:
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    if mo:
        return f"{y}-{int(mo):02d}"
    return y


def classify(pub_types: list[str], title: str) -> str:
    pts = set(pub_types)
    if pts & GUIDELINE_PT or GUIDELINE_TITLE.search(title):
        return "guideline"
    if pts & META_PT or META_TITLE.search(title):
        return "meta"
    if pts & REVIEW_PT or REVIEW_TITLE.search(title):
        return "review"
    return "article"


def parse(article: ET.Element) -> dict | None:
    mc = article.find("MedlineCitation")
    art = mc.find("Article")
    pmid = mc.findtext("PMID")
    title = _text(art.find("ArticleTitle")) or _text(art.find("VernacularTitle"))
    if not title or EXCLUDE_TITLE.search(title):
        return None

    pub_types = [_text(p) for p in art.findall("PublicationTypeList/PublicationType")]

    authors = []
    for a in art.findall("AuthorList/Author"):
        if a.findtext("CollectiveName"):
            authors.append(a.findtext("CollectiveName"))
        elif a.findtext("LastName"):
            authors.append(f"{a.findtext('LastName')} {a.findtext('Initials') or ''}".strip())

    abstract_parts = []
    for ab in art.findall("Abstract/AbstractText"):
        label = ab.get("Label")
        txt = _text(ab)
        if txt:
            abstract_parts.append({"label": label, "text": txt} if label else {"text": txt})

    ids = {i.get("IdType"): (i.text or "").strip()
           for i in article.findall("PubmedData/ArticleIdList/ArticleId")}
    doi = ids.get("doi") or next(
        ((e.text or "").strip() for e in art.findall("ELocationID") if e.get("EIdType") == "doi"), "")

    journal = art.find("Journal")
    epub = _date(art.find("ArticleDate"))
    ppub = _date(journal.find("JournalIssue/PubDate")) if journal is not None else ""

    return {
        "pmid": pmid,
        "title": title,
        "journal": journal.findtext("ISOAbbreviation") or journal.findtext("Title") or "",
        "journal_full": journal.findtext("Title") or "",
        "date": epub or ppub,
        "authors": authors,
        "abstract": abstract_parts,
        "pub_types": pub_types,
        "type": classify(pub_types, title),
        "doi": doi,
        "pmc": ids.get("pmc", ""),
        "issn": mc.findtext("MedlineJournalInfo/ISSNLinking")
                or (journal.findtext("ISSN") if journal is not None else "") or "",
        "cats": [],
    }


# --------------------------------------------------------------------------
# 主程式
# --------------------------------------------------------------------------
def update_journal_metrics(articles: list[dict]) -> None:
    """
    以 OpenAlex「2-year mean citedness」作為影響係數 (IF) 近似值，
    依期刊縮寫存入 data/journal_metrics.json（累積保存，供所有週次使用）。
    """
    try:
        metrics = json.loads(METRICS.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        metrics = {}
    journals: dict[str, set[str]] = {}
    for a in articles:
        if a.get("issn") and a.get("journal"):
            journals.setdefault(a["journal"], set()).add(a["issn"])
    issn_to_j = {i: j for j, iss in journals.items() for i in iss}
    issns = list(issn_to_j)
    if not issns:
        return
    print(f"Fetching OpenAlex metrics for {len(journals)} journals…")
    found = 0
    for i in range(0, len(issns), 50):
        params = {"filter": "issn:" + "|".join(issns[i:i + 50]), "per-page": 200}
        if OPENALEX_KEY:
            params["api_key"] = OPENALEX_KEY
        if EMAIL:
            params["mailto"] = EMAIL
        url = OPENALEX + "?" + urllib.parse.urlencode(params)
        try:
            time.sleep(0.2)
            req = urllib.request.Request(url, headers={"User-Agent": TOOL})
            with urllib.request.urlopen(req, timeout=60) as r:
                results = json.loads(r.read()).get("results", [])
        except Exception as e:  # 失敗不影響主流程，保留舊值
            print(f"  ! OpenAlex failed ({e}); keeping cached metrics", file=sys.stderr)
            continue
        for src in results:
            v = (src.get("summary_stats") or {}).get("2yr_mean_citedness")
            if v is None:
                continue
            for issn in [src.get("issn_l")] + (src.get("issn") or []):
                j = issn_to_j.get(issn or "")
                if j:
                    metrics[j] = {
                        "if": round(float(v), 2),
                        "h": (src.get("summary_stats") or {}).get("h_index"),
                        "issn": issn,
                        "updated": dt.datetime.now(TZ).date().isoformat(),
                    }
                    found += 1
                    break
    METRICS.write_text(json.dumps(dict(sorted(metrics.items())), ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"  metrics updated for {found} journals (total {len(metrics)})")


def backfill_metrics() -> None:
    """舊週次資料沒有 ISSN：每個缺少指標的期刊挑一篇 PMID 重新查 ISSN，再補抓指標。"""
    try:
        have = set(json.loads(METRICS.read_text(encoding="utf-8")))
    except (FileNotFoundError, json.JSONDecodeError):
        have = set()
    sample: dict[str, str] = {}
    for f in WEEKS.glob("*.json"):
        try:
            for a in json.loads(f.read_text(encoding="utf-8")).get("articles", []):
                if a.get("journal") and a["journal"] not in have:
                    sample.setdefault(a["journal"], a["pmid"])
        except json.JSONDecodeError:
            continue
    if not sample:
        return
    print(f"Backfilling ISSN for {len(sample)} journals from earlier weeks…")
    recs = [r for r in (parse(el) for el in efetch(list(sample.values()))) if r]
    update_journal_metrics(recs)


RANGES = {"30": 30, "365": 365, "730": 730}   # 網頁可選的區間（天）
RANGE_DIR = DATA / "range"


def fetch_week(start: str, end: str) -> list[dict]:
    hits: dict[str, list[str]] = {}
    for cat in CATEGORIES:
        ids = esearch(cat["query"], start, end, retmax=9999)
        print(f"  {cat['name']:<36} {len(ids):>5}")
        for pmid in ids:
            hits.setdefault(pmid, []).append(cat["id"])
    print(f"  Fetching {len(hits)} unique records…")
    order = [c["id"] for c in CATEGORIES]
    articles = []
    for el in efetch(list(hits)):
        rec = parse(el)
        if rec and rec["pmid"] in hits:
            rec["cats"] = sorted(hits[rec["pmid"]], key=order.index)
            articles.append(rec)
    articles.sort(key=lambda a: (a["date"], a["pmid"]), reverse=True)
    return articles


def save_week(label: str, start: str, end: str, articles: list[dict]) -> None:
    WEEKS.mkdir(parents=True, exist_ok=True)
    week = {
        "week": label,
        "range": [start.replace("/", "-"), end.replace("/", "-")],
        "generated": dt.datetime.now(TZ).isoformat(timespec="seconds"),
        "count": len(articles),
        "articles": articles,
    }
    (WEEKS / f"{label}.json").write_text(
        json.dumps(week, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  Saved {len(articles)} articles → data/weeks/{label}.json")


def run_week(monday: dt.date, start: str | None = None, end: str | None = None,
             label: str | None = None) -> list[dict]:
    """抓取「monday 前 7 天」（上週一～週日）新收錄的文章。"""
    start = start or (monday - dt.timedelta(days=7)).strftime("%Y/%m/%d")
    end = end or (monday - dt.timedelta(days=1)).strftime("%Y/%m/%d")
    label = label or monday.isoformat()
    print(f"Week {label}: PubMed entry date {start} – {end}")
    arts = fetch_week(start, end)
    save_week(label, start, end, arts)
    return arts


def load_weeks() -> list[dict]:
    weeks = []
    for f in sorted(WEEKS.glob("*.json"), reverse=True):
        try:
            weeks.append(json.loads(f.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return weeks


def rebuild_outputs() -> None:
    """重建 index.json 與 30 天／1 年／2 年的精簡清單。"""
    weeks = load_weeks()
    now = dt.datetime.now(TZ).isoformat(timespec="seconds")
    index = {
        "updated": now,
        "categories": [{k: c[k] for k in ("id", "name", "zh")} for c in CATEGORIES],
        "weeks": [{"week": w["week"], "range": w["range"], "count": w["count"]} for w in weeks],
        "ranges": {},
    }
    if weeks:
        latest_end = dt.date.fromisoformat(weeks[0]["range"][1])
        RANGE_DIR.mkdir(parents=True, exist_ok=True)
        for key, days in RANGES.items():
            since = latest_end - dt.timedelta(days=days - 1)
            seen, rows, first = set(), [], None
            for w in weeks:
                if dt.date.fromisoformat(w["range"][1]) < since:
                    continue
                first = w["range"][0]
                for a in w["articles"]:
                    if a["pmid"] in seen:
                        continue
                    seen.add(a["pmid"])
                    au = a.get("authors") or []
                    rows.append({
                        "pmid": a["pmid"], "title": a["title"], "journal": a["journal"],
                        "date": a["date"], "type": classify(a.get("pub_types", []), a["title"]),
                        "cats": a["cats"], "doi": a.get("doi", ""), "pmc": a.get("pmc", ""),
                        "au": au[0] + (" et al." if len(au) > 1 else "") if au else "",
                        "w": w["week"],
                    })
            rows.sort(key=lambda a: (a["date"], a["pmid"]), reverse=True)
            (RANGE_DIR / f"{key}.json").write_text(json.dumps(
                {"days": days, "range": [first, latest_end.isoformat()], "count": len(rows),
                 "articles": rows}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            index["ranges"][key] = {"range": [first, latest_end.isoformat()], "count": len(rows),
                                    "complete": first is not None and
                                    dt.date.fromisoformat(first) <= since + dt.timedelta(days=6)}
            print(f"  range {key}d: {len(rows)} articles")
    (DATA / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


def main() -> None:
    today = dt.datetime.now(TZ).date()
    this_monday = today - dt.timedelta(days=today.weekday())
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="YYYY/MM/DD（含）")
    ap.add_argument("--end", help="YYYY/MM/DD（含）")
    ap.add_argument("--label", help="週次標籤 YYYY-MM-DD（預設：執行當週的週一）")
    ap.add_argument("--metrics-only", action="store_true", help="只補抓期刊影響係數")
    ap.add_argument("--backfill", type=int, default=0, metavar="N",
                    help="補抓過去 N 週（已存在的週次會略過）")
    ap.add_argument("--rebuild-only", action="store_true", help="只重建 index 與區間清單")
    args = ap.parse_args()

    if args.metrics_only:
        backfill_metrics()
        rebuild_outputs()
        return
    if args.rebuild_only:
        rebuild_outputs()
        return

    if args.backfill:
        t0, ok = time.time(), True
        for k in range(0, args.backfill + 1):
            monday = this_monday - dt.timedelta(weeks=k)
            f = WEEKS / f"{monday.isoformat()}.json"
            want = [(monday - dt.timedelta(days=7)).isoformat(), (monday - dt.timedelta(days=1)).isoformat()]
            try:
                if json.loads(f.read_text(encoding="utf-8")).get("range") == want:
                    continue          # 已存在且區間正確 → 略過
            except (FileNotFoundError, json.JSONDecodeError):
                pass
            try:
                run_week(monday)
            except Exception as e:      # 單週失敗不中斷，下次再補
                print(f"  ! week {monday} failed: {e}", file=sys.stderr)
                ok = False
            if time.time() - t0 > 5 * 3600:   # GitHub Actions 單次上限 6 小時
                print("Time budget reached; remaining weeks next run.")
                ok = False
                break
        if ok:
            (DATA / "backfill_done.txt").write_text(
                f"{args.backfill} weeks backfilled at {dt.datetime.now(TZ).isoformat()}\n", encoding="utf-8")
    else:
        run_week(this_monday, args.start, args.end, args.label)

    # 本次新文章的期刊指標 + 舊週次缺的期刊
    backfill_metrics()
    rebuild_outputs()


if __name__ == "__main__":
    main()
