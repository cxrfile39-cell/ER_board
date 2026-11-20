# EM Weekly｜急診醫學每週文獻

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

之後每週一 06:00（台北時間）自動更新並重新發布。GitHub 排程偶爾延遲數十分鐘屬正常。

> 若第一次自動執行顯示 push 權限錯誤：到 **Settings → Actions → General → Workflow permissions** 改為 **Read and write permissions**，再到 Actions 分頁按 **Re-run**。

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
