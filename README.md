# 足球 AI 工作台

[開啟手機與電腦工作台](https://a066988-maker.github.io/football-ai-workspace/)

免費優先：GitHub Actions + GitHub Pages + Gemini。每天台灣時間 16:00 自動執行；17:00、18:00 會自動補抓，已有當日成功分析就不重複產出，工作台在手機上編輯賽事分析、比分、大小球方向，下載 1080×1920 PNG，複製小紅書簡體文案。

## 每日流程

1. 直接從球探足球即時資料來源嘗試取得賽事、歐賠、亞盤與大小球初盤／即時盤。
2. 若球探拒絕雲端連線，透過免費 Playwright 無頭瀏覽器及中文字型讀取已載入官網的足球資料。
3. 如球探完全不可用，嘗試 ESPN 公開賽程作備援。**備援僅用於賽程展示，絕不能當成球探盤口。**
4. 將全部可確認的晚間賽程與各聯賽場數輸出至 output/fixtures.json。
5. 只有 3～5 場比賽有完整、數值合法的球探盤口時，才允許 Gemini 分析；逐項檢查 AI 推薦盤口、三個比分及資料來源。
6. 發布 output/status.json，成功時另發布 output/analysis.json、output/poster.png（1080×1920）、output/xiaohongshu.txt；網站自動讀取，亦可下載並編輯圖片與文案。
7. 可選：如已設定 Telegram Bot secrets，且當日分析成功，會傳送摘要、已生成的 PNG 圖片與網站連結至 Telegram。

GitHub Actions 工作流程： [.github/workflows/daily.yml](.github/workflows/daily.yml)

## 安全與資料原則

- 賽事時段：當日 16:00～隔日 08:00（Asia/Taipei）。
- 資料不足會顯示明確的狀態，**不會自行編造比賽、盤口、傷停、陣容或分析。**
- 亞洲讓球盤的原始數值符號尚未另行驗證前，AI 只建議已確實核對盤線的大小球，不假設主客讓球方向。
- 不會自動發布至小紅書：網站提供編輯、下載與複製，發文由使用者完成。
- 免費 GitHub Actions 與 Gemini API 均可能受執行額度及服務可用性限制，不能保證 100% 零費用與穩定存取。

## GitHub Secrets

- GEMINI_API_KEY：Gemini 必需，曾由使用者設定。不要公開或複製到程式碼中。
- TELEGRAM_BOT_TOKEN：Telegram 機器人 token（選填）。
- TELEGRAM_CHAT_ID：Telegram 對話 ID（選填）。

## 每日公開狀態

| 狀態 | 說明 |
| --- | --- |
| analysis_ready | 已取得完整盤口，AI 輸出經程式一致性檢查 |
| insufficient_verified_odds | 球探資料不足三場完整初盤與即時盤 |
| schedule_only_no_titan_odds | 只有 ESPN 來源賽程，不執行 AI |
| source_error | 所有資料來源均無法可靠存取 |
| ai_error | Gemini API 錯誤或輸出未通過驗證 |

所有技術驗證都不代表賽果必定命中。
