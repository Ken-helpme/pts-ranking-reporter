"""
銘柄チャート画像を取得・生成するモジュール
"""
import requests
from PIL import Image
from io import BytesIO
import os
import time
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ChartGenerator:
    """銘柄チャート画像を取得・生成するクラス"""

    KABUTAN_CHART_URL = "https://kabutan.jp/stock/chart"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
    }

    def __init__(self, chart_dir: str = '/tmp/charts', request_delay: float = 1.0):
        """
        Args:
            chart_dir: チャート画像の保存ディレクトリ
            request_delay: リクエスト間の待機時間（秒）
        """
        self.chart_dir = chart_dir
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

        # ディレクトリが存在しない場合は作成
        os.makedirs(self.chart_dir, exist_ok=True)

    def fetch_chart(self, stock_code: str, chart_type: str = 'd') -> Optional[str]:
        """
        指定された銘柄のチャート画像を取得

        Args:
            stock_code: 銘柄コード
            chart_type: チャートタイプ
                - 'd': 日足
                - 'w': 週足
                - 'm': 月足

        Returns:
            str: 保存されたチャート画像のパス、失敗時はNone
        """
        try:
            time.sleep(self.request_delay)  # レート制限対策

            # 株探のチャート画像URL
            # 注意: 実際のURLは株探のHTML構造に合わせて調整が必要
            chart_url = f"{self.KABUTAN_CHART_URL}?code={stock_code}&span={chart_type}"
            logger.info(f"Fetching chart for stock {stock_code}")

            response = self.session.get(chart_url, timeout=30)
            response.raise_for_status()

            # 画像データを取得
            image = Image.open(BytesIO(response.content))

            # 画像を保存
            chart_path = os.path.join(self.chart_dir, f"{stock_code}_chart.png")
            image.save(chart_path)

            logger.info(f"Chart saved: {chart_path}")
            return chart_path

        except requests.RequestException as e:
            logger.error(f"Error fetching chart for stock {stock_code}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error processing chart image: {e}")
            return None

    def fetch_chart_from_url(self, stock_code: str, image_url: str) -> Optional[str]:
        """
        指定されたURLからチャート画像を取得

        Args:
            stock_code: 銘柄コード
            image_url: チャート画像のURL

        Returns:
            str: 保存されたチャート画像のパス、失敗時はNone
        """
        try:
            time.sleep(self.request_delay)

            logger.info(f"Fetching chart from URL: {image_url}")
            response = self.session.get(image_url, timeout=30)
            response.raise_for_status()

            # 画像データを取得
            image = Image.open(BytesIO(response.content))

            # 画像を保存
            chart_path = os.path.join(self.chart_dir, f"{stock_code}_chart.png")
            image.save(chart_path)

            logger.info(f"Chart saved: {chart_path}")
            return chart_path

        except Exception as e:
            logger.error(f"Error fetching chart from URL: {e}")
            return None

    def get_kabutan_chart_url(self, stock_code: str, chart_type: str = 'd',
                              width: int = 600, height: int = 400) -> str:
        """
        株探のチャート画像URLを生成

        Args:
            stock_code: 銘柄コード
            chart_type: チャートタイプ ('d', 'w', 'm')
            width: 画像幅
            height: 画像高さ

        Returns:
            str: チャート画像URL
        """
        # 株探のチャート画像URL（推測）
        # 実際のURLは株探のサイトを確認して調整が必要
        base_url = "https://kabutan.jp/stock/chart"
        return f"{base_url}?code={stock_code}&span={chart_type}&width={width}&height={height}"

    def cleanup_old_charts(self, max_age_hours: int = 24):
        """
        古いチャート画像を削除

        Args:
            max_age_hours: 削除する画像の経過時間（時間単位）
        """
        import time

        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        deleted_count = 0
        for filename in os.listdir(self.chart_dir):
            file_path = os.path.join(self.chart_dir, filename)

            if os.path.isfile(file_path):
                file_age = current_time - os.path.getmtime(file_path)

                if file_age > max_age_seconds:
                    try:
                        os.remove(file_path)
                        deleted_count += 1
                        logger.info(f"Deleted old chart: {filename}")
                    except Exception as e:
                        logger.warning(f"Error deleting file {filename}: {e}")

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old chart images")

    def create_placeholder_chart(self, stock_code: str, stock_name: str) -> str:
        """
        プレースホルダーチャート画像を生成（データ取得失敗時用）

        Args:
            stock_code: 銘柄コード
            stock_name: 銘柄名

        Returns:
            str: 生成されたプレースホルダー画像のパス
        """
        from PIL import ImageDraw, ImageFont

        # 画像を作成
        width, height = 600, 400
        image = Image.new('RGB', (width, height), color=(240, 240, 240))
        draw = ImageDraw.Draw(image)

        # テキストを描画
        text = f"[{stock_code}] {stock_name}\nチャート画像取得中..."

        try:
            # システムフォントを使用（フォントが見つからない場合はデフォルト）
            font = ImageFont.load_default()
        except:
            font = None

        # テキストを中央に配置
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        position = ((width - text_width) // 2, (height - text_height) // 2)
        draw.text(position, text, fill=(100, 100, 100), font=font)

        # 画像を保存
        chart_path = os.path.join(self.chart_dir, f"{stock_code}_placeholder.png")
        image.save(chart_path)

        return chart_path

    def close(self):
        """セッションをクローズ"""
        self.session.close()


if __name__ == "__main__":
    # テスト実行
    generator = ChartGenerator()
    try:
        # テスト用銘柄コード（トヨタ自動車）
        test_code = "7203"

        # プレースホルダー画像を生成（実際のチャート取得は株探のURL構造確認が必要）
        chart_path = generator.create_placeholder_chart(test_code, "トヨタ自動車")
        print(f"Placeholder chart created: {chart_path}")

        # 古いチャートのクリーンアップ
        generator.cleanup_old_charts(max_age_hours=24)

    finally:
        generator.close()
