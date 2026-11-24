#!/usr/bin/env python3
"""
中文敘述輔助工具（給每週的 Claude 排程任務使用）

  python scripts/zh_tool.py status                 # 各週中文完成度
  python scripts/zh_tool.py export [週] [--n 60] [--all]
        # 輸出尚未翻譯的文章（JSON Lines）；預設只含指引、統合分析、綜論，--all 為全部類型
  python scripts/zh_tool.py merge 檔案.json [週]   # 合併翻譯結果到 data/zh/<週>.json

merge 的輸入格式：{"<pmid>": {"t": "中文標題", "s": "一句中文重點"}, ...}
週省略時預設為最新一週。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEEKS = ROOT / "data" / "weeks"
ZH = ROOT / "data" / "zh"


def latest_week() -> str:
    return sorted(p.stem for p in WEEKS.glob("*.json"))[-1]


def load_week(w: str) -> dict:
    return json.loads((WEEKS / f"{w}.json").read_text(encoding="utf-8"))


def load_zh(w: str) -> dict:
    f = ZH / f"{w}.json"
    return json.loads(f.read_text(encoding="utf-8")).get("items", {}) if f.exists() else {}


def key_text(a: dict, limit: int = 700) -> str:
    """摘要中最有資訊的部分：優先 Results / Conclusion，否則取開頭。"""
    parts = a.get("abstract") or []
    pick = [p["text"] for p in parts
            if re.search(r"result|finding|conclusion|interpretation", p.get("label") or "", re.I)]
    txt = " ".join(pick) or " ".join(p["text"] for p in parts)
    return txt[:limit]


TARGET_TYPES = {"guideline", "meta", "review"}   # 撰寫規則：只寫指引、統合分析、綜論（原著不寫）


def targets(w: str, all_types: bool = False) -> list[dict]:
    arts = load_week(w)["articles"]
    return arts if all_types else [a for a in arts if classify_type(a) in TARGET_TYPES]


def classify_type(a: dict) -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    from fetch_pubmed import classify
    return classify(a.get("pub_types", []), a["title"])


def cmd_status() -> None:
    for w in sorted((p.stem for p in WEEKS.glob("*.json")), reverse=True)[:8]:
        t = {a["pmid"] for a in targets(w)}
        z = load_zh(w)
        print(f"{w}: 指引/統合分析/綜論 {len(t & z.keys())}/{len(t)} 已有中文")


def cmd_export(args: list[str]) -> None:
    n = 60
    if "--n" in args:
        i = args.index("--n"); n = int(args[i + 1]); del args[i:i + 2]
    all_types = "--all" in args
    args = [x for x in args if x != "--all"]
    w = args[0] if args else latest_week()
    done = load_zh(w)
    todo = [a for a in targets(w, all_types) if a["pmid"] not in done]
    print(f"# week {w}: {len(todo)} remaining, showing {min(n, len(todo))}", file=sys.stderr)
    for a in todo[:n]:
        print(json.dumps({"pmid": a["pmid"], "journal": a["journal"], "title": a["title"],
                          "key": key_text(a, 1200)}, ensure_ascii=False))


def cmd_merge(args: list[str]) -> None:
    src = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    w = args[1] if len(args) > 1 else latest_week()
    valid = {a["pmid"] for a in load_week(w)["articles"]}
    items = load_zh(w)
    added = 0
    for pmid, v in src.items():
        pmid = str(pmid)
        if pmid not in valid or not isinstance(v, dict) or not v.get("t"):
            print(f"  skip {pmid}", file=sys.stderr)
            continue
        items[pmid] = {"t": str(v["t"]).strip(), "s": str(v.get("s", "")).strip()}
        added += 1
    ZH.mkdir(parents=True, exist_ok=True)
    (ZH / f"{w}.json").write_text(json.dumps({"week": w, "items": items}, ensure_ascii=False,
                                             separators=(",", ":")), encoding="utf-8")
    print(f"merged {added}; week {w} now {len(items)}/{len(valid)}")


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["status"]
    {"status": lambda a: cmd_status(), "export": cmd_export, "merge": cmd_merge}[cmd](rest)
