#!/bin/bash
# 自動PTS分析スクリプト（cron用）
# cronはシェルの環境変数を読み込まないので、ここで直接設定する

# === Claude API Key（~/.config/anthropic/api_key から読み込み） ===
if [ -f "$HOME/.config/anthropic/api_key" ]; then
    export ANTHROPIC_API_KEY=$(cat "$HOME/.config/anthropic/api_key")
fi

# === 作業ディレクトリ ===
cd /Users/ken/pts-ranking-reporter

echo "========================================="
echo "⏰ 自動PTS分析開始 - $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================="

# API Keyの確認
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "❌ エラー: ANTHROPIC_API_KEYが設定されていません"
    exit 1
fi
echo "✅ Claude API Key: 確認済み"

# 分析実行
echo ""
echo "🚀 分析開始..."
python3 /Users/ken/pts-ranking-reporter/fetch_and_analyze_pts.py

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ 分析完了 - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "📊 ダッシュボード: http://localhost:5001"
else
    echo "❌ 分析失敗（エラーコード: $EXIT_CODE）"
fi

echo "========================================="
echo ""
