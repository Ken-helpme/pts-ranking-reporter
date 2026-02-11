# 📊 PTS Ranking Dashboard

モダンでカッコいいWebダッシュボードでPTSランキングを管理・表示！

## ✨ 機能

- 📈 **リアルタイムPTSランキング表示** - 最新のPTS上昇率ランキングをテーブルで表示
- 💾 **過去データ保存** - SQLiteデータベースに履歴を保存して比較可能
- 📊 **ビジュアライゼーション** - Chart.jsでチャートとグラフを表示
- 📱 **レスポンシブデザイン** - スマホでも見やすいモダンなUI
- 🔍 **銘柄詳細** - 各銘柄のニュース、企業情報、過去データを表示

## 🚀 使い方

### 1. ダッシュボードを起動

```bash
# プロジェクトルートから
./start_dashboard.sh

# または直接
cd dashboard
python3 app.py
```

### 2. ブラウザでアクセス

```
http://localhost:5000
```

### 3. データを取得

ダッシュボードの「データ更新」ボタンをクリックして、最新のPTSランキングを取得・保存

## 📁 ファイル構成

```
dashboard/
├── app.py              # Flaskアプリケーション
├── models.py           # データベースモデル
├── pts_data.db         # SQLiteデータベース（自動生成）
├── templates/
│   └── dashboard.html  # ダッシュボードHTML
├── static/
│   ├── css/
│   │   └── style.css   # スタイルシート
│   └── js/
│       └── dashboard.js # JavaScriptロジック
└── README.md           # このファイル
```

## 🎨 デザインの特徴

- グラデーション背景とカード型レイアウト
- ホバーエフェクトとスムーズなアニメーション
- Chart.jsによるインタラクティブなグラフ
- モーダルウィンドウでの詳細表示
- トースト通知

## 🔧 API エンドポイント

- `GET /` - ダッシュボードページ
- `GET /api/latest` - 最新PTSランキング取得
- `GET /api/fetch` - 新しいデータをスクレイピング
- `GET /api/history?days=7&code=1234` - 過去データ取得
- `GET /api/stats` - 統計情報取得
- `GET /api/stock/<code>` - 特定銘柄の詳細

## 💡 Tips

- 自動更新: ページは5分ごとに自動更新されます
- 手動更新: 「データ更新」ボタンで最新データを取得
- 銘柄詳細: テーブルの「詳細」ボタンで企業情報・ニュース・過去データを表示
- レスポンシブ: スマホ・タブレットでも快適に閲覧可能

## 🌐 本番環境へのデプロイ

Google Cloud Platform、AWS、Herokuなどにデプロイ可能です。

詳細は親ディレクトリの `deploy/` フォルダを参照してください。

---

**Made with ❤️ by Claude**
