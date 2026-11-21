# 足球 AI 工作台

[開啟手機與電腦工作台](https://a066988-maker.github.io/football-ai-workspace/)

免費優先：GitHub Actions + GitHub Pages + Gemini。每天台灣時間 16:00、17:00、18:00、19:00、20:00、22:00 自動執行多輪檢查；只有當天完成 Gemini 正式分析及完整 QA 才停止重抓；規則備援可產出但隔次仍會嘗試 Gemini，工作台在手機上編輯賽事分析、比分、大小球方向，下載 1080×1920 PNG，複製小紅書簡體文案。

## 每日流程

1. 直接從球探足球即時資料來源嘗試取得賽事、歐賠、亞盤與大小球初盤／即時盤。
2. 若球探拒絕雲端連線，透過免費 Playwright 無頭瀏覽器及中文字型讀取已載入官網的足球資料。
3. 如球探完全不可用，嘗試 ESPN 公開賽程作備援。**備援僅用於賽程展示，絕不能當成球探盤口。**
4. 將全部可確認的晚間賽程與各聯賽場數輸出至 output/fixtures.json。
5. 只有 3～5 場比賽有完整、數值合法的球探盤口，才允許 Gemini 分析。使用 Gemini 3.5/3.8，必要時嘗試官方 Interactions API；之後先做程式規則審查、再由 Gemini 獨立審稿，最多自動修正三輪。如 Gemini 回 503 等連線錯誤，改用來源盤口的**規則版分析**，明確標示**非 AI 生成**，以確保每天仍可產文、產圖，且不編造資料。
6. 產圖、文案後再次核對賽事名稱、全部比分、趨勢、Hashtag、免責聲明、圖片格式與 1080×1920 尺寸。若出錯，最多重產兩次；若仍錯誤則禁止發布。每次保存 output/qa_report.json 供手機工作台直接查看。只有全數通過才發布 output/analysis.json、output/poster.png、output/xiaohongshu.txt。
7. 可選：如已設定 Telegram Bot secrets，且當日分析成功，會傳送摘要、已生成的 PNG 圖片與網站連結至 Telegram。

GitHub Actions 工作流程： [.github/workflows/daily.yml](.github/workflows/daily.yml)

## 安全與資料原則

- 賽事時段：當日 16:00～隔日 08:00（Asia/Taipei）。
- 資料不足會顯示明確的狀態，**不會自行編造比賽、盤口、傷停、陣容或分析。**
- 亞洲讓球盤的原始數值符號尚未另行驗證前，AI 只建議已確實核對盤線的大小球，不假設主客讓球方向。
- 不會自動發布至小紅書：網站提供編輯、下載與複製，發文由使用者完成。
- 自我修正限於資料來源切換、模型重新生成及圖片重繪；**不允許 Gemini 自行修改 GitHub 原始程式碼**，避免不受控的程式碼執行。真正程式故障會有失敗報告，需開發者修復。
- 免費 GitHub Actions 與 Gemini API 均可能受執行額度及服務可用性限制，不能保證 100% 零費用與穩定存取。

## GitHub Secrets

- GEMINI_API_KEY：Gemini 必需，曾由使用者設定。不要公開或複製到程式碼中。
- TELEGRAM_BOT_TOKEN：Telegram 機器人 token（選填）。
- TELEGRAM_CHAT_ID：Telegram 對話 ID（選填）。

## 每日公開狀態

| 狀態 | 說明 |
| --- | --- |
| analysis_ready | 已取得完整盤口，Gemini AI 輸出經多輪複審，圖文通過 QA |
| analysis_ready_rules | Gemini 無法使用，改產已驗證盤口的規則分析、圖片與文案（非 AI） |
| insufficient_verified_odds | 球探資料不足三場完整初盤與即時盤 |
| schedule_only_no_titan_odds | 只有 ESPN 來源賽程，不執行 AI |
| source_error | 所有資料來源均無法可靠存取 |
| ai_quality_failed | Gemini 生成／獨立複審最多三輪仍未通過 |
| source_quality_failed | 球探賽程、盤口或時間新鮮度檢驗不通過 |
| asset_quality_failed | 圖片或文案最多兩輪仍驗證失敗 |
| pipeline_preflight_error | 執行環境、單元測試或圖片自測失敗 |

所有技術驗證都不代表賽果必定命中。
