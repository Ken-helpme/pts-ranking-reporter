# AWS Lambda デプロイ手順

このディレクトリには、PTSランキングレポーターをAWS Lambdaにデプロイするためのファイルが含まれています。

## 前提条件

- AWS CLIがインストール・設定済み
- LINE Notify トークンを取得済み
- Python 3.11以上

## デプロイ手順

### 1. 依存パッケージのインストール

```bash
# プロジェクトルートから実行
cd pts-ranking-reporter

# 依存パッケージをディレクトリにインストール
mkdir -p deploy/aws/package
pip install -r deploy/aws/requirements.txt -t deploy/aws/package/
```

### 2. ソースコードのコピー

```bash
# srcディレクトリをpackageにコピー
cp -r src/* deploy/aws/package/
cp deploy/aws/lambda_function.py deploy/aws/package/
```

### 3. デプロイパッケージの作成

```bash
# packageディレクトリに移動してzipファイルを作成
cd deploy/aws/package
zip -r ../pts-reporter-lambda.zip .
cd ..
```

### 4. Lambda関数の作成

```bash
# Lambda関数を作成（初回のみ）
aws lambda create-function \
  --function-name pts-ranking-reporter \
  --runtime python3.11 \
  --role arn:aws:iam::YOUR_ACCOUNT_ID:role/lambda-execution-role \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://pts-reporter-lambda.zip \
  --timeout 300 \
  --memory-size 512 \
  --environment Variables="{LINE_NOTIFY_TOKEN=your_token_here,MIN_VOLUME=10000,TOP_N=10}"
```

### 5. Lambda関数の更新（コード変更時）

```bash
# コードを更新
aws lambda update-function-code \
  --function-name pts-ranking-reporter \
  --zip-file fileb://pts-reporter-lambda.zip
```

### 6. EventBridgeでスケジュール設定

#### 6-1. EventBridgeルールの作成

```bash
# 毎日18:00 JST（09:00 UTC）に実行
aws events put-rule \
  --name pts-reporter-daily-schedule \
  --schedule-expression "cron(0 9 * * ? *)" \
  --description "Daily PTS ranking report at 18:00 JST"
```

#### 6-2. Lambda関数に実行権限を付与

```bash
aws lambda add-permission \
  --function-name pts-ranking-reporter \
  --statement-id pts-reporter-event \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:REGION:ACCOUNT_ID:rule/pts-reporter-daily-schedule
```

#### 6-3. ターゲットの設定

```bash
aws events put-targets \
  --rule pts-reporter-daily-schedule \
  --targets "Id"="1","Arn"="arn:aws:lambda:REGION:ACCOUNT_ID:function:pts-ranking-reporter"
```

## 環境変数

以下の環境変数をLambda関数に設定してください：

- `LINE_NOTIFY_TOKEN`: LINE Notifyアクセストークン（必須）
- `MIN_VOLUME`: 最小出来高（デフォルト: 10000）
- `TOP_N`: 取得する上位銘柄数（デフォルト: 10）

### 環境変数の更新

```bash
aws lambda update-function-configuration \
  --function-name pts-ranking-reporter \
  --environment Variables="{LINE_NOTIFY_TOKEN=your_new_token,MIN_VOLUME=10000,TOP_N=10}"
```

## テスト実行

```bash
# Lambda関数を手動で実行
aws lambda invoke \
  --function-name pts-ranking-reporter \
  --payload '{}' \
  response.json

# 結果を確認
cat response.json
```

## ログの確認

```bash
# CloudWatch Logsでログを確認
aws logs tail /aws/lambda/pts-ranking-reporter --follow
```

## トラブルシューティング

### タイムアウトエラー

Lambda関数のタイムアウト時間を延長してください（最大15分）：

```bash
aws lambda update-function-configuration \
  --function-name pts-ranking-reporter \
  --timeout 900
```

### メモリ不足エラー

メモリサイズを増やしてください：

```bash
aws lambda update-function-configuration \
  --function-name pts-ranking-reporter \
  --memory-size 1024
```

### パッケージサイズが大きすぎる場合

Lambda Layersを使用してください：

```bash
# Layerを作成
cd deploy/aws/package
zip -r dependencies.zip .

aws lambda publish-layer-version \
  --layer-name pts-reporter-dependencies \
  --zip-file fileb://dependencies.zip \
  --compatible-runtimes python3.11

# Lambda関数にLayerを追加
aws lambda update-function-configuration \
  --function-name pts-ranking-reporter \
  --layers arn:aws:lambda:REGION:ACCOUNT_ID:layer:pts-reporter-dependencies:1
```

## コスト見積もり

- Lambda実行時間: 約30-60秒/日
- 月間実行回数: 30回
- 推定コスト: $0.01未満/月（無料枠内）

## セキュリティ

- LINE_NOTIFY_TOKENはAWS Secrets Managerに保存することを推奨
- Lambda実行ロールは最小権限の原則に従って設定
