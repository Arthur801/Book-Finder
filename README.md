# Book-Finder
A .net core website about using LLM to find a book you want.

## 本機開發

1. 資料庫與 migration：見 `Infrastructure/Persistence/README.md`（`ConnectionStrings:DefaultConnection` 放在 `dotnet user-secrets`）。
2. JWT signing key：Web 啟動時會檢查 `Jwt:SigningKey`，缺少或短於 32 bytes 會直接啟動失敗。本機放在 repository 根目錄的 `.env`（不進 repository）：

   ```bash
   echo "Jwt__SigningKey=$(openssl rand -hex 32)" >> .env
   ```

3. 程式本身不讀 `.env`；啟動前先載入到 shell：

   ```bash
   set -a; . ./.env; set +a
   dotnet run
   ```

   VS Code 偵錯可在 `launch.json` 的設定加上 `"envFile": "${workspaceFolder}/.env"`。

正式環境的 key 來自 SSM（`Docs/deployment/deployment.md` §5）。
