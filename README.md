# 📰 自社ニュースRSS（マーケティング支援向け）

PR TIMES（全国プレスリリース）と「みんなの経済新聞ネットワーク」（九州・関西・関東の地域版）を
毎朝9時に自動収集し、用途別のRSSフィードを生成・公開するシステム。

## 生成されるフィード

| ファイル | 内容 | 主な用途 |
|---|---|---|
| `feed-eigyo.xml`   | **営業候補まとめ**（出店＋資金調達） | アプローチ先の発見 |
| `feed-shutten.xml` | 新規出店・開業 | 新店オープン営業 |
| `feed-shikin.xml`  | 資金調達・新会社設立 | 予算が動く先への提案 |
| `feed-trend.xml`   | 業界トレンド・市場 | 提案資料のネタ |
| `feed-chiiki.xml`  | 地域経済・自治体 | 地場ネタ・補助金 |
| `feed.xml`         | 全ニュース統合 | 横断チェック |

公開後のURL例: `https://<ユーザー名>.github.io/news-rss/feed-eigyo.xml`
一覧ページ: `https://<ユーザー名>.github.io/news-rss/`

---

## セットアップ（クラウドで毎朝自動稼働 / PC不要）

### 1. GitHubリポジトリを作成
GitHubで新規リポジトリ `news-rss` を作成（Public推奨。Privateの場合Pagesは有料プラン）。

### 2. このフォルダ一式をpush
```bash
cd C:/Users/wish_/news-rss
git init
git add .
git commit -m "init news rss aggregator"
git branch -M main
git remote add origin https://github.com/<ユーザー名>/news-rss.git
git push -u origin main
```

### 3. GitHub Pagesを有効化
リポジトリの **Settings → Pages → Build and deployment → Source** を
**「GitHub Actions」** に設定。

### 4. 初回実行
**Actions** タブ →「build-news-rss」→「Run workflow」で手動実行。
以降は **毎朝9:00(JST)** に自動更新される。

### 5. RSSリーダーに登録
公開URL（上記）を Feedly / Slack(RSSアプリ) / Outlook 等に登録すれば購読完了。

### 6. Slackへ毎朝自動投稿（任意）
1. Slackで対象チャンネルに **Incoming Webhook** を作成
   （https://api.slack.com/messaging/webhooks → 「Create your Slack app」→ Incoming Webhooks 有効化 → Add New Webhook → 投稿先チャンネルを選択 → URL発行）
2. GitHubリポジトリ **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `SLACK_WEBHOOK_URL`
   - Value: 1で発行したWebhook URL
3. 以降、毎朝9時のActions実行時に「今日の営業候補ニュース」が自動投稿される。
   （Secret未設定時は投稿スキップされるだけでエラーにはならない）

---

## ローカルで試す（任意）
```powershell
cd C:\Users\wish_\news-rss
pip install -r requirements.txt
python aggregator.py
# public\index.html をブラウザで開いて確認
```

## AIエンリッチ（任意・精度UP）
`DEEPSEEK_API_KEY` を設定すると、営業候補をAI(DeepSeek)が判定し直し、
**周年/グッズ/コラボだけの記事を除外**＋**1行要約・営業フック・営業価値スコア(⭐1-5)** を付与します。
キー未設定なら従来のキーワードモードで動作（エラーにならない）。

- ローカル: `.env`（`.env.example` をコピー）に `DEEPSEEK_API_KEY=...` を記入
- クラウド: GitHub Secrets に `DEEPSEEK_API_KEY` を登録（手順は上記6と同じ）
- コスト: 新着の営業候補のみ処理。DeepSeekは非常に安価で1日数円以下の見込み

### 🔐 キーが漏れない仕組み
- キーは **環境変数からのみ** 読み込み、**ファイル・ログ・標準出力に一切出力しない**（例外メッセージにも含めない）
- `.env` / `.env.*` / `*.key` は **`.gitignore` 済み** → Gitに上がらない（共有するのは空欄の `.env.example` のみ）
- クラウドでは `.env` を使わず **GitHub Secrets**（ログ上はマスク表示）に保存
- Slack Webhook も同じ扱い

## カスタマイズ
- **収集元の追加/削除**: `sources.yaml`（RSSのURLを足すだけ）
- **分類キーワード**: `keywords.yaml`（業種特化ワードを追加すると精度UP）
- **実行時刻**: `.github/workflows/build.yml` の `cron`（`0 0 * * *` = 朝9時JST）
- **保持期間/件数**: `aggregator.py` 冒頭の `RETENTION_DAYS` 等

> メモ: 死んでいるフィードは自動スキップされ、Actionsログに `WARN` で残ります。
> 不要なら `sources.yaml` から削除してください。
