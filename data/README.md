# 已驗證賽事資料

請建立 data/verified_matches.json，內含 3–5 場具有可靠來源的真實賽事，欄位請參照網站「載入資料格式」。

**沒有資料時系統會停止，不會虛構賽事。** 目前尚未接通球探網自動採集；本工作流程需手動匯入已驗證資料。

API 金鑰只能存在 GitHub Actions Secrets 的 GEMINI_API_KEY，不能放進本資料夾。
