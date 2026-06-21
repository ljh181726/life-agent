# Life-Agent 全自動智慧生活管理系統

這是一個基於 Notion API、Gemini API 與 Telegram Bot API 的全自動智慧生活管理系統，旨在透過嚴格的數據推理與視覺辨識，協助使用者打理課業、記帳、排程與書包物品管理。

---

## 🚀 快速上手：一鍵自動建立 Notion 資料庫

為了方便您使用，本系統提供了 **自動建立 5 個 Notion 資料庫** 的自動化指令，您不需手動在 Notion 建立與設定複雜的欄位。

### 第一步：填寫基礎設定到 `.env` 檔案中
請打開專案根目錄下的 `.env` 檔案，填入以下兩個變數：

1. **`NOTION_TOKEN`**（Notion 整合金鑰）：
   - **取得方式**：
     1. 前往 [Notion Integrations (我的整合)](https://www.notion.so/my-integrations)。
     2. 點選 **「+ New integration (新增整合)」**。
     3. 填寫名稱，確認關聯到正確的 Notion 工作區，然後點選 **Submit** 儲存。
     4. 複製以 `secret_` 開頭的 **Internal Integration Token (內部整合金鑰)**。
     5. 將此金鑰貼入 `.env` 檔案中的 `NOTION_TOKEN=` 後方。

2. **`NOTION_PARENT_PAGE_ID`**（父頁面網址或 ID）：
   - **取得方式與設定步驟**：
     1. 在 Notion 中打開一個您想用來存放這 5 個資料庫的**現有父頁面**（或建立一個新頁面）。
     2. **關鍵授權步驟**：點選頁面右上角的 **「...」** 按鈕 -> 選擇 **「Add connections (新增連線)」** -> 搜尋並點選您剛才建立的整合名稱，同意授權連結（這能讓 API 有權限在此頁面下建立資料庫）。
     3. 複製該 Notion 頁面的網址 (URL)。
        - 網址格式例如：`https://www.notion.so/My-Page-1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p`
        - 或是直接複製網址最後面的 32 位字元（即 `1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p`）。
     4. 將此網址或 ID 貼入 `.env` 檔案中的 `NOTION_PARENT_PAGE_ID=` 後方。

### 第二步：執行自動建立指令
請先在終端機切換至本專案的根目錄，再執行建立指令。

**Windows 終端機指令（請逐行執行）：**
```cmd
python setup_notion.py
```

執行成功後，系統將自動在您的 Notion 頁面下建立這六個資料庫（包含其欄位型態），並**自動將產生的六個資料庫 ID 寫入您的 `.env` 檔案中**！

---

## ⚙️ 祕鑰與環境變數 (Secrets) 設定指引

為讓系統在 GitHub Actions 與本地正確運行，系統使用以下環境變數（皆已配置在 `.env` 中）：

1. **`NOTION_TOKEN`**：Notion API Token，前往 [Notion Integrations](https://www.notion.so/my-integrations) 建立整合。請確保已將該整合連線 (Connection) 加入您的父頁面中。
2. **`GEMINI_API_KEY`**：前往 [Google AI Studio](https://aistudio.google.com/) 申請 API 金鑰，用於聯絡簿、收據視覺辨識與智能提示。
3. **`TELEGRAM_BOT_TOKEN`** 與 **`TELEGRAM_CHAT_ID`**：
   - **`TELEGRAM_BOT_TOKEN`**：在 Telegram 搜尋並發送訊息給 `@BotFather`，輸入 `/newbot` 建立機器人，完成後會獲得一串 HTTP API Token（格式如 `123456789:ABCdefGhIJK...`）。
   - **`TELEGRAM_CHAT_ID`**：將您的機器人啟用後（點選 Start），在 Telegram 搜尋 `@userinfobot` 並發送任意訊息給它，它會回傳您的個人 `Id`（一串數字，例如 `987654321`）。

在部署到 GitHub Actions 時，請在您 GitHub 儲存庫的 **Settings > Secrets and variables > Actions > Repository secrets** 中新增上述的所有變數（包括產生的資料庫 ID 變數）。

---

## 🛠️ 本地測試與驗證

若要在本地運行測試：
1. 確保已安裝套件：
   ```bash
   pip install -r requirements.txt
   ```
2. 執行時段定時任務：
   ```bash
   # 執行時段 A：下午 5:00 邏輯 (記帳統計 + 視覺辨識 + 書包物品檢查)
   python main.py --mode A

   # 執行時段 B：半夜 12:00 邏輯 (時間塊動態分配 + Telegram 明日日程通知)
   python main.py --mode B
   ```
