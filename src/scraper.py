"""
株探（Kabutan）からPTSランキング情報を取得するモジュール
"""
import requests
from bs4 import BeautifulSoup
import time
from typing import List, Dict, Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class KabutanScraper:
    """株探からPTSランキングをスクレイピングするクラス"""

    BASE_URL = "https://kabutan.jp"
    PTS_RANKING_URL = f"{BASE_URL}/warning/pts_night_price_increase"

    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
    }

    def __init__(self, retry_count: int = 3, retry_delay: float = 2.0):
        """
        Args:
            retry_count: リトライ回数
            retry_delay: リトライ時の待機時間（秒）
        """
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)

    def fetch_pts_ranking(self) -> List[Dict[str, any]]:
        """
        PTSランキング情報を取得

        Returns:
            List[Dict]: 銘柄情報のリスト
                - code: 銘柄コード
                - name: 銘柄名
                - pts_price: PTS価格
                - change_rate: 変化率（%）
                - change_amount: 変化額（円）
                - volume: 出来高
                - market: 市場区分
        """
        for attempt in range(self.retry_count):
            try:
                logger.info(f"Fetching PTS ranking (attempt {attempt + 1}/{self.retry_count})")
                response = self.session.get(self.PTS_RANKING_URL, timeout=30)
                response.raise_for_status()
                response.encoding = response.apparent_encoding

                soup = BeautifulSoup(response.text, 'lxml')
                rankings = self._parse_ranking_table(soup)

                logger.info(f"Successfully fetched {len(rankings)} stocks from PTS ranking")
                return rankings

            except requests.RequestException as e:
                logger.error(f"Error fetching PTS ranking: {e}")
                if attempt < self.retry_count - 1:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                else:
                    logger.error("Max retry count reached. Giving up.")
                    raise

        return []

    def _parse_ranking_table(self, soup: BeautifulSoup) -> List[Dict[str, any]]:
        """
        HTMLからランキングテーブルをパースする

        Args:
            soup: BeautifulSoupオブジェクト

        Returns:
            List[Dict]: パースされた銘柄情報
        """
        rankings = []

        # 株探のPTSランキングテーブルを探す
        # 注意: 実際のHTML構造に合わせて調整が必要
        table = soup.find('table', class_='stock_table')

        if not table:
            logger.warning("PTS ranking table not found. HTML structure may have changed.")
            return rankings

        rows = table.find_all('tr')[1:]  # ヘッダー行をスキップ

        for row in rows:
            try:
                cols = row.find_all('td')
                if len(cols) < 7:
                    continue

                # 正しいテーブル構造:
                # cols[0]: 銘柄コード
                # cols[1]: 市場
                # cols[4]: 前日価格
                # cols[5]: PTS価格
                # cols[6]: 変化額
                # cols[7]: 変化率%
                # cols[8]: 出来高

                code = cols[0].text.strip()
                if not code or not code.isdigit():
                    continue

                market = cols[1].text.strip()
                name = ""  # このテーブルには会社名がない

                # 前日価格
                prev_price_text = cols[4].text.strip().replace(',', '')
                prev_price = self._parse_number(prev_price_text)

                # PTS価格
                pts_price_text = cols[5].text.strip().replace(',', '')
                pts_price = self._parse_number(pts_price_text)

                # 変化額
                change_amount_text = cols[6].text.strip().replace(',', '').replace('+', '')
                change_amount = self._parse_number(change_amount_text)

                # 変化率（%で提供されている）
                change_rate_text = cols[7].text.strip().replace('%', '').replace('+', '')
                change_rate = self._parse_number(change_rate_text)

                # 出来高
                volume_text = cols[8].text.strip().replace(',', '') if len(cols) > 8 else '0'
                volume = self._parse_number(volume_text, is_int=True)

                # 変化率は既に取得済み（上のコードで）

                stock_data = {
                    'code': code,
                    'name': name,
                    'pts_price': pts_price or 0,
                    'change_rate': change_rate,
                    'change_amount': change_amount or 0,
                    'volume': volume,
                    'market': market,
                }

                rankings.append(stock_data)

            except Exception as e:
                logger.warning(f"Error parsing row: {e}")
                continue

        return rankings

    def _parse_number(self, text: str, is_int: bool = False) -> Optional[float]:
        """
        文字列を数値に変換

        Args:
            text: 変換する文字列
            is_int: 整数として扱うかどうか

        Returns:
            float or int or None: 変換された数値
        """
        try:
            text = text.strip()
            if not text or text == '--':
                return None

            number = float(text)
            return int(number) if is_int else number
        except ValueError:
            return None

    def get_stock_detail_url(self, code: str) -> str:
        """
        銘柄詳細ページのURLを取得

        Args:
            code: 銘柄コード

        Returns:
            str: 銘柄詳細ページURL
        """
        return f"{self.BASE_URL}/stock/?code={code}"

    def fetch_stock_name(self, code: str) -> str:
        """
        銘柄コードから会社名を取得

        Args:
            code: 銘柄コード (4桁)

        Returns:
            str: 会社名
        """
        try:
            url = f"{self.BASE_URL}/stock/?code={code}"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'lxml')

            # h3タグから会社名を取得
            h3 = soup.find('h3')
            if h3:
                name_text = h3.get_text(strip=True)
                # "6072 地盤ネットホールディングス" から会社名を抽出
                parts = name_text.split(maxsplit=1)
                if len(parts) > 1:
                    return parts[1]

            return ""

        except Exception as e:
            logger.warning(f"Error fetching stock name for {code}: {e}")
            return ""

    def close(self):
        """セッションをクローズ"""
        self.session.close()


if __name__ == "__main__":
    # テスト実行
    scraper = KabutanScraper()
    try:
        rankings = scraper.fetch_pts_ranking()
        print(f"取得した銘柄数: {len(rankings)}")
        for i, stock in enumerate(rankings[:5], 1):
            print(f"{i}. [{stock['code']}] {stock['name']}")
            print(f"   PTS価格: {stock['pts_price']}円 ({stock['change_rate']:+.2f}%)")
            print(f"   出来高: {stock['volume']:,}株")
    finally:
        scraper.close()
