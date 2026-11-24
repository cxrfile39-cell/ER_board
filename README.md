# EM Weekly｜急診醫學每週文獻

製作者：JH CHIU MD · Claude 5.5

每週一自動從 PubMed 抓取前一週新收錄的急診醫學 **Journal Article / Review / Guideline**，依 12 個次專科分類，發布在 GitHub Pages。

次專科：General EM、Emergency Critical Care、Pediatric EM、EMS、Medical Toxicology、Emergency Ultrasound、Disaster Medicine、Hyperbaric & Undersea Medicine、Sports Medicine、Geriatric EM、Emergency Neurology、Emergency Trauma Medicine。

## 功能
- 次專科、文章類型各有「全選／全不選」
- 週次切換（保留所有歷史週次）、關鍵字搜尋並標示、排序
- 摘要展開、PubMed / DOI / PMC 免費全文連結
- 篩選設定會記在瀏覽器；支援手機與深色模式

## 部署步驟
1. 在 GitHub 建立新的 **Public** repo（例如 `em-weekly`），把本資料夾所有檔案上傳到 `main` 分支（包含 `.github` 資料夾與 `.nojekyll`）。
   上傳後 Actions 會**自動**抓取第一週資料並 commit 回 repo（約 1–3 分鐘），不需手動執行。
2. **Settings → Pages → Build and deployment**：Source 選 **Deploy from a branch**，Branch 選 **main / (root)**，按 Save。
3. 約 1 分鐘後網址生效：`https://<你的帳號>.github.io/<repo 名稱>/`
4. （建議）**Settings → Secrets and variables → Actions** 新增 `NCBI_API_KEY`（NCBI 帳號免費申請）與 `NCBI_EMAIL`，抓取更穩定。

之後每週一 05:37（台北時間）自動更新並重新發布。GitHub 排程偶爾延遲數十分鐘屬正常。

> 若第一次自動執行顯示 push 權限錯誤：到 **Settings → Actions → General → Workflow permissions** 改為 **Read and write permissions**，再到 Actions 分頁按 **Re-run**。

## 時間範圍
- 網頁可切換 7 天／30 天／1 年／2 年，或指定週次。
- 第一次更新到新版時，GitHub 會自動補抓過去 104 週（約 20–60 分鐘），完成後產生 `data/backfill_done.txt`；中途失敗會保留進度，下次自動接續。
- 30 天／1 年／2 年清單存在 `data/range/`，不含摘要（點開時才載入）以減少手機載入量。

## 期刊影響係數（IF）
- 自動：OpenAlex「2-year mean citedness」（近似 IF，非官方 JIF），存在 `data/journal_metrics.json`。
  建議到 openalex.org/settings/api 免費申請 API key，加入 Secrets：`OPENALEX_API_KEY`。
- 手動：在 `data/jif.json` 填入官方 JIF（例如 `"Ann Emerg Med": 5.0`），網頁會優先顯示。

## 調整
- **分類關鍵字／期刊**：編輯 `scripts/fetch_pubmed.py` 的 `CATEGORIES`。
- **更新時間**：編輯 `.github/workflows/weekly.yml` 的 `cron`（UTC 時間）。
- **補抓某一週**：
  `python scripts/fetch_pubmed.py --start 2026/11/09 --end 2026/11/15 --label 2026-11-16`

## 分類邏輯說明
- 以 PubMed「收錄日期」(Entrez date) 為準，抓取執行日前 7 天。
- 剛收錄的文章多半還沒有 MeSH 索引，所以每個次專科以標題／摘要關鍵字為主，並搭配「急診情境」（急診期刊或摘要提到 emergency department、prehospital 等）。專科期刊（如 *Clin Toxicol*、*Undersea Hyperb Med*、*Br J Sports Med*、*J Trauma Acute Care Surg*）直接納入。
- 一篇文章可同時屬於多個次專科。
- 類型判定：PubMed 文章類型含 Guideline / Consensus，或標題含 guideline、consensus、clinical policy、recommendation 等 → Guideline；含 Review / Systematic Review / Meta-Analysis 或標題含 review、meta-analysis → Review；其餘 → Journal Article。Letter、Editorial、Comment、勘誤、撤稿則排除。
