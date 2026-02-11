# GCP Cloud Functions デプロイ手順

このディレクトリには、PTSランキングレポーターをGCP Cloud Functionsにデプロイするためのファイルが含まれています。

## 前提条件

- Google Cloud CLIがインストール・設定済み
- GCPプロジェクトが作成済み
- LINE Notify トークンを取得済み
- Cloud Functions API、Cloud Scheduler API、Secret Manager APIが有効化済み

## デプロイ手順

### 1. GCPプロジェクトの設定

```bash
# プロジェクトIDを設定
export PROJECT_ID="your-project-id"
gcloud config set project $PROJECT_ID

# 必要なAPIを有効化
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable cloudscheduler.googleapis.com
gcloud services enable secretmanager.googleapis.com
```

### 2. LINE Notify トークンをSecret Managerに保存

```bash
# Secretを作成
echo -n "your_line_notify_token" | \
  gcloud secrets create line-notify-token \
  --data-file=-

# Secretへのアクセス権限を確認
gcloud secrets describe line-notify-token
```

### 3. デプロイパッケージの準備

```bash
# プロジェクトルートから実行
cd pts-ranking-reporter

# デプロイ用ディレクトリを作成
mkdir -p deploy/gcp/deploy_package
cp -r src/* deploy/gcp/deploy_package/
cp deploy/gcp/main.py deploy/gcp/deploy_package/
cp deploy/gcp/requirements.txt deploy/gcp/deploy_package/
```

### 4. Cloud Functionsにデプロイ

```bash
cd deploy/gcp/deploy_package

gcloud functions deploy pts-ranking-reporter \
  --runtime python311 \
  --trigger-http \
  --allow-unauthenticated \
  --entry-point pts_reporter_handler \
  --timeout 540s \
  --memory 512MB \
  --region asia-northeast1 \
  --set-env-vars MIN_VOLUME=10000,TOP_N=10 \
  --set-secrets LINE_NOTIFY_TOKEN=line-notify-token:latest
```

### 5. Cloud Schedulerでスケジュール設定

```bash
# 毎日18:00 JST（09:00 UTC）に実行するジョブを作成
gcloud scheduler jobs create http pts-reporter-daily \
  --schedule="0 9 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="https://asia-northeast1-${PROJECT_ID}.cloudfunctions.net/pts-ranking-reporter" \
  --http-method=GET \
  --location=asia-northeast1 \
  --description="Daily PTS ranking report at 18:00 JST"
```

## 環境変数

以下の環境変数をCloud Functionsに設定してください：

- `LINE_NOTIFY_TOKEN`: LINE Notifyアクセストークン（Secret Managerから取得）
- `MIN_VOLUME`: 最小出来高（デフォルト: 10000）
- `TOP_N`: 取得する上位銘柄数（デフォルト: 10）

### 環境変数の更新

```bash
gcloud functions deploy pts-ranking-reporter \
  --update-env-vars MIN_VOLUME=20000,TOP_N=5
```

### Secretの更新

```bash
# 新しいトークンをSecretに保存
echo -n "new_line_notify_token" | \
  gcloud secrets versions add line-notify-token \
  --data-file=-
```

## テスト実行

### Cloud Functions コンソールからテスト

1. [Cloud Functions コンソール](https://console.cloud.google.com/functions)を開く
2. `pts-ranking-reporter` 関数を選択
3. 「テスト」タブを開く
4. 「関数をテスト」をクリック

### gcloudコマンドでテスト

```bash
# HTTPリクエストを送信
gcloud functions call pts-ranking-reporter \
  --region=asia-northeast1
```

### curlでテスト

```bash
curl https://asia-northeast1-${PROJECT_ID}.cloudfunctions.net/pts-ranking-reporter
```

## ログの確認

```bash
# Cloud Functionsのログを確認
gcloud functions logs read pts-ranking-reporter \
  --region=asia-northeast1 \
  --limit=50

# リアルタイムでログを監視
gcloud functions logs read pts-ranking-reporter \
  --region=asia-northeast1 \
  --limit=50 \
  --follow
```

## Cloud Schedulerジョブの管理

### ジョブの一時停止

```bash
gcloud scheduler jobs pause pts-reporter-daily \
  --location=asia-northeast1
```

### ジョブの再開

```bash
gcloud scheduler jobs resume pts-reporter-daily \
  --location=asia-northeast1
```

### ジョブの手動実行

```bash
gcloud scheduler jobs run pts-reporter-daily \
  --location=asia-northeast1
```

## トラブルシューティング

### タイムアウトエラー

タイムアウト時間を延長してください（最大540秒）：

```bash
gcloud functions deploy pts-ranking-reporter \
  --timeout=540s
```

### メモリ不足エラー

メモリサイズを増やしてください：

```bash
gcloud functions deploy pts-ranking-reporter \
  --memory=1024MB
```

### Secret Manager アクセスエラー

Cloud Functions のサービスアカウントに適切な権限を付与：

```bash
# プロジェクト番号を取得
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")

# Secret Manager へのアクセス権限を付与
gcloud secrets add-iam-policy-binding line-notify-token \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## コスト見積もり

### Cloud Functions
- 呼び出し回数: 30回/月
- 実行時間: 約30-60秒/回
- メモリ: 512MB
- 推定コスト: $0.01未満/月（無料枠内）

### Cloud Scheduler
- ジョブ数: 1個
- 推定コスト: $0.10/月

### Secret Manager
- シークレット数: 1個
- アクセス回数: 30回/月
- 推定コスト: $0.01未満/月

**合計: 約$0.11/月**

## セキュリティのベストプラクティス

1. **Secret Managerの使用**
   - LINE_NOTIFY_TOKENはSecret Managerに保存
   - 環境変数に直接トークンを含めない

2. **最小権限の原則**
   - Cloud Functionsサービスアカウントに必要最小限の権限のみ付与

3. **認証の設定**
   - 必要に応じて `--no-allow-unauthenticated` でデプロイ
   - Cloud Schedulerからの呼び出しにはサービスアカウント認証を使用

```bash
# 認証ありでデプロイ（より安全）
gcloud functions deploy pts-ranking-reporter \
  --no-allow-unauthenticated

# サービスアカウントを作成
gcloud iam service-accounts create pts-reporter-invoker

# 関数の呼び出し権限を付与
gcloud functions add-iam-policy-binding pts-ranking-reporter \
  --member="serviceAccount:pts-reporter-invoker@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/cloudfunctions.invoker"

# Cloud Schedulerジョブを更新
gcloud scheduler jobs create http pts-reporter-daily \
  --schedule="0 9 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="https://asia-northeast1-${PROJECT_ID}.cloudfunctions.net/pts-ranking-reporter" \
  --http-method=GET \
  --oidc-service-account-email="pts-reporter-invoker@${PROJECT_ID}.iam.gserviceaccount.com" \
  --location=asia-northeast1
```

## クリーンアップ

リソースを削除する場合：

```bash
# Cloud Schedulerジョブを削除
gcloud scheduler jobs delete pts-reporter-daily --location=asia-northeast1

# Cloud Functionを削除
gcloud functions delete pts-ranking-reporter --region=asia-northeast1

# Secretを削除
gcloud secrets delete line-notify-token
```
