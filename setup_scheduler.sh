#!/bin/bash
# Cloud Scheduler セットアップスクリプト
# 毎週日曜深夜に /api/screening/auto_optimize を呼んで自動最適化
#
# 使い方:
#   chmod +x setup_scheduler.sh
#   ./setup_scheduler.sh

set -e

PROJECT_ID="son-app-project"
REGION="asia-northeast1"
SERVICE="pts-ranking-reporter"
JOB_NAME="pts-auto-optimize-weekly"
SCHEDULE="0 2 * * 0"   # 毎週日曜 02:00 JST (UTC+9 → UTC 17:00 土曜)
TIME_ZONE="Asia/Tokyo"

# Cloud Run サービスの URL を取得
SERVICE_URL=$(gcloud run services describe "$SERVICE" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --format='value(status.url)')

if [ -z "$SERVICE_URL" ]; then
  echo "❌ Cloud Run サービスの URL を取得できませんでした"
  exit 1
fi

ENDPOINT="${SERVICE_URL}/api/screening/auto_optimize"
echo "✅ エンドポイント: $ENDPOINT"

# OPTIMIZE_SECRET を環境変数から取得（任意）
OPTIMIZE_SECRET="${OPTIMIZE_SECRET:-}"

# Cloud Scheduler ジョブを作成または更新
gcloud scheduler jobs create http "$JOB_NAME" \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  --schedule="$SCHEDULE" \
  --time-zone="$TIME_ZONE" \
  --uri="$ENDPOINT" \
  --http-method="POST" \
  --message-body="{}" \
  --headers="Content-Type=application/json${OPTIMIZE_SECRET:+,X-Optimize-Secret=$OPTIMIZE_SECRET}" \
  --attempt-deadline=600s \
  --description="PTSスクリーナー 自動パラメータ最適化（毎週日曜深夜）" \
  2>/dev/null || \
gcloud scheduler jobs update http "$JOB_NAME" \
  --location="$REGION" \
  --project="$PROJECT_ID" \
  --schedule="$SCHEDULE" \
  --time-zone="$TIME_ZONE" \
  --uri="$ENDPOINT" \
  --http-method="POST" \
  --message-body="{}" \
  --headers="Content-Type=application/json${OPTIMIZE_SECRET:+,X-Optimize-Secret=$OPTIMIZE_SECRET}" \
  --attempt-deadline=600s

echo ""
echo "✅ Cloud Scheduler ジョブ '$JOB_NAME' を設定しました"
echo "   スケジュール: $SCHEDULE ($TIME_ZONE)"
echo "   エンドポイント: $ENDPOINT"
echo ""
echo "今すぐ手動実行してテストする場合:"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$PROJECT_ID"
