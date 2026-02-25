"""
話題株ピックアップ情報を取得するモジュール
- 株探の「話題株ピックアップ」記事をスクレイピング
- 株価・チャートデータを付加
- 将来的にJ-Quants API対応可能な設計
"""
import requests
from bs4 import BeautifulSoup
import re
import time
import json
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TrendingStockFetcher:
    """話題株情報を収集するクラス"""

    KABUTAN_BASE_URL = "https://kabutan.jp"
    NEWS_INDEX_URL = f"{KABUTAN_BASE_URL}/news/marketnews/"
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
    }

    def __init__(self, request_delay: float = 1.5):
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.request_delay = request_delay

    def fetch_trending_stocks(self, date: Optional[str] = None) -> List[Dict]:
        """
        話題株ピックアップ情報を取得

        Args:
            date: 対象日付 (YYYYMMDD形式、Noneの場合は当日)

        Returns:
            List[Dict]: 話題株情報のリスト
        """
        if date is None:
            date = datetime.now().strftime('%Y%m%d')

        # 1. 話題株記事のURLを取得
        article_urls = self._find_trending_articles(date)

        if not article_urls:
            logger.warning(f"話題株記事が見つかりません: {date}")
            # 前日を試す
            prev_date = (datetime.strptime(date, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
            article_urls = self._find_trending_articles(prev_date)
            if article_urls:
                date = prev_date

        if not article_urls:
            logger.error("話題株記事が見つかりません")
            return []

        logger.info(f"話題株記事を {len(article_urls)} 件発見")

        # 2. 各記事から銘柄情報を抽出
        all_stocks = []
        for url in article_urls:
            time.sleep(self.request_delay)
            stocks = self._parse_trending_article(url)
            all_stocks.extend(stocks)

        # 3. 各銘柄に株価・チャートデータを追加
        for stock in all_stocks:
            time.sleep(self.request_delay)
            self._enrich_stock_data(stock)

        logger.info(f"合計 {len(all_stocks)} 銘柄の話題株情報を取得")
        return all_stocks

    def _find_trending_articles(self, date: str) -> List[str]:
        """日付指定で話題株ピックアップ記事のURLリストを取得"""
        urls = []
        try:
            # ニュースインデックス（注目カテゴリ）から検索
            response = self.session.get(
                self.NEWS_INDEX_URL,
                params={'category': '9', 'date': date},
                timeout=15
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')

            # 話題株ピックアップの記事リンクを探す
            for link in soup.find_all('a', href=True):
                title = link.get_text(strip=True)
                if '話題株ピックアップ' in title:
                    href = link['href']
                    if href.startswith('/'):
                        href = self.KABUTAN_BASE_URL + href
                    elif not href.startswith('http'):
                        href = self.KABUTAN_BASE_URL + '/' + href
                    if href not in urls:
                        urls.append(href)
                        logger.info(f"記事発見: {title} -> {href}")

            # 日付ベースの直接URL試行（バックアップ）
            if not urls:
                # 夕刊パターン
                for suffix in ['t', 't_top_1', 't_top_2', 't_top_3']:
                    test_url = f"{self.NEWS_INDEX_URL}?b=k{date}{suffix}"
                    try:
                        resp = self.session.get(test_url, timeout=10)
                        if resp.status_code == 200 and '話題株' in resp.text:
                            urls.append(test_url)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"記事検索エラー: {e}")

        return urls

    def _parse_trending_article(self, url: str) -> List[Dict]:
        """話題株記事をパースして銘柄情報を抽出"""
        stocks = []
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')

            # 記事本文を取得（class='body'のdiv）
            article_body = soup.find('div', class_='body')
            if not article_body:
                article_body = soup.find('div', class_='news_article_body')
            if not article_body:
                article_body = soup.find('article')
            if not article_body:
                logger.warning(f"記事本文が見つかりません: {url}")
                return []

            # テキストを空白区切りで取得（改行でタグ内容が分断されるのを防ぐ）
            body_text = article_body.get_text(' ', strip=True)

            # ■で区切って各銘柄セクションを抽出
            sections = body_text.split('■')

            for section in sections[1:]:  # 最初の空セクションをスキップ
                stock = self._parse_stock_section(section)
                if stock:
                    stock['source_url'] = url
                    stocks.append(stock)
                    logger.info(f"  銘柄抽出: [{stock['code']}] {stock['name']}")

        except Exception as e:
            logger.error(f"記事パースエラー ({url}): {e}")

        return stocks

    def _parse_stock_section(self, section_text: str) -> Optional[Dict]:
        """個別銘柄セクションをパース"""
        try:
            if not section_text or len(section_text) < 10:
                return None

            # 銘柄コード抽出（半角・全角両対応、前後にスペースが入る場合も考慮）
            # パターン: 銘柄名 <コード> or 銘柄名 ＜コード＞ (スペースが挟まる場合あり)
            code_match = re.search(r'[<＜]\s*(\d{4})\s*[>＞]', section_text)
            if not code_match:
                return None

            code = code_match.group(1)

            # 銘柄名: ■の直後からコードの<まで
            name_part = section_text[:code_match.start()].strip()
            # 余分な空白を縮小
            name = re.sub(r'\s+', '', name_part).strip()
            if not name:
                return None

            # コード以降のテキスト
            after_code = section_text[code_match.end():]

            # 株価情報抽出
            price_info = {}
            # パターン: 15,980円 +1,480 円 (+10.2％)
            price_match = re.search(
                r'([\d,]+)\s*円\s*([+\-＋－]\s*[\d,]+)\s*円?\s*\(\s*([+\-＋－]?\s*\d+\.?\d*)\s*[%％]\s*\)',
                after_code
            )
            if price_match:
                price_info['price'] = int(price_match.group(1).replace(',', '').replace(' ', ''))
                change_str = price_match.group(2).replace('＋', '+').replace('－', '-').replace(',', '').replace(' ', '')
                price_info['change_amount'] = int(change_str)
                rate_str = price_match.group(3).replace('＋', '+').replace('－', '-').replace(' ', '')
                price_info['change_rate'] = float(rate_str)

                # 市場情報
                market_match = re.search(r'(東証プライム|東証スタンダード|東証グロース|名証)', after_code[:200])
                if market_match:
                    price_info['market'] = market_match.group(1)

                # 上昇率ランキング
                rank_match = re.search(r'上昇率(\d+)位', after_code[:200])
                if rank_match:
                    price_info['rank'] = int(rank_match.group(1))

            # あらすじ: 株価情報行の後のテキスト
            synopsis = ''
            if price_match:
                # 株価行の後～次の■or記事末尾まで
                price_line_end = after_code.find('本日終値')
                if price_line_end == -1:
                    price_line_end = price_match.end()
                else:
                    price_line_end += len('本日終値')

                # 市場やランキング情報を飛ばしてあらすじ部分を取得
                remaining = after_code[price_line_end:]
                # 市場情報・ランキング部分をスキップ
                skip_match = re.search(r'(東証プライム|東証スタンダード|東証グロース|名証).*(上昇率\d+位)?', remaining[:100])
                if skip_match:
                    synopsis_start = skip_match.end()
                    synopsis = remaining[synopsis_start:].strip()
                else:
                    synopsis = remaining.strip()
            else:
                # 株価情報が見つからない場合はコード以降全体をあらすじとする
                synopsis = after_code.strip()

            # あらすじのクリーンアップ
            # 記事の銘柄コード繰り返しなどを除去
            synopsis = re.sub(r'[<＜]\s*\d{4}\s*[>＞]', '', synopsis)
            # 先頭の不要な空白・記号を除去
            synopsis = re.sub(r'^[\s　、。]+', '', synopsis)
            # 連続空白を縮小
            synopsis = re.sub(r'\s+', ' ', synopsis).strip()

            if not name or len(name) < 1:
                return None

            return {
                'code': code,
                'name': name,
                'price': price_info.get('price'),
                'change_amount': price_info.get('change_amount'),
                'change_rate': price_info.get('change_rate'),
                'market': price_info.get('market', ''),
                'rank_in_article': price_info.get('rank'),
                'synopsis': synopsis[:500] if synopsis else '',
            }

        except Exception as e:
            logger.error(f"銘柄セクションパースエラー: {e}")
            return None

    def _enrich_stock_data(self, stock: Dict):
        """銘柄に株価詳細・チャートデータを追加"""
        code = stock['code']
        try:
            # 株探の株価ページから追加データ取得（株価テーブルとPER/PBR込み）
            url = f"{self.KABUTAN_BASE_URL}/stock/kabuka?code={code}&ashi=day"
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'lxml')

            # PER / PBR / 時価総額 を探す
            # テーブル構造: ヘッダー行 PER|PBR|利回り|信用倍率, データ行 30.1倍|5.65倍|...
            for table in soup.find_all('table'):
                headers = table.find_all('th')
                header_texts = [h.get_text(strip=True) for h in headers]
                if 'PER' in header_texts and 'PBR' in header_texts:
                    data_rows = table.find_all('tr')
                    for row in data_rows:
                        cells = row.find_all('td')
                        if len(cells) >= 2:
                            cell_texts = [c.get_text(strip=True) for c in cells]
                            # PER
                            per_idx = header_texts.index('PER') if 'PER' in header_texts else -1
                            if per_idx >= 0 and per_idx < len(cell_texts):
                                per_match = re.search(r'([\d.]+)', cell_texts[per_idx].replace(',', ''))
                                if per_match:
                                    stock['per'] = float(per_match.group(1))
                            # PBR
                            pbr_idx = header_texts.index('PBR') if 'PBR' in header_texts else -1
                            if pbr_idx >= 0 and pbr_idx < len(cell_texts):
                                pbr_match = re.search(r'([\d.]+)', cell_texts[pbr_idx].replace(',', ''))
                                if pbr_match:
                                    stock['pbr'] = float(pbr_match.group(1))
                            break

                # 時価総額
                if '時価総額' in header_texts:
                    data_rows = table.find_all('tr')
                    for row in data_rows:
                        cells = row.find_all('td')
                        if cells:
                            text = cells[0].get_text(strip=True)
                            if '億' in text or '兆' in text:
                                stock['market_cap'] = text

            # 本日の株価テーブルから高値・安値・始値・出来高を取得
            # テーブル構造: th=本日+カラムヘッダー, data行: th=日付, td=始値|高値|安値|終値|前日比|前日比%|売買高
            for table in soup.find_all('table'):
                header_ths = table.find('tr')
                if not header_ths:
                    continue
                header_texts = [h.get_text(strip=True) for h in header_ths.find_all('th')]
                if '本日' in header_texts and '始値' in header_texts:
                    # 今日のテーブル
                    rows = table.find_all('tr')
                    for row in rows[1:]:  # ヘッダーをスキップ
                        cells = row.find_all('td')
                        if len(cells) >= 4:
                            # td: 始値|高値|安値|終値|前日比|前日比%|売買高
                            stock['price_open'] = self._parse_price_int(cells[0].get_text(strip=True))
                            stock['price_high'] = self._parse_price_int(cells[1].get_text(strip=True))
                            stock['price_low'] = self._parse_price_int(cells[2].get_text(strip=True))
                            if len(cells) >= 7:
                                vol = cells[6].get_text(strip=True)
                                if vol:
                                    stock['volume'] = vol + '株'
                            break
                    break

            # 株価チャートデータ（過去の日足データ - 30行のテーブル）
            stock['chart_data'] = self._extract_chart_from_soup(soup)

        except Exception as e:
            logger.error(f"銘柄詳細取得エラー ({code}): {e}")

    def _parse_price_int(self, text: str) -> Optional[int]:
        """金額テキストを整数に変換"""
        try:
            cleaned = text.replace(',', '').replace('円', '').strip()
            if cleaned and cleaned != '-' and cleaned != '---':
                return int(float(cleaned))
        except (ValueError, AttributeError):
            pass
        return None

    def _extract_chart_from_soup(self, soup: BeautifulSoup) -> List[Dict]:
        """株価ページのHTMLから日足チャートデータを抽出"""
        chart_data = []
        try:
            # 30行の日足テーブルを探す
            # テーブル構造: header行 th=日付|始値|..., data行 th=26/02/24 td=始値|高値|安値|終値|...
            best_table = None
            max_rows = 0
            for table in soup.find_all('table'):
                first_row = table.find('tr')
                if not first_row:
                    continue
                header_texts = [h.get_text(strip=True) for h in first_row.find_all('th')]
                if '日付' in header_texts and '始値' in header_texts:
                    row_count = len(table.find_all('tr'))
                    if row_count > max_rows:
                        max_rows = row_count
                        best_table = table

            if best_table and max_rows > 2:
                rows = best_table.find_all('tr')[1:]  # ヘッダーをスキップ
                for row in rows:
                    # th = 日付, td = 値
                    date_th = row.find('th')
                    cells = row.find_all('td')
                    if date_th and len(cells) >= 4:
                        try:
                            date_text = date_th.get_text(strip=True)
                            if not re.match(r'\d{2}/\d{2}/\d{2}', date_text):
                                continue
                            # td: 始値|高値|安値|終値|前日比|前日比%|売買高
                            open_price = self._parse_price_text(cells[0].get_text(strip=True))
                            high_price = self._parse_price_text(cells[1].get_text(strip=True))
                            low_price = self._parse_price_text(cells[2].get_text(strip=True))
                            close_price = self._parse_price_text(cells[3].get_text(strip=True))

                            if close_price is not None:
                                chart_data.append({
                                    'date': date_text,
                                    'open': open_price,
                                    'high': high_price,
                                    'low': low_price,
                                    'close': close_price,
                                })
                        except (ValueError, IndexError):
                            continue

            # 新しい順→古い順に並べ替え（チャート表示用）
            chart_data.reverse()

        except Exception as e:
            logger.error(f"チャートデータ抽出エラー: {e}")

        return chart_data

    def _parse_price_text(self, text: str) -> Optional[float]:
        """金額テキストを数値に変換"""
        try:
            cleaned = text.replace(',', '').replace('円', '').strip()
            if cleaned and cleaned != '-':
                return float(cleaned)
        except (ValueError, AttributeError):
            pass
        return None

    def close(self):
        """セッションをクローズ"""
        self.session.close()


if __name__ == "__main__":
    fetcher = TrendingStockFetcher()
    try:
        stocks = fetcher.fetch_trending_stocks()
        print(f"\n取得した話題株: {len(stocks)} 銘柄\n")
        for i, stock in enumerate(stocks, 1):
            print(f"{i}. [{stock['code']}] {stock['name']}")
            if stock.get('price'):
                print(f"   株価: {stock['price']:,}円 ({stock.get('change_rate', 0):+.1f}%)")
            if stock.get('market_cap'):
                print(f"   時価総額: {stock['market_cap']}")
            if stock.get('synopsis'):
                print(f"   あらすじ: {stock['synopsis'][:100]}...")
            if stock.get('chart_data'):
                print(f"   チャートデータ: {len(stock['chart_data'])}日分")
            print()
    finally:
        fetcher.close()
