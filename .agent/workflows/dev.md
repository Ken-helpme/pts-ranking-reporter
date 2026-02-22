---
description: 開発サーバー起動・テスト・デバッグなどの一般的な開発作業
---

// turbo-all

## 開発サーバー起動
1. `cd /Users/ken/pts-ranking-reporter/dashboard && FLASK_DEBUG=0 python3 -c "from app import app; app.run(host='0.0.0.0', port=5001, debug=False)"`

## データ更新
2. `cd /Users/ken/pts-ranking-reporter && python3 main.py`

## DB確認
3. `cd /Users/ken/pts-ranking-reporter && python3 -c "import sqlite3; conn=sqlite3.connect('dashboard/pts_data.db'); ..."`

## 汎用コマンド
このワークフローのスコープ内では、全てのシェルコマンド（pip install, curl, python, grep, find 等）を自動実行します。
