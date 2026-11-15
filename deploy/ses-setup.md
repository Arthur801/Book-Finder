# Amazon SES 設定步驟（Email 驗證與忘記密碼上線前）

> 對象：在 AWS Console 與 Cloudflare 上操作的人（營運者）。
> 目的：讓正式環境的網站能以 `noreply@khwebsc.com` 寄出驗證信、重設密碼信與「密碼已變更」通知。
> 背景：[會員中心計畫](../Docs/plans/member-center-email-verification.md) Feature E 第 2 步；追蹤項目 [DEP-B27](docs/backlog.md)、[INF-B11](../Infrastructure/docs/backlog.md)。
> 建立日期：2026-11-15。AWS 的說明以官方文件為準，本文每一節都附上來源。

## 0. 先知道的事

- 本文的步驟都在 AWS 與 Cloudflare 上進行，**不會改變網站行為**。網站要等 v0.0.16 打開 `EmailVerification__Enabled` 才會開始寄信。
- 你需要：
  - 可以修改 IAM、EC2、SES 的 AWS 帳號（不是 EC2 上的 instance role）；
  - Cloudflare 上 `khwebsc.com` 的 DNS 編輯權限；
  - 一個你自己收得到信的信箱，用來測試。
- 費用：SES 依寄出封數計費，詳見 [Amazon SES 定價](https://aws.amazon.com/ses/pricing/)。本站只寄交易信件，量很小。
- 查核時的現況（2026-11-15，公開 DNS 查詢）：`khwebsc.com` 的 DNS 在 Cloudflare；根網域沒有 MX、SPF、DMARC，`mail.khwebsc.com` 沒有任何紀錄。所以下面新增的紀錄不會和既有設定衝突。
- 全部完成後，請把第 10 節的兩個值告訴 agent，由 agent 準備 v0.0.16 的 PR。

| 本文使用的值 | 說明 |
|---|---|
| `<REGION>` | EC2 所在的 AWS region，第 1 節查出 |
| `<ACCOUNT_ID>` | AWS 帳號 ID，第 1 節查出 |
| `<ROLE_NAME>` | EC2 instance role 的名稱，第 1 節查出 |
| `<INSTANCE_ID>` | EC2 instance ID，第 1 節查出 |
| `noreply@khwebsc.com` | 寄件地址（建議值，可以改） |
| `mail.khwebsc.com` | 自訂 MAIL FROM 網域（建議值，可以改） |
| `<YOUR_EMAIL>` | 你自己的信箱，測試用 |

## 1. 在 EC2 上查出 region、instance 與 role

在 EC2 上執行（只讀）：

```bash
TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/placement/region; echo
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id; echo
aws sts get-caller-identity --query '[Account,Arn]' --output text
```

- 第 1 行輸出是 `<REGION>`，例如 `ap-northeast-1`。
- 第 2 行是 `<INSTANCE_ID>`，形如 `i-0abc…`。
- 最後一行是 `<ACCOUNT_ID>`，以及形如 `arn:aws:sts::<ACCOUNT_ID>:assumed-role/<ROLE_NAME>/<INSTANCE_ID>` 的 ARN，從中取出 `<ROLE_NAME>`。

**SES 一律使用這個 region。** SES 的網域驗證、sandbox 狀態與 production access 都是依 region 分開的；在別的 region 驗證的網域，在這個 region 不能用。

## 2. 在 SES 建立網域 identity（含 DKIM 與 MAIL FROM）

來源：[Creating a domain identity](https://docs.aws.amazon.com/ses/latest/dg/creating-identities.html)、[Easy DKIM](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim-easy.html)、[Custom MAIL FROM domain](https://docs.aws.amazon.com/ses/latest/dg/mail-from.html)。

1. 登入 AWS Console，右上角切換到 `<REGION>`。
2. 開啟 **Amazon SES** → 左側 **Configuration** → **Identities** → **Create identity**。
3. **Identity type** 選 **Domain**，Domain 填 `khwebsc.com`（不要加 `www.`）。
4. 勾選 **Use a custom MAIL FROM domain**：
   - MAIL FROM domain 填 `mail`（完整網域會是 `mail.khwebsc.com`）。
   - **Behavior on MX failure** 選 **Use default MAIL FROM domain**。這樣即使 MX 紀錄出問題，信仍然寄得出去，只是 SPF 會退回 SES 預設網域；選 Reject message 則會直接寄不出去。
5. **Verifying your domain**：選 **Easy DKIM**，**DKIM signing key length** 保持 **RSA_2048_BIT**。不要勾選「Publish DNS records to Route53」，因為 DNS 在 Cloudflare。
6. 按 **Create identity**。
7. 進入這個 identity 的頁面，在 **Publish DNS records** 區塊找到：
   - 3 筆 **DKIM** 的 CNAME；
   - **Custom MAIL FROM domain** 的 1 筆 MX 與 1 筆 TXT。

   先留在這頁，下一節要逐筆複製。

## 3. 在 Cloudflare 新增 DNS 紀錄

開啟 Cloudflare → `khwebsc.com` → **DNS** → **Records** → **Add record**。逐筆新增下表的紀錄。

**Name 欄位只填子網域部分，不要填完整網域。** Cloudflare 的 Name 是相對於 `khwebsc.com` 的；填入 `mail.khwebsc.com` 這類完整名稱時，可能會被再接上一次網域，變成 `mail.khwebsc.com.khwebsc.com`（2026-11-15 實際發生過，造成 MAIL FROM 驗證失敗、測試信的 SPF 顯示 None）。存檔後請看 Cloudflare 列表中的 Name 欄，必須顯示 `mail`、`_dmarc`、`abc123._domainkey`，不能出現兩次 `khwebsc.com`。

**最重要的一點：所有紀錄的 Proxy status 都必須是 DNS only（灰色雲）。** CNAME 在 Cloudflare 預設是 Proxied（橘色雲）。若保持 Proxied，Cloudflare 會改寫解析結果，SES 的 DKIM 驗證永遠不會通過。

| # | Type | Name（Cloudflare 欄位） | Content | 其他 |
|---|---|---|---|---|
| 1～3 | CNAME | SES 表格中 DKIM 的 Name **去掉結尾的 `.khwebsc.com`**，只填 `abc123._domainkey` | SES 表格中對應的 Value，形如 `abc123.dkim.amazonses.com` | Proxy status：**DNS only** |
| 4 | MX | `mail` | `feedback-smtp.<REGION>.amazonses.com` | Priority：`10` |
| 5 | TXT | `mail` | `v=spf1 include:amazonses.com ~all` | Cloudflare 會自動處理引號 |
| 6 | TXT | `_dmarc` | `v=DMARC1; p=none;` | 見下方說明 |

- 第 4、5 筆一律以 SES 頁面顯示的值為準。上表是依官方文件格式寫出的預期值，複製時注意 region 是否一致。
- **DMARC（第 6 筆）**：SES 的 DMARC 文件建議先用 `p=none`（只觀察，不影響投遞），確認一段時間沒有問題後，再改成 `p=quarantine`，最後 `p=reject`（[DMARC](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dmarc.html)）。要收 DMARC 報告的話，可以寫成 `v=DMARC1; p=none; rua=mailto:<收報告的信箱>`。報告信箱如果不在 `khwebsc.com` 底下，該信箱的網域必須另外授權接收，一般個人信箱通常收不到；不需要報告的話，省略 `rua` 即可。
- 不要在根網域 `khwebsc.com` 新增 SPF。SPF 只放在 `mail.khwebsc.com`，因為 SES 的退信地址（MAIL FROM）是這個子網域。

新增後，可以在任何電腦上確認公開 DNS 已經生效（把 `<DKIM_NAME>` 換成第 1 筆的 Name）：

```bash
curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=<DKIM_NAME>.khwebsc.com&type=CNAME'
curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=mail.khwebsc.com&type=MX'
curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=mail.khwebsc.com&type=TXT'
curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=_dmarc.khwebsc.com&type=TXT'
```

另外確認沒有建錯位置（下面這行應該回傳空的 `Answer`）：

```bash
curl -s -H 'accept: application/dns-json' 'https://cloudflare-dns.com/dns-query?name=mail.khwebsc.com.khwebsc.com&type=MX'
```

每一筆的 `Answer` 都要有你剛填的值。CNAME 的答案如果是 Cloudflare 的 IP，而不是 `….dkim.amazonses.com`，就表示 Proxy 沒有關掉。

## 4. 等待 SES 驗證完成

回到 SES 的 identity 頁面，等到以下三項全部完成：

- **Identity status**：**Verified**
- **DKIM configuration**：**Successful**
- **Custom MAIL FROM domain**：**Success**

官方文件說 DNS 變更最長可能需要 72 小時才會生效（[Easy DKIM](https://docs.aws.amazon.com/ses/latest/dg/send-email-authentication-dkim-easy.html)），Cloudflare 通常幾分鐘內就會生效。若超過幾小時仍是 Pending，回頭用第 3 節的指令檢查紀錄與 Proxy status。

## 5. 在 sandbox 內先測試一次

新開的 SES 帳號都在 sandbox 中：只能寄給已驗證的地址、每 24 小時最多 200 封、每秒最多 1 封（[Production access](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html)）。

1. SES → **Identities** → **Create identity** → **Email address** → 填 `<YOUR_EMAIL>` → 建立後，到信箱點擊驗證信。
2. 回到 `khwebsc.com` 這個 identity → 右上角 **Send test email**：
   - From address：`noreply`
   - Scenario：**Custom**，Custom recipient 填 `<YOUR_EMAIL>`
   - Subject 與 Body 任意填寫。
3. 收到信後，在信箱中查看原始郵件（Gmail：右上角 ⋮ → 「顯示原始郵件」），確認 `SPF: PASS`、`DKIM: PASS`、`DMARC: PASS`。

## 6. 申請 production access

完成後才能寄給任何註冊會員。這一步只能由帳號擁有者申請。

1. SES → 左側 **Get set up**（或 **Account dashboard**）→ **Request production access**。
2. 依序填寫：
   - **Mail type**：**Transactional**
   - **Website URL**：`https://khwebsc.com`
   - **Use case description**：可以直接使用下面的英文範本（AWS 審核以英文為主）
   - **Additional contacts**：選填，最多 4 個信箱，用來接收審核通知
   - **Preferred contact language**：English
   - 勾選同意只寄給要求收信的人，並有處理退信與投訴的流程
3. 送出。官方文件說 AWS Support 會在 **96 小時內**初步回覆；需要補充資料時會更久，審核期間不能修改申請內容。

Use case description 範本：

```text
khwebsc.com ("好想找書") is a book discovery website. We only send transactional emails that a user triggers directly:
1) an email-address verification link when a user registers,
2) a password-reset link when a user requests it on the "forgot password" page (at most once per hour per account),
3) a "your password was changed" notice after a successful reset.
We never send marketing or bulk email and never send to purchased or scraped lists. Recipients are only our own registered users.
Expected volume is low (well under 1,000 emails per day).
Bounces and complaints: we rely on the SES account-level suppression list (enabled by default) so we never resend to addresses that
hard-bounced or complained, and we monitor bounce and complaint rates in the SES reputation dashboard.
```

## 7. 讓 EC2 instance role 可以寄信

來源：[Controlling access to SES](https://docs.aws.amazon.com/ses/latest/dg/control-user-access.html)、[SES v2 actions, resources and condition keys](https://docs.aws.amazon.com/service-authorization/latest/reference/list_sesv2.html)。

網站使用 AWS SDK 的預設 credential 鏈，也就是 EC2 instance role；不需要也不應該建立 access key。

1. AWS Console → **IAM** → **Roles** → 搜尋 `<ROLE_NAME>` → **Add permissions** → **Create inline policy** → **JSON**。
2. 貼上以下內容，替換 `<REGION>` 與 `<ACCOUNT_ID>`：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BookFinderSendTransactionalMail",
      "Effect": "Allow",
      "Action": "ses:SendEmail",
      "Resource": "arn:aws:ses:<REGION>:<ACCOUNT_ID>:identity/khwebsc.com"
    }
  ]
}
```

3. Policy name 填 `book-finder-ses-send`，按 **Create policy**。

說明：
- 權限只限 `ses:SendEmail`，而且只能使用 `khwebsc.com` 這個 identity。
- 官方範例另外用 `ses:FromAddress` 限制寄件地址。網站的寄件地址可能帶顯示名稱，例如 `好想找書 <noreply@khwebsc.com>`，所以這裡先不加這個條件，避免意外被拒。
- sandbox 期間（第 6 節尚未核准時）用第 9 節測試，如果錯誤訊息說對某個 email identity 沒有權限，代表 sandbox 的收件者 identity 也需要授權。請把錯誤訊息貼給 agent，再決定要不要暫時加上那個 identity 的 ARN。

## 8. 讓 container 拿得到 instance role（IMDS hop limit）

來源：[Configure instance metadata options](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configuring-instance-metadata-options.html)。

網站在 Docker container 內執行，向 instance metadata 取得 role 憑證時會多經過一層網路。官方文件建議：在 container 環境、且要求 IMDSv2 時，把 hop limit 設為 **2**；hop limit 為 1 時，container 會拿不到憑證。

1. 在你自己的電腦上，用有 EC2 權限的 AWS 身分查詢目前的設定（EC2 上的 instance role 沒有這個權限）：

```bash
aws ec2 describe-instances --region <REGION> --instance-ids <INSTANCE_ID> \
  --query 'Reservations[0].Instances[0].MetadataOptions' --output table
```

2. 如果 `HttpPutResponseHopLimit` 小於 2，執行以下指令修改。修改會立即生效，不需要重開機：

```bash
aws ec2 modify-instance-metadata-options --region <REGION> --instance-id <INSTANCE_ID> \
  --http-put-response-hop-limit 2 --http-endpoint enabled
```

官方文件規定：設定 hop limit 時必須同時帶 `--http-endpoint enabled`。

3. 在 EC2 上，以和網站相同的 docker network 確認 container 拿得到 role（只讀；結束後刪除測試用 image，避免占用磁碟）：

```bash
docker run --rm --network book-finder_web curlimages/curl:8.11.1 -s -o /dev/null -w '%{http_code}\n' \
  -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60'
docker image rm curlimages/curl:8.11.1
```

輸出 `200` 才算通過。如果逾時或沒有輸出，代表 hop limit 還是 1。

## 9. 從 EC2 實際寄一封信

在 EC2 上執行。EC2 host 的 AWS CLI 和 container 使用同一個 instance role，所以這一步可以同時驗證第 6、7 節：

```bash
aws sesv2 send-email --region <REGION> \
  --from-email-address 'noreply@khwebsc.com' \
  --destination 'ToAddresses=<YOUR_EMAIL>' \
  --content 'Simple={Subject={Data=Book-Finder SES test,Charset=UTF-8},Body={Text={Data=SES test from EC2,Charset=UTF-8}}}'
```

- 成功時會輸出 `MessageId`，信箱也會收到信。
- `AccessDenied`：回到第 7 節檢查 policy 的 region、帳號 ID 與 identity 名稱。
- `MessageRejected: Email address is not verified`：仍在 sandbox，而且 `<YOUR_EMAIL>` 尚未驗證；或 production access 尚未核准。

## 10. 交給 agent 的資料

全部通過後，把以下內容告訴 agent。這些都不是 secret：

| 設定 | 值 |
|---|---|
| `Email__Region` | `<REGION>` |
| `Email__From` | `noreply@khwebsc.com`，或含顯示名稱的 `好想找書 <noreply@khwebsc.com>` |
| production access | 已核准／尚未核准 |

agent 會準備 v0.0.16 的 PR，內容如下：

- `compose.prod.yaml` 加上：
  - `Site__PublicBaseUrl: https://khwebsc.com`
  - `Email__Provider: Ses`
  - `Email__From`、`Email__Region`
  - `EmailVerification__Enabled: "true"`
- data migration `BackfillLegacyEmailVerification`：把舊版建立、`email_verified_at` 為 NULL 的帳號回填為已驗證。

上線前請你在 production 確認 `SELECT count(*) FROM users WHERE email_verified_at IS NULL` 為 0（agent 沒有 production DB 連線）。

## 11. 上線後的維護

- **聲譽指標**：SES → **Reputation metrics**（或 **Account dashboard**）可以看到退信率與投訴率。官方文件說，退信率或投訴率過高時，AWS 可能把帳號列入審查或暫停寄信（[Monitoring sender reputation](https://docs.aws.amazon.com/ses/latest/dg/monitor-sender-reputation.html)）。
- **退信名單**：2019-11-25 之後開始使用 SES 的帳號，預設啟用 account-level suppression list，涵蓋 hard bounce 與 complaint。寄給名單上的地址時，SES 會接受請求但不投遞（[Suppression list](https://docs.aws.amazon.com/ses/latest/dg/sending-email-suppression-list.html)）。會員反映收不到信時，先到 SES → **Configuration** → **Suppression list** 搜尋該地址；確認信箱沒問題後，可以移除：

```bash
aws sesv2 delete-suppressed-destination --region <REGION> --email-address <會員的 email>
```

  名單區分大小寫，地址要完全一致。
- **DMARC**：觀察一段時間、確認沒有合法信件失敗後，可以把第 3 節第 6 筆改成 `p=quarantine`。
- **回退**：要停止寄信時，重新部署 v0.0.15（開關關閉）即可。SES 與 DNS 的設定可以保留，不影響網站。
