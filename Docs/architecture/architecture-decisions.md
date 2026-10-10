# Architecture Decisions

> Path: `Docs/architecture/architecture-decisions.md`
> Authority: 已決定的架構取捨。每條決策一節；推翻時新增一節並將舊節標為 Superseded，不直接改寫歷史。

---

## ADR-001 — Modular Monolith，不拆微服務

**Status**: Accepted

單一產品領域、單一主要資料庫、個人專案規模，拆服務只會帶來 service discovery、服務間認證、分散式交易與多服務部署成本，沒有對應收益。因此 Web 採單一 ASP.NET Core MVC deployable，內部依業務能力（Identity、Catalog、Bestseller、Recommendation、Library）分模組，模組間以 Application 層介面互動。

- **Alternatives**: 依模組拆微服務；AI Recommendation 獨立服務。
- **Trade-offs**: 無法獨立擴縮模組；Web 單點故障。換得部署與除錯簡單。
- **Migration impact**: 若日後拆分，以既有模組邊界為切點；模組間不得直接存取彼此的資料表以保留此路徑。

---

## ADR-002 — Python crawler 直接寫共用 PostgreSQL，schema 只由 EF Core 管理

**Status**: Accepted

Crawler 以 Python 撰寫並作為每日 one-shot batch，直接寫入 Web 使用的同一個 PostgreSQL，而非透過 Web API。Schema 唯一擁有者是 EF Core migration；crawler 不執行 DDL，只寫 Catalog 與 Bestseller 相關資料表。

- **Alternatives**: Crawler 呼叫 Web 的內部 ingest API；crawler 自有資料庫再同步。
- **Trade-offs**: 兩種語言共用同一份 schema 契約，schema 變更須同步檢查 crawler；換得不需為 crawler 開 Web 寫入端點與服務間認證。
- **Migration impact**: 任何 Catalog / Bestseller schema 變更必須先更新 `Docs/data/data-model.md` 並驗證 crawler。

---

## ADR-003 — Embedding 與所有 OpenAI 呼叫只在 C# Web Application

**Status**: Accepted

OpenAI 整合（需求解析、embedding、排序、推薦理由、Book AI Profile）集中於 C# Recommendation 模組。Crawler 新增的 Book 沒有 embedding，由 C# 端補齊。

- **Alternatives**: Crawler 寫入新書時一併產生 embedding。
- **Trade-offs**: 新書在補齊前無法被向量檢索；換得 OpenAI 金鑰、模型版本與 prompt 只存在一處，crawler 不需持有 AI secrets。
- **Migration impact**: 若改由 crawler 產生 embedding，須將 embedding model 與維度變成跨語言共享契約。

---

## ADR-004 — JWT 以 HttpOnly cookie 傳遞

**Status**: Accepted

前端為 Razor server-rendered 頁面，一般頁面導覽不會攜帶 `Authorization` header。JWT 由伺服器簽發並存放於 `HttpOnly`、`Secure`、`SameSite=Lax` cookie，JWT Bearer middleware 從 cookie 讀取；所有改變狀態的請求須通過 ASP.NET Core antiforgery 驗證。

- **Alternatives**: JWT 存於 localStorage 並以 `Authorization` header 傳遞。
- **Trade-offs**: 需要 CSRF 防護；換得 JavaScript 無法讀取 token（降低 XSS 竊取風險），且 Razor 頁面導覽可直接取得使用者身分。
- **Migration impact**: 若日後提供給非瀏覽器 client 的 API，可另外接受 `Authorization` header，不影響 cookie 流程。

---

## ADR-005 — 使用 process-local `IMemoryCache`，不引入 Redis

**Status**: Accepted

MVP 只有單一 Web instance。Cache 只存可由 PostgreSQL 重建的唯讀資料（例如目前 Bestseller、Book detail），restart 清空可接受；不作為 source of truth。Crawler 與 Web 之間沒有 invalidation 通道，以短 TTL 讓 Bestseller cache 自然過期。

- **Alternatives**: Redis / ElastiCache。
- **Trade-offs**: 多 instance 時 cache 不一致；換得不多一個基礎服務與成本。
- **Migration impact**: 水平擴充 Web 前須改為分散式 cache。
