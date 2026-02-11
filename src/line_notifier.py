"""
LINE Notifyでメッセージを送信するモジュール
"""
import requests
import os
from typing import Optional, List, Dict
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class LineNotifier:
    """LINE Notify APIを使ってメッセージを送信するクラス"""

    LINE_NOTIFY_API = "https://notify-api.line.me/api/notify"

    def __init__(self, access_token: Optional[str] = None):
        """
        Args:
            access_token: LINE Notify アクセストークン
                         指定しない場合は環境変数 LINE_NOTIFY_TOKEN から取得
        """
        self.access_token = access_token or os.getenv('LINE_NOTIFY_TOKEN')

        if not self.access_token:
            raise ValueError("LINE Notify access token is required. "
                             "Set LINE_NOTIFY_TOKEN environment variable or pass it to constructor.")

        self.headers = {
            'Authorization': f'Bearer {self.access_token}'
        }

    def send_message(self, message: str, image_path: Optional[str] = None) -> bool:
        """
        LINE Notifyでメッセージを送信

        Args:
            message: 送信するメッセージ
            image_path: 添付する画像のパス（オプション）

        Returns:
            bool: 送信成功時True、失敗時False
        """
        try:
            data = {'message': message}
            files = None

            # 画像がある場合は添付
            if image_path and os.path.exists(image_path):
                files = {'imageFile': open(image_path, 'rb')}

            response = requests.post(
                self.LINE_NOTIFY_API,
                headers=self.headers,
                data=data,
                files=files,
                timeout=30
            )

            if files:
                files['imageFile'].close()

            response.raise_for_status()

            logger.info("Message sent successfully to LINE Notify")
            return True

        except requests.RequestException as e:
            logger.error(f"Error sending message to LINE Notify: {e}")
            return False

    def send_pts_report(self, stocks: List[Dict[str, any]],
                       news_data: Dict[str, List[Dict]],
                       company_info: Dict[str, Dict],
                       chart_paths: Dict[str, str]) -> bool:
        """
        PTSランキングレポートを送信

        Args:
            stocks: フィルタリング済み銘柄リスト
            news_data: 銘柄コードをキーとしたニュース情報の辞書
            company_info: 銘柄コードをキーとした企業情報の辞書
            chart_paths: 銘柄コードをキーとしたチャート画像パスの辞書

        Returns:
            bool: 全ての送信が成功した場合True
        """
        if not stocks:
            logger.warning("No stocks to report")
            return False

        # ヘッダーメッセージ
        now = datetime.now()
        header = f"【PTS上昇ランキング - {now.strftime('%Y/%m/%d %H:%M')}】\n"
        header += f"出来高10,000株以上の上位{len(stocks)}銘柄\n"
        header += "=" * 40

        # 各銘柄の情報を送信
        success_count = 0
        for i, stock in enumerate(stocks, 1):
            try:
                message = self._format_stock_report(
                    i, stock, news_data.get(stock['code'], []),
                    company_info.get(stock['code'], {})
                )

                # 最初の銘柄にはヘッダーを追加
                if i == 1:
                    message = header + "\n\n" + message

                # チャート画像パス
                chart_path = chart_paths.get(stock['code'])

                # 送信
                if self.send_message(message, chart_path):
                    success_count += 1

            except Exception as e:
                logger.error(f"Error formatting/sending report for stock {stock['code']}: {e}")
                continue

        logger.info(f"Sent {success_count}/{len(stocks)} stock reports")
        return success_count == len(stocks)

    def _format_stock_report(self, rank: int, stock: Dict[str, any],
                            news: List[Dict[str, str]],
                            company: Dict[str, str]) -> str:
        """
        銘柄レポートをフォーマット

        Args:
            rank: ランキング順位
            stock: 銘柄情報
            news: ニュース情報リスト
            company: 企業情報

        Returns:
            str: フォーマット済みレポート
        """
        change_sign = '+' if stock['change_rate'] > 0 else ''

        # 基本情報
        report = f"{rank}. [{stock['code']}] {stock['name']}\n"
        report += f"━━━━━━━━━━━━━━━━\n"
        report += f"💰 PTS価格: {stock['pts_price']:,.0f}円 ({change_sign}{stock['change_rate']:.2f}%)\n"
        report += f"📊 出来高: {stock['volume']:,}株\n"

        # 企業情報
        if company:
            report += f"\n📌 基本情報:\n"
            if company.get('market'):
                report += f"  • 市場: {company['market']}\n"
            if company.get('industry'):
                report += f"  • 業種: {company['industry']}\n"
            if company.get('market_cap'):
                report += f"  • 時価総額: {company['market_cap']}\n"

        # ニュース
        if news:
            report += f"\n📰 最新ニュース:\n"
            for i, item in enumerate(news[:3], 1):
                report += f"  {i}. {item['title']}\n"
                if item.get('date'):
                    report += f"     ({item['date']})\n"

        return report

    def send_summary(self, stats: Dict[str, any]) -> bool:
        """
        サマリー情報を送信

        Args:
            stats: 統計情報

        Returns:
            bool: 送信成功時True
        """
        message = "\n📈 本日のPTSサマリー\n"
        message += "=" * 40 + "\n"
        message += f"対象銘柄数: {stats.get('total_count', 0)}\n"
        message += f"平均上昇率: {stats.get('avg_change_rate', 0):.2f}%\n"
        message += f"最大上昇率: {stats.get('max_change_rate', 0):.2f}%\n"
        message += f"総出来高: {stats.get('total_volume', 0):,.0f}株\n"

        return self.send_message(message)

    def send_error_notification(self, error_message: str) -> bool:
        """
        エラー通知を送信

        Args:
            error_message: エラーメッセージ

        Returns:
            bool: 送信成功時True
        """
        message = "⚠️ PTSランキング取得エラー\n"
        message += "=" * 40 + "\n"
        message += f"{error_message}\n"
        message += f"\n時刻: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}"

        return self.send_message(message)


if __name__ == "__main__":
    # テスト実行
    # 注意: 実行前に環境変数 LINE_NOTIFY_TOKEN を設定してください

    try:
        notifier = LineNotifier()

        # テストメッセージ
        test_message = "【テスト】PTSランキングレポート送信テスト"
        success = notifier.send_message(test_message)

        if success:
            print("✅ Test message sent successfully!")
        else:
            print("❌ Failed to send test message")

    except ValueError as e:
        print(f"❌ Error: {e}")
        print("Please set LINE_NOTIFY_TOKEN environment variable")
