# PTSランキング自動監視・レポート送信システム

毎日18:00にPTS（私設取引システム）ランキングを自動監視し、上昇率上位の銘柄情報を分析してLINEに送信するシステムです。

## 機能

- 📊 **PTSランキング取得**: 株探からPTS上昇率ランキングを自動取得
- 🔍 **データフィルタリング**: 出来高10,000株未満の銘柄を除外
- 📰 **ニュース取得**: 各銘柄の最新ニュースを自動収集
- 📈 **チャート生成**: 銘柄チャート画像を取得・生成
- 📱 **LINE通知**: LINE Notify経由で整形されたレポートを送信
- ☁️ **クラウド対応**: AWS Lambda / GCP Cloud Functionsで自動実行

## システム要件

- Python 3.11以上
- LINE Notify アクセストークン
- AWS または GCP アカウント（クラウドデプロイ時）

## プロジェクト構成

```
pts-ranking-reporter/
├── src/
│   ├── main.py                 # メインエントリポイント
│   ├── scraper.py              # 株探スクレイピング
│   ├── analyzer.py             # データ分析・フィルタリング
│   ├── news_fetcher.py         # ニュース取得
│   ├── chart_generator.py      # チャート画像取得
│   └── line_notifier.py        # LINE Notify送信
├── config/
│   └── config.yaml             # 設定ファイル
├── deploy/
│   ├── aws/                    # AWS Lambda用ファイル
│   └── gcp/                    # GCP Cloud Functions用ファイル
├── requirements.txt            # Python依存パッケージ
├── .env.template               # 環境変数テンプレート
└── README.md                   # このファイル
```

## セットアップ

### 1. LINE Notify トークンの取得

1. [LINE Notify](https://notify-bot.line.me/my/)にアクセス
2. 「トークンを発行する」をクリック
3. トークン名を入力し、通知先を選択
4. 発行されたトークンをコピー（後で使用）

### 2. ローカル環境でのセットアップ

```bash
# リポジトリをクローン
cd pts-ranking-reporter

# 仮想環境を作成（推奨）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 依存パッケージをインストール
pip install -r requirements.txt

# 環境変数ファイルを作成
cp .env.template .env

# .envファイルを編集してLINE_NOTIFY_TOKENを設定
# nano .env または vi .env
```

### 3. 環境変数の設定

`.env`ファイルを編集：

```bash
LINE_NOTIFY_TOKEN=your_actual_token_here
MIN_VOLUME=10000
TOP_N=10
```

### 4. ローカルでの実行

```bash
# srcディレクトリに移動
cd src

# メインスクリプトを実行
python main.py
```

実行すると、PTSランキングが取得され、LINEにレポートが送信されます。

## クラウドへのデプロイ

### AWS Lambda

詳細は [deploy/aws/README.md](deploy/aws/README.md) を参照してください。

```bash
# 概要
1. 依存パッケージをインストール
2. デプロイパッケージを作成
3. Lambda関数を作成
4. EventBridgeでスケジュール設定（毎日18:00）
```

### GCP Cloud Functions

詳細は [deploy/gcp/README.md](deploy/gcp/README.md) を参照してください。

```bash
# 概要
1. Secret Managerにトークンを保存
2. Cloud Functionsにデプロイ
3. Cloud Schedulerでスケジュール設定（毎日18:00）
```

## 設定のカスタマイズ

### config/config.yaml

```yaml
filtering:
  min_volume: 10000  # 最小出来高（変更可能）
  top_n: 10          # 取得する銘柄数（変更可能）

news:
  max_news_per_stock: 3  # 1銘柄あたりのニュース数

chart:
  chart_dir: "/tmp/charts"
  cleanup_hours: 24
```

### 環境変数

- `LINE_NOTIFY_TOKEN`: LINE Notifyアクセストークン（必須）
- `MIN_VOLUME`: 最小出来高（デフォルト: 10000）
- `TOP_N`: 取得する上位銘柄数（デフォルト: 10）

## レポート例

```
【PTS上昇ランキング - 2026/02/11 18:00】
出来高10,000株以上の上位10銘柄
========================================

1. [1234] ○○○株式会社
━━━━━━━━━━━━━━━━
💰 PTS価格: 1,500円 (+10.5%)
📊 出来高: 150,000株

📌 基本情報:
  • 市場: 東証プライム
  • 業種: 情報・通信業
  • 時価総額: 1,000億円

📰 最新ニュース:
  1. 新製品発表でPTS急騰
     (2026/02/11 15:30)
  2. 業績予想の上方修正を発表
     (2026/02/11 14:00)
  3. 大手企業と業務提携
     (2026/02/10 17:00)

---
[チャート画像が添付されます]
```

## トラブルシューティング

### スクレイピングが失敗する

- 株探のHTML構造が変更された可能性があります
- `src/scraper.py` のセレクタを確認・修正してください
- User-Agentヘッダーが適切か確認してください

### LINE送信が失敗する

- LINE_NOTIFY_TOKENが正しく設定されているか確認
- トークンが有効期限切れでないか確認
- LINE Notifyの利用規約を確認

### タイムアウトエラー

- クラウド環境のタイムアウト設定を延長
- 取得する銘柄数（TOP_N）を減らす
- リクエスト間隔を調整

## 注意事項

### スクレイピングについて

- 株探の利用規約を遵守してください
- robots.txtを確認してください
- アクセス頻度を適切に制限してください（現在: 1秒間隔）
- 商用利用時は株探に確認が必要な場合があります

### LINE Notify

- 1時間あたりの送信上限: 1,000通
- 画像サイズ上限: 1MB
- メッセージ長上限: 1,000文字

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。

## 免責事項

- このツールは教育・個人利用目的で作成されています
- 株探のデータ取得に関しては、自己責任で利用してください
- 投資判断は自己責任で行ってください
- 本ツールの使用によって生じた損害について、作者は一切の責任を負いません

## 貢献

バグ報告や機能改善の提案は、GitHubのIssuesで受け付けています。

## サポート

問題が発生した場合は、以下を確認してください：

1. ログを確認（ローカル実行時は標準出力、クラウドはCloudWatch/Cloud Logging）
2. 環境変数が正しく設定されているか確認
3. 依存パッケージのバージョンを確認
4. インターネット接続を確認

## 今後の改善予定

- [ ] Slack、Discord対応
- [ ] データベース保存機能
- [ ] 過去データとの比較分析
- [ ] Webダッシュボード
- [ ] より詳細なチャート分析
- [ ] アラート条件のカスタマイズ

## 変更履歴

### v1.0.0 (2026-02-11)
- 初回リリース
- 基本機能の実装
- AWS Lambda / GCP Cloud Functions対応

---

**Made with ❤️ for stock traders**
