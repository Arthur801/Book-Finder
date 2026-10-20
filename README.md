# Book-Finder
A .net core website about using LLM to find a book you want.

## 本機開發

1. 資料庫與 migration：見 `Infrastructure/Persistence/README.md`（`ConnectionStrings:DefaultConnection` 放在 `dotnet user-secrets`）。
2. JWT signing key：Web 啟動時會檢查 `Jwt:SigningKey`，缺少或短於 32 bytes 會直接啟動失敗。本機放在 repository 根目錄的 `.env`（不進 repository）：

   ```bash
   echo "Jwt__SigningKey=$(openssl rand -hex 32)" >> .env
   ```

   `.env` 也必須有 `OPENAIAPI_KEY`，缺少時網站無法啟動。下面只是格式示意，不要寫入真實的 key：

   ```bash
   OPENAIAPI_KEY=<your-openai-api-key>
   ```

   注意：啟動後背景補齊會立即呼叫 OpenAI 產生 embedding，會產生費用。本機開發若不需要，可在 `.env` 加上 `Embedding__BackfillEnabled=false` 關閉（`Docs/modules/recommendation.md` §10）。

3. 程式本身不讀 `.env`；啟動前先載入到 shell：

   ```bash
   set -a; . ./.env; set +a
   dotnet run
   ```

   VS Code 偵錯可在 `launch.json` 的設定加上 `"envFile": "${workspaceFolder}/.env"`。

正式環境的 key 來自 SSM（`Docs/deployment/deployment.md` §5）。
