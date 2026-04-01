# コンサル音声テキスト整理ツール

美容室オーナーとのコンサルをテキスト化した内容を、Claude API で整理（課題・改善案の Markdown）します。

- **CLI**: `main.py` … `input/*.txt` を読み `output/*.md` に保存
- **LINE Bot**: `app.py` … LINE に送ったテキストを同じ分析ロジックで処理し、プッシュで結果を返す

## 必要環境

- Python 3.10 以上推奨
- Anthropic API キー
- LINE Bot 利用時: LINE Developers のチャネルシークレット・アクセストークン（実装は公式 Webhook 署名検証 + Messaging API の HTTP 呼び出しのみ）

## GitHub に初回 push（このフォルダ単体のリポジトリ）

ローカルでは `consul-analyzer` を **独立した Git リポジトリ**にしてあり、`origin` は  
`https://github.com/nynyzeni-dot/consul-analyzer.git` を指します。

1. GitHub で **空の** リポジトリ `consul-analyzer` を作成する（README・.gitignore の追加は不要）。
2. ターミナルで次を実行する。

   ```bash
   cd consul-analyzer
   git push -u origin main
   ```

3. 認証が求められたら、GitHub の Personal Access Token または SSH を設定する。

`input/*.txt` と `output/*.md` は `.gitignore` で除外してあり、クライアント別の文字起こし・分析結果はリポジトリに含まれません。

## ローカルセットアップ（CLI）

```bash
cd consul-analyzer
pip install -r requirements.txt
cp .env.example .env
# .env に ANTHROPIC_API_KEY を記入
python main.py
```

## ローカルセットアップ（LINE Bot）

1. `.env` に次を設定する。

   | 変数 | 説明 |
   |------|------|
   | `LINE_CHANNEL_SECRET` | LINE Developers → チャネル → 「チャネルシークレット」 |
   | `LINE_CHANNEL_ACCESS_TOKEN` | 同じく「チャネルアクセストークン（長期）」 |
   | `ANTHROPIC_API_KEY` | Anthropic コンソールで発行したキー |

2. 依存関係を入れる（上記 CLI と同じ）。

   ```bash
   pip install -r requirements.txt
   ```

3. 開発時は Flask で起動する。

   ```bash
   set PORT=5000
   python app.py
   ```

4. **HTTPS の Webhook URL** が必要なため、ローカルでは [ngrok](https://ngrok.com/) などで `https://xxxx.ngrok.io/callback` を公開し、LINE Developers の「Webhook URL」にその URL を登録する。

5. Webhook の「利用する」をオンにする。

6. ボットを友だち追加し、**テキストメッセージ**でコンサル文面を送る。まず「分析しています」と返り、完了後に分析結果がプッシュで届く。

### Notion 連携（LINE 経由の分析結果を議事録 DB に保存）

- `NOTION_API_KEY` を設定すると、分析完了後に **議事録データベースへ新規ページ**が追加されます。
- **タイトル（議事録）**: `（LINE表示名） YYYY-MM-DD`
- **ページ本文**: 「数字サマリー」「課題（優先度順）」「改善アクション（3つ）」を Claude 出力から抽出して見出し＋段落で配置。
- **プロパティ**: DB を `retrieve` してスキーマに合わせ、`日付`・`会社名`（LINE名と選択肢が一致するときのみ）・`ステータス`（あれば先頭候補など）を可能な範囲で設定。
- Notion のインテグレーションに、対象データベースへの**接続**が必要です。`pages.create` が 404 / object_not_found のときは `NOTION_DATABASE_ID` を Notion の「データベース ID」に変更するか、インテグレーションの共有設定を確認してください。

### 動作の注意

- 分析はバックグラウンドで実行するため、LINE の Webhook はすぐ `200 OK` を返せます。
- 結果は **プッシュメッセージ**で送ります（1通が長い場合は複数通に分割）。
- 見出しのクライアント名には、可能なら **LINE の表示名**を使います。

## Railway にデプロイする手順

1. 上記どおり **GitHub に `main` を push** しておく。

2. [Railway](https://railway.app/) にログインし、**New Project** → **Deploy from GitHub** で `nynyzeni-dot/consul-analyzer` を選ぶ。

3. このリポジトリはルートがそのままアプリなので、**Root Directory の変更は不要**（モノレポで親フォルダを繋いだ場合だけ `consul-analyzer` に設定）。

4. サービスの **Variables** に以下を登録する。

   - `LINE_CHANNEL_SECRET`
   - `LINE_CHANNEL_ACCESS_TOKEN`
   - `ANTHROPIC_API_KEY`
   - 任意: `ANTHROPIC_MODEL`（未設定時は `claude-sonnet-4-5`）
   - **Notion 連携**: `NOTION_API_KEY`（未設定なら Notion 保存のみスキップ）
   - 任意: `NOTION_DATABASE_ID`（省略時は `26c708db-dcc2-4c1e-bc44-95a8df53c329`。`pages.create` が失敗する場合は Notion のデータベース ID を指定）

5. デプロイ完了後、サービス画面の **Settings** → **Networking**（または **Generate Domain**）で **公開 URL** を発行する。Railway が付与するドメインはプロジェクトごとに異なり、例として `https://xxxx.up.railway.app` の形式になる。

6. LINE Developers の **Webhook URL** を  
   `https://（手順5のドメイン）/callback`  
   に設定し、接続検証する。

7. ボットの応答設定で Webhook を利用する。

`Procfile` と `railway.toml` の `startCommand` で `gunicorn` を **`$PORT` にバインド**して起動します。ヘルスチェックは `/`（タイムアウト 120 秒）。

### ヘルスチェック

ブラウザや `curl` で `https://（手順5のドメイン）/` にアクセスすると `ok` が返ればプロセスは起動しています。

## ファイル構成

| ファイル | 役割 |
|----------|------|
| `analyzer.py` | Claude 分析ロジック（CLI・LINE 共通） |
| `main.py` | バッチ処理 CLI |
| `app.py` | LINE Webhook（Flask） |
| `railway_run.py` | Railway 用: `PORT` を読んで gunicorn を起動 |
| `notion_sync.py` | 分析結果を Notion 議事録 DB に保存 |
| `Procfile` | Railway / 起動定義 |
| `input/` | CLI 用の入力 `.txt` |
| `output/` | CLI 用の出力 `.md` |

## トラブルシュート

- **403 / Invalid signature**: `LINE_CHANNEL_SECRET` の誤り、またはプロキシがボディを改変していないか確認。
- **503 on /callback**: `LINE_CHANNEL_*` が未設定。Railway の Variables を確認。
- **Claude エラー**: `ANTHROPIC_API_KEY` と `ANTHROPIC_MODEL`（モデル名が API で有効か）を確認。
- **デプロイが Removed / Container Stopping**: ログで gunicorn の bind 先が `$PORT` か確認。ヘルスチェック失敗の場合は Railway の Variables に `PORT` を手動で入れない（プラットフォームが自動付与）。Windows 由来の CRLF でシェルが落ちる場合は `.gitattributes` で `*.sh` を LF に固定する（本リポジトリは `start.sh` を使わず `gunicorn` 直起動）。
