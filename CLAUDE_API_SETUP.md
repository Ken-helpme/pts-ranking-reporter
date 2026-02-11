# Claude API設定ガイド

## 🔑 Claude APIキーの取得

1. **Anthropic Consoleにアクセス**
   - https://console.anthropic.com/

2. **APIキーを作成**
   - 「API Keys」セクションに移動
   - 「Create Key」をクリック
   - キーをコピー（一度しか表示されません）

## 💻 環境変数の設定

### macOS / Linux

```bash
# ~/.bash_profile または ~/.zshrc に追加
export ANTHROPIC_API_KEY='your-api-key-here'

# 設定を反映
source ~/.bash_profile  # または source ~/.zshrc
```

### 一時的に設定（現在のセッションのみ）

```bash
export ANTHROPIC_API_KEY='your-api-key-here'
```

### 確認

```bash
echo $ANTHROPIC_API_KEY
```

## 🚀 使い方

APIキーを設定すると、以下の機能が有効になります：

### 1. 決算の深掘り分析

決算発表があった銘柄について：
- **なぜ好決算/上方修正になったか** を自動で分析
- **主要な要因**（売上増加、コスト削減など）を抽出
- **今後の見通し** を予測

### 2. ダッシュボードで確認

1. ダッシュボードを起動
   ```bash
   ./start_dashboard.sh
   ```

2. 「データ更新」ボタンをクリック

3. 決算銘柄の「詳細」を開く

4. **📊 決算分析**セクションに表示：
   - 決算内容の説明
   - 主要な要因（箇条書き）
   - 今後の見通し

## 💡 API未設定の場合

APIキーがなくても基本機能は動作します：
- キーワードベースの簡易分析
- 上昇理由のまとめ
- 将来性評価

ただし、決算の深掘り分析には**Claude APIが必須**です。

## 📊 分析例

### API設定あり（Claude分析）
```
【決算内容】
売上高が前年同期比で25%増加し、過去最高を更新。主要事業の受注残高が
積み上がっており、今期の業績予想を上方修正した。

【主要な要因】
1. 主力製品の需要急増により売上が大幅増加
2. 生産効率改善によるコスト削減で利益率が向上
3. 新規大型契約の獲得により受注残高が拡大

【今後の見通し】
受注残高が積み上がっており、今後も堅調な業績が見込まれる。来期も
増益基調が続くと予想される。
```

### API未設定（キーワード分析）
```
【決算内容】
業績予想を上方修正。

【主要な要因】
1. 業績が当初予想を上回る

【今後の見通し】
詳細は開示資料をご確認ください。Claude API設定で自動分析可能です。
```

## 🔒 セキュリティ

- APIキーは**絶対に**GitHubにプッシュしないでください
- 環境変数で管理することを推奨
- `.env`ファイルを使う場合は`.gitignore`に追加

## 💰 料金

Claude API（3.5 Sonnet）の料金：
- Input: $3 / 1M tokens
- Output: $15 / 1M tokens

1銘柄の決算分析あたり：
- 約500-1000 tokens（入力）
- 約200-500 tokens（出力）
- **約$0.01-0.02 / 銘柄**

毎日20銘柄を分析しても、月額**約$10-15程度**です。

## 🆘 トラブルシューティング

### エラー: "ANTHROPIC_API_KEY not set"

```bash
# APIキーが設定されているか確認
echo $ANTHROPIC_API_KEY

# 未設定の場合
export ANTHROPIC_API_KEY='your-api-key-here'
```

### エラー: "API returned error: 401"

- APIキーが無効または期限切れ
- Console で新しいキーを作成

### エラー: "API returned error: 429"

- レート制限に達した
- 少し待ってから再試行

---

**Made with ❤️ by Claude**
