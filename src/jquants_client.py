"""
J-Quants API v2 クライアント
銘柄マスター、株価、決算データの取得
"""
import os
import math
import time
import logging
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class JQuantsClient:
    BASE_URL = "https://api.jquants.com/v2"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv('JQUANTS_API_KEY', '')
        self.session = requests.Session()
        self.session.headers.update({
            'x-api-key': self.api_key,
            'Accept': 'application/json',
        })
        self._master_cache = None
        self._master_cache_time = None
        self._price_cache: Dict[str, list] = {}  # date -> price list
        self._price_cache_time: Dict[str, float] = {}

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        """API GETリクエスト（429レート制限時は最大3回リトライ）"""
        url = f"{self.BASE_URL}{path}"
        for attempt in range(3):
            try:
                resp = self.session.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = (attempt + 1) * 5   # 5s, 10s, 15s
                    logger.warning(f"Rate limit 429, {wait}秒待機して再試行...")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as e:
                logger.error(f"J-Quants API error: {e} - {resp.text[:200]}")
                return {"data": [], "error": str(e)}
            except Exception as e:
                logger.error(f"J-Quants request failed: {e}")
                return {"data": [], "error": str(e)}
        return {"data": [], "error": "Rate limit exceeded after retries"}

    # ========== マスターデータ ==========

    def get_master(self, code: Optional[str] = None) -> List[Dict]:
        """銘柄マスターデータ取得（キャッシュ: 1時間）"""
        if code:
            result = self._get("/equities/master", {"code": code})
            return result.get("data", [])

        now = time.time()
        if self._master_cache and self._master_cache_time and (now - self._master_cache_time < 3600):
            return self._master_cache

        result = self._get("/equities/master")
        data = result.get("data", [])
        if data:
            self._master_cache = data
            self._master_cache_time = now
        return data

    def get_sectors(self) -> List[Dict]:
        """業種一覧を取得"""
        master = self.get_master()
        sectors = {}
        for item in master:
            code = item.get("S33", "")
            name = item.get("S33Nm", "")
            if code and name and code not in sectors:
                sectors[code] = name
        return [{"code": k, "name": v} for k, v in sorted(sectors.items())]

    def get_markets(self) -> List[str]:
        """市場区分一覧"""
        master = self.get_master()
        markets = set()
        for item in master:
            mkt = item.get("MktNm", "")
            if mkt:
                markets.add(mkt)
        return sorted(markets)

    # ========== 株価データ ==========

    def get_prices(self, code: str, from_date: Optional[str] = None,
                   to_date: Optional[str] = None) -> List[Dict]:
        """日足株価データ取得"""
        params = {"code": code}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        result = self._get("/equities/bars/daily", params)
        return result.get("data", [])

    def get_latest_prices(self, code: Optional[str] = None,
                          date: Optional[str] = None) -> List[Dict]:
        """最新株価を取得（全銘柄 or 単一銘柄）"""
        params = {}
        if code:
            params["code"] = code
        if date:
            params["date"] = date
        result = self._get("/equities/bars/daily", params)
        return result.get("data", [])

    def _fetch_prices_for_date(self, date: str) -> List[Dict]:
        """指定日の全銘柄株価（キャッシュあり・10分）"""
        now = time.time()
        if date in self._price_cache and (now - self._price_cache_time.get(date, 0) < 600):
            return self._price_cache[date]
        result = self._get("/equities/bars/daily", {"date": date})
        data = result.get("data", [])
        if data and len(data) > 100:
            self._price_cache[date] = data
            self._price_cache_time[date] = now
        return data

    def _find_latest_trading_date(self) -> tuple[str, List[Dict]]:
        """最近の取引日と株価データを返す"""
        today = datetime.now()
        for days_back in range(0, 7):
            check_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
            data = self._fetch_prices_for_date(check_date)
            if data and len(data) > 100:
                return check_date, data
            time.sleep(0.2)
        return "", []

    def _find_prev_trading_date(self, base_date: str) -> List[Dict]:
        """base_dateの前の取引日の株価データを返す"""
        dt = datetime.strptime(base_date, "%Y-%m-%d")
        for days_back in range(1, 7):
            prev_date = (dt - timedelta(days=days_back)).strftime("%Y-%m-%d")
            data = self._fetch_prices_for_date(prev_date)
            if data and len(data) > 100:
                return data
            time.sleep(0.2)
        return []

    # ========== 決算データ ==========

    def get_financial_summary(self, code: str) -> List[Dict]:
        """決算サマリーデータ取得"""
        result = self._get("/fins/summary", {"code": code})
        return result.get("data", [])

    def get_financial_statements(self, code: str) -> List[Dict]:
        """詳細決算データ取得"""
        result = self._get("/fins/statements", {"code": code})
        return result.get("data", [])

    def get_earnings_announcements(self, date: str) -> List[Dict]:
        """指定日に決算発表があった銘柄リストを取得"""
        result = self._get("/fins/announcement", {"date": date})
        return result.get("data", [])

    # ========== 決算インパクト分析 ==========

    @staticmethod
    def _quarter_order(q_type: str) -> int:
        return {'1Q': 1, 'HY': 2, '3Q': 3, 'FY': 4}.get(q_type, 0)

    @staticmethod
    def _prev_quarter_type(q_type: str) -> Optional[str]:
        return {'HY': '1Q', '3Q': 'HY', 'FY': '3Q'}.get(q_type)

    @staticmethod
    def _safe_float(val) -> Optional[float]:
        if val is None or val == '':
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _calc_single_quarter(self, statements: List[Dict], target: Dict) -> Optional[Dict]:
        """
        累計値から単四半期の売上高・営業利益を算出する。
        target: 対象となる statements レコード。
        1Qなら累計=単Q。2Q以降は前Qの累計を引く。
        """
        q_type = target.get('TypeOfCurrentPeriod', '')
        fy_start = target.get('CurrentFiscalYearStartDate', '')

        cum_sales = self._safe_float(target.get('NetSales'))
        cum_op = self._safe_float(target.get('OperatingProfit'))

        if cum_sales is None and cum_op is None:
            return None

        if q_type == '1Q':
            return {'sales': cum_sales, 'op': cum_op}

        prev_qt = self._prev_quarter_type(q_type)
        if not prev_qt:
            return {'sales': cum_sales, 'op': cum_op}

        prev = None
        for s in statements:
            if (s.get('TypeOfCurrentPeriod') == prev_qt
                    and s.get('CurrentFiscalYearStartDate') == fy_start):
                prev = s
                break

        if not prev:
            return {'sales': cum_sales, 'op': cum_op}

        prev_sales = self._safe_float(prev.get('NetSales'))
        prev_op = self._safe_float(prev.get('OperatingProfit'))

        single_sales = (cum_sales - prev_sales) if cum_sales is not None and prev_sales is not None else cum_sales
        single_op = (cum_op - prev_op) if cum_op is not None and prev_op is not None else cum_op

        return {'sales': single_sales, 'op': single_op}

    def _find_yoy_target(self, statements: List[Dict], current: Dict) -> Optional[Dict]:
        """現在の決算に対応する前年同期のレコードを探す。"""
        q_type = current.get('TypeOfCurrentPeriod', '')
        fy_start = current.get('CurrentFiscalYearStartDate', '')
        if not fy_start or len(fy_start) < 4:
            return None

        try:
            fy_start_dt = datetime.strptime(fy_start, '%Y-%m-%d')
            prev_fy_start = (fy_start_dt - timedelta(days=370)).strftime('%Y-')
        except ValueError:
            return None

        prev_year_str = str(int(fy_start[:4]) - 1)

        for s in statements:
            s_fy = s.get('CurrentFiscalYearStartDate', '')
            if (s.get('TypeOfCurrentPeriod') == q_type
                    and s_fy.startswith(prev_year_str)):
                return s
        return None

    def get_earnings_impact(self, date: str) -> Dict:
        """
        指定日の決算発表銘柄について単四半期YoY成長率を算出・ランク付けする。

        Returns: {
            'date': str,
            'stocks': [{code, name, rank, sales_yoy, op_yoy, progress, market_cap, ...}, ...],
            'total': int,
            'counts': {S: n, A: n, B: n, C: n}
        }
        """
        announcements = self.get_earnings_announcements(date)
        if not announcements:
            return {'date': date, 'stocks': [], 'total': 0,
                    'counts': {'S': 0, 'A': 0, 'B': 0, 'C': 0}}

        master = self.get_master()
        master_dict = {}
        for m in master:
            c = m.get('Code', '')
            master_dict[c] = m
            if len(c) == 5 and c.endswith('0'):
                master_dict[c[:-1]] = m

        latest_prices = self.get_latest_prices(date=date)
        price_map = {}
        for p in latest_prices:
            c = p.get('Code', '')
            price_map[c] = p
            if len(c) == 5 and c.endswith('0'):
                price_map[c[:-1]] = p

        results = []
        for ann in announcements:
            code = ann.get('Code', '')
            code4 = code[:-1] if len(code) == 5 and code.endswith('0') else code

            try:
                stmts = self.get_financial_statements(code)
                time.sleep(0.3)
            except Exception as e:
                logger.warning(f"[{code4}] statements取得失敗: {e}")
                continue

            if not stmts:
                continue

            stmts_sorted = sorted(
                stmts,
                key=lambda s: (
                    s.get('CurrentFiscalYearStartDate', ''),
                    self._quarter_order(s.get('TypeOfCurrentPeriod', '')),
                ),
            )

            current = stmts_sorted[-1]
            q_type = current.get('TypeOfCurrentPeriod', '')

            current_sq = self._calc_single_quarter(stmts_sorted, current)
            if not current_sq:
                continue

            yoy_target = self._find_yoy_target(stmts_sorted, current)
            sales_yoy = None
            op_yoy = None

            if yoy_target:
                prev_sq = self._calc_single_quarter(stmts_sorted, yoy_target)
                if prev_sq:
                    if prev_sq['sales'] and prev_sq['sales'] > 0 and current_sq['sales'] is not None:
                        sales_yoy = round((current_sq['sales'] / prev_sq['sales'] - 1) * 100, 1)
                    if prev_sq['op'] and prev_sq['op'] > 0 and current_sq['op'] is not None:
                        op_yoy = round((current_sq['op'] / prev_sq['op'] - 1) * 100, 1)

            # Progress rate
            progress = None
            cum_ord = self._safe_float(current.get('OrdinaryProfit'))
            forecast_ord = self._safe_float(current.get('ForecastOrdinaryProfit'))
            if cum_ord is not None and forecast_ord and forecast_ord > 0:
                progress = round(cum_ord / forecast_ord * 100, 1)

            # Rank
            if (sales_yoy is not None and sales_yoy >= 20
                    and op_yoy is not None and op_yoy >= 30):
                rank = 'S'
            elif op_yoy is not None and op_yoy >= 20:
                rank = 'A'
            elif op_yoy is not None and op_yoy >= 10:
                rank = 'B'
            else:
                rank = 'C'

            # Market cap
            m_info = master_dict.get(code, master_dict.get(code4, {}))
            name = m_info.get('CoName', ann.get('CompanyName', ''))
            shares = self._safe_float(m_info.get('NumberOfIssuedShares'))
            p_info = price_map.get(code, price_map.get(code4, {}))
            close = self._safe_float(p_info.get('AdjC') or p_info.get('C'))
            market_cap = None
            if shares and close:
                market_cap = round(shares * close)

            results.append({
                'code': code4,
                'name': name,
                'sector': m_info.get('S33Nm', ''),
                'market': m_info.get('MktNm', ''),
                'q_type': q_type,
                'rank': rank,
                'sales_yoy': sales_yoy,
                'op_yoy': op_yoy,
                'progress': progress,
                'market_cap': market_cap,
                'close': close,
            })

        rank_order = {'S': 0, 'A': 1, 'B': 2, 'C': 3}
        results.sort(key=lambda r: (
            rank_order.get(r['rank'], 9),
            -(r['op_yoy'] or -9999),
        ))

        counts = {'S': 0, 'A': 0, 'B': 0, 'C': 0}
        for r in results:
            counts[r['rank']] = counts.get(r['rank'], 0) + 1

        return {
            'date': date,
            'stocks': results,
            'total': len(results),
            'counts': counts,
        }

    # ========== スクリーニング ==========

    def _normalize_code(self, code: str) -> str:
        """J-Quants 5桁コードを4桁に変換（末尾0を1文字だけ除去）"""
        if len(code) == 5 and code.endswith("0"):
            return code[:-1]
        return code

    def _build_result(self, code: str, price: Dict, prev_price: Optional[Dict],
                      master_dict: Dict, used_date: str) -> Optional[Dict]:
        """1銘柄の結果Dictを構築"""
        close = price.get("AdjC") or price.get("C")
        volume = price.get("AdjVo") or price.get("Vo") or 0
        turnover = price.get("Va") or 0

        if not close or close == 0:
            return None

        change_rate = 0.0
        change_amount = 0.0
        if prev_price:
            prev_close = prev_price.get("AdjC") or prev_price.get("C") or 0
            if prev_close > 0:
                change_amount = close - prev_close
                change_rate = (change_amount / prev_close) * 100

        m = master_dict.get(code, {})
        return {
            "code": self._normalize_code(code),
            "name": m.get("CoName", ""),
            "market": m.get("MktNm", ""),
            "sector": m.get("S33Nm", ""),
            "sector_code": m.get("S33", ""),
            "scale": m.get("ScaleCat", ""),
            "date": price.get("Date", used_date),
            "open":  price.get("AdjO") or price.get("O"),
            "high":  price.get("AdjH") or price.get("H"),
            "low":   price.get("AdjL") or price.get("L"),
            "close": close,
            "volume": volume,
            "turnover": turnover,
            "change_amount": round(change_amount, 1),
            "change_rate": round(change_rate, 2),
        }

    def screen_stocks(self, filters: Dict) -> List[Dict]:
        """
        銘柄スクリーニング

        filters:
            market, sector, price_min/max, volume_min,
            turnover_min, change_rate_min/max,
            sort_by, sort_desc, limit
        """
        master = self.get_master()
        if not master:
            logger.warning("マスターデータが取得できませんでした")
            return []

        master_dict = {item["Code"]: item for item in master}

        market_filter = filters.get("market", "")
        sector_filter = filters.get("sector", "")

        target_codes = []
        for item in master:
            mkt = item.get("MktNm", "")
            if market_filter and mkt != market_filter:
                continue
            if sector_filter and item.get("S33", "") != sector_filter:
                continue
            if mkt == "TOKYO PRO MARKET":
                continue
            target_codes.append(item["Code"])

        logger.info(f"スクリーニング対象: {len(target_codes)}銘柄")

        used_date, prices_data = self._find_latest_trading_date()
        if not prices_data:
            logger.warning("株価データが取得できませんでした")
            return []

        price_dict = {p["Code"]: p for p in prices_data}
        prev_data = self._find_prev_trading_date(used_date)
        prev_dict = {p["Code"]: p for p in prev_data}

        price_min     = filters.get("price_min")
        price_max     = filters.get("price_max")
        volume_min    = filters.get("volume_min")
        turnover_min  = filters.get("turnover_min")
        cr_min        = filters.get("change_rate_min")
        cr_max        = filters.get("change_rate_max")

        results = []
        for code in target_codes:
            if code not in price_dict:
                continue

            row = self._build_result(code, price_dict[code], prev_dict.get(code), master_dict, used_date)
            if row is None:
                continue

            if price_min   is not None and row["close"]       < price_min:   continue
            if price_max   is not None and row["close"]       > price_max:   continue
            if volume_min  is not None and row["volume"]      < volume_min:  continue
            if turnover_min is not None and row["turnover"]   < turnover_min: continue
            if cr_min      is not None and row["change_rate"] < cr_min:      continue
            if cr_max      is not None and row["change_rate"] > cr_max:      continue

            results.append(row)

        sort_by   = filters.get("sort_by", "turnover")
        sort_desc = filters.get("sort_desc", True)

        if sort_by in ["close", "volume", "turnover", "change_rate", "change_amount"]:
            results.sort(key=lambda x: x.get(sort_by) or 0, reverse=sort_desc)
        elif sort_by == "name":
            results.sort(key=lambda x: x.get("name", ""), reverse=sort_desc)

        limit = filters.get("limit", 100)
        return results[:limit]

    # ========== 今買うべき銘柄 ==========

    def get_top_picks(self, n: int = 10) -> List[Dict]:
        """
        買いシグナルの強い銘柄トップN

        スコアリング:
          - 上昇率（前日比）: 0-15% レンジで正規化 × 0.45
          - 流動性（売買代金）: log スケール正規化 × 0.55
          - 上昇率 > 15% はオーバーエクステンデッド扱いでペナルティ
        """
        master = self.get_master()
        if not master:
            return []

        master_dict = {item["Code"]: item for item in master}

        # TOKYO PRO MARKET 除外
        target_codes = [
            item["Code"] for item in master
            if item.get("MktNm") != "TOKYO PRO MARKET"
        ]

        used_date, prices_data = self._find_latest_trading_date()
        if not prices_data:
            return []

        price_dict = {p["Code"]: p for p in prices_data}
        prev_data  = self._find_prev_trading_date(used_date)
        prev_dict  = {p["Code"]: p for p in prev_data}

        candidates = []
        for code in target_codes:
            if code not in price_dict:
                continue
            row = self._build_result(code, price_dict[code], prev_dict.get(code), master_dict, used_date)
            if row is None:
                continue
            # 最低流動性フィルター（売買代金 1億円以上、前日比プラス）
            if row["turnover"] < 100_000_000:
                continue
            if row["change_rate"] <= 0:
                continue
            candidates.append(row)

        if not candidates:
            return []

        # スコアリング
        max_va = max(s["turnover"] for s in candidates) or 1
        min_va = min(s["turnover"] for s in candidates) or 1

        for s in candidates:
            cr = s["change_rate"]
            # 上昇率スコア: 0〜15%を0〜1、15%超はペナルティ
            if cr <= 15:
                cr_score = cr / 15
            else:
                cr_score = 1.0 - (cr - 15) / 30  # 超騰は減点

            # 流動性スコア: log スケール
            va_score = (math.log10(max(s["turnover"], 1)) - math.log10(min_va)) / \
                       (math.log10(max_va) - math.log10(min_va) + 1e-9)

            s["_score"] = cr_score * 0.45 + va_score * 0.55

        candidates.sort(key=lambda x: x["_score"], reverse=True)
        picks = candidates[:n]

        # タグ付け
        for s in picks:
            tags = []
            cr = s["change_rate"]
            va = s["turnover"]
            mkt = s["market"]
            if cr >= 10:
                tags.append("急騰")
            elif cr >= 5:
                tags.append("上昇")
            else:
                tags.append("堅調")
            if va >= 10_000_000_000:
                tags.append("超大型")
            elif va >= 1_000_000_000:
                tags.append("大商い")
            elif va >= 500_000_000:
                tags.append("高流動性")
            if mkt == "グロース":
                tags.append("グロース")
            elif mkt == "プライム":
                tags.append("プライム")
            s["tags"] = tags

        return picks

    # ========== 出来高レジームチェンジ検出 ==========

    @staticmethod
    def _median(arr):
        """中央値を計算。スパイクにロバストな中心傾向の推定。"""
        if not arr:
            return 0
        s = sorted(arr)
        n = len(s)
        if n % 2 == 1:
            return s[n // 2]
        return (s[n // 2 - 1] + s[n // 2]) / 2

    @staticmethod
    def _sma(prices, period):
        """直近 period 個の単純移動平均。データ不足時は None。"""
        if len(prices) < period:
            return None
        return sum(prices[-period:]) / period

    @staticmethod
    def _detect_regime_change(opens, highs, lows, closes, volumes,
                              regime_ratio_min=2.5, min_recent_vol=100_000):
        """
        出来高サージ × パーフェクトオーダーで初動を高速検知する。

        出来高: 過去35日(中央値) vs 直近3日(平均) で急変を即座に捕捉。
        トレンド: 終値 > 5SMA > 25SMA > 75SMA のパーフェクトオーダーで
                  デッド・キャット・バウンスを物理的に排除。

        Args:
            opens/highs/lows/closes/volumes: 古い順の配列（75日以上必要）
            regime_ratio_min: recent_surge / past_base の閾値 (default 2.5)
            min_recent_vol:   recent_surge の最低出来高

        Returns:
            (passed: bool, details: dict)
        """
        n = len(closes)
        result = {
            "passed": False, "past_base": 0, "recent_surge": 0,
            "surge_ratio": 0,
            "sma5": None, "sma25": None, "sma75": None,
            "perfect_order": False,
        }

        if n < 75:
            return False, result

        # ── 出来高サージ検知 ──
        # past_base:    Day 40 ~ Day 5 (35日間) の中央値
        # recent_surge: Day 2 ~ Day 0  (直近3日)  の平均値
        past_vols = volumes[n - 41: n - 5]       # 35 elements
        recent_3d_vols = volumes[n - 3: n]        # 3 elements

        past_base = JQuantsClient._median(past_vols)
        recent_surge = sum(recent_3d_vols) / 3 if len(recent_3d_vols) == 3 else 0

        surge_ratio = recent_surge / past_base if past_base > 0 else 0

        result["past_base"] = round(past_base)
        result["recent_surge"] = round(recent_surge)
        result["surge_ratio"] = round(surge_ratio, 2)

        if surge_ratio < regime_ratio_min:
            return False, result

        if recent_surge < min_recent_vol:
            return False, result

        # ── パーフェクトオーダー（鉄壁トレンドフィルター） ──
        sma5 = JQuantsClient._sma(closes, 5)
        sma25 = JQuantsClient._sma(closes, 25)
        sma75 = JQuantsClient._sma(closes, 75)

        result["sma5"] = round(sma5, 1) if sma5 else None
        result["sma25"] = round(sma25, 1) if sma25 else None
        result["sma75"] = round(sma75, 1) if sma75 else None

        if sma5 is None or sma25 is None or sma75 is None:
            return False, result

        day0_close = closes[-1]

        # 条件A: 25SMA > 75SMA（中期線が長期線の上）
        # 条件B: 5SMA > 25SMA （短期線が中期線の上）
        # 条件C: 終値 > 5SMA  （株価が一番上）
        perfect_order = (sma25 > sma75) and (sma5 > sma25) and (day0_close > sma5)
        result["perfect_order"] = perfect_order
        if not perfect_order:
            return False, result

        result["passed"] = True
        return True, result

    def get_volume_breakout_stocks(self, days: int = 20, top_n: int = 20,
                                   target_date: Optional[str] = None,
                                   vol_ratio_min: float = 2.0,
                                   price_5d_chg_min: float = -999.0,
                                   turnover_min: int = 50_000_000,
                                   market: str = '') -> List[Dict]:
        """
        出来高レジームチェンジ銘柄を検出。

        中央値ベースで「出来高の水準そのものが底上げされた」銘柄を検出する。
        1日だけのスパイク（イナゴタワー）は検出しない。
        下落トレンド中の投げ売りも厳格なトレンドフィルターで排除する。

        判定:
          past_base      = Day40~Day5 (35日間) の出来高中央値
          recent_surge   = Day2~Day0  (直近3日) の出来高平均
          surge_ratio    = recent_surge / past_base >= 2.5x
          + 流動性フィルター (recent_surge >= 100,000株)
          + パーフェクトオーダー: 終値 > 5SMA > 25SMA > 75SMA
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import statistics

        master = self.get_master()
        if not master:
            return []

        master_dict = {item["Code"]: item for item in master}
        valid_codes = {
            item["Code"]
            for item in master
            if item.get("MktNm") != "TOKYO PRO MARKET"
        }

        # ── 1. 過去75営業日+余裕分のカレンダー日を並列フェッチ ──
        if target_date:
            base = datetime.strptime(target_date, "%Y-%m-%d")
        else:
            base = datetime.now()

        # 75営業日 + 休日マージン → 約120カレンダー日
        candidate_dates = [
            (base - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(0, 120)
        ]

        date_data: Dict[str, Dict] = {}

        def fetch_one(date_str: str):
            data = self._fetch_prices_for_date(date_str)
            if data and len(data) > 100:
                return date_str, {p["Code"]: p for p in data}
            return date_str, None

        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(fetch_one, d): d for d in candidate_dates}
            for fut in as_completed(futures):
                d, result = fut.result()
                if result:
                    date_data[d] = result

        trading_days = sorted(date_data.keys(), reverse=True)
        if len(trading_days) < 75:
            logger.warning(f"取引日データ不足: {len(trading_days)}日 (75日必要)")
            return []

        trading_days = trading_days[:85]
        today_date = trading_days[0]
        today_prices = date_data[today_date]

        # ── 2. 銘柄ごとにレジームチェンジ判定 ──
        results = []

        for code in valid_codes:
            if code not in today_prices:
                continue
            if market and master_dict.get(code, {}).get("MktNm", "") != market:
                continue

            opens_arr, highs_arr, lows_arr, closes_arr, volumes_arr = [], [], [], [], []
            for d in reversed(trading_days):
                p = date_data[d].get(code)
                if p is None:
                    continue
                o = p.get("AdjO") or p.get("O") or 0
                h = p.get("AdjH") or p.get("H") or 0
                l = p.get("AdjL") or p.get("L") or 0
                c = p.get("AdjC") or p.get("C")
                v = p.get("AdjVo") or p.get("Vo") or 0
                if c and c > 0:
                    opens_arr.append(o)
                    highs_arr.append(h)
                    lows_arr.append(l)
                    closes_arr.append(c)
                    volumes_arr.append(v)

            if len(closes_arr) < 75:
                continue

            passed, details = self._detect_regime_change(
                opens_arr, highs_arr, lows_arr, closes_arr, volumes_arr,
                regime_ratio_min=vol_ratio_min,
                min_recent_vol=100_000,
            )

            if not passed:
                continue

            today_close = closes_arr[-1]
            today_vol = volumes_arr[-1]
            today_turnover = today_prices[code].get("Va") or 0

            if today_turnover < turnover_min:
                continue

            today_change = 0.0
            if len(closes_arr) >= 2 and closes_arr[-2] > 0:
                today_change = (today_close - closes_arr[-2]) / closes_arr[-2] * 100

            price_5d_chg = 0.0
            if len(closes_arr) >= 6:
                price_5d_chg = (today_close - closes_arr[-6]) / closes_arr[-6] * 100

            price_10d_chg = 0.0
            if len(closes_arr) >= 11:
                price_10d_chg = (today_close - closes_arr[-11]) / closes_arr[-11] * 100

            surge_ratio = details["surge_ratio"]

            m = master_dict.get(code, {})
            results.append({
                "code":           self._normalize_code(code),
                "_raw_code":      code,
                "name":           m.get("CoName", ""),
                "market":         m.get("MktNm", ""),
                "sector":         m.get("S33Nm", ""),
                "date":           today_date,
                "close":          today_close,
                "volume":         today_vol,
                "turnover":       today_turnover,
                "change_rate":    round(today_change, 2),
                "vol_ratio_5d":   round(surge_ratio, 2),
                "price_5d_chg":   round(price_5d_chg, 2),
                "price_10d_chg":  round(price_10d_chg, 2),
                "past_base":      details["past_base"],
                "recent_surge":   details["recent_surge"],
                "surge_ratio":    surge_ratio,
                "_score":         surge_ratio,
            })

        if not results:
            return []

        results.sort(key=lambda x: x["_score"], reverse=True)
        top = results[:top_n]

        # ── 3. 上位銘柄の6ヶ月チャートデータを並列取得 ──
        today_dt = datetime.strptime(today_date, "%Y-%m-%d")
        today_real = datetime.now().strftime("%Y-%m-%d")
        chart_from = (today_dt - timedelta(days=185)).strftime("%Y-%m-%d")
        if today_date < today_real:
            chart_to = min(
                (today_dt + timedelta(days=35)).strftime("%Y-%m-%d"),
                today_real,
            )
        else:
            chart_to = today_date

        def fetch_chart(s):
            raw_code = s.pop("_raw_code", None)
            if not raw_code:
                raw_code = s["code"] + "0" if len(s["code"]) == 4 else s["code"]
            try:
                price_data = self.get_prices(raw_code, chart_from, chart_to)
                if price_data:
                    valid = [
                        (p.get("Date", ""),
                         p.get("AdjC") or p.get("C"),
                         p.get("AdjVo") or p.get("Vo") or 0)
                        for p in price_data
                        if (p.get("AdjC") or p.get("C"))
                    ]
                    if valid:
                        dates_l, prices_l, vols_l = (list(x) for x in zip(*valid))
                        s["chart_dates"] = dates_l
                        s["chart_prices"] = prices_l
                        s["chart_volumes"] = vols_l

                        sig_idx = -1
                        for i in range(len(dates_l) - 1, -1, -1):
                            if dates_l[i] <= today_date:
                                sig_idx = i
                                break
                        s["signal_idx"] = sig_idx

                        if sig_idx >= 0 and sig_idx < len(prices_l):
                            sig_p = prices_l[sig_idx]
                            def _fwd(n_days):
                                idx = sig_idx + n_days
                                return round((prices_l[idx] / sig_p - 1) * 100, 2) \
                                    if idx < len(prices_l) and sig_p else None
                            s["fwd_5d"] = _fwd(5)
                            s["fwd_10d"] = _fwd(10)
                            s["fwd_20d"] = _fwd(20)
                        else:
                            s["fwd_5d"] = s["fwd_10d"] = s["fwd_20d"] = None
                        return

                s["chart_dates"] = s["chart_prices"] = s["chart_volumes"] = []
                s["signal_idx"] = -1
                s["fwd_5d"] = s["fwd_10d"] = s["fwd_20d"] = None
            except Exception as e:
                logger.warning(f"チャートデータ取得失敗 {raw_code}: {e}")
                s["chart_dates"] = s["chart_prices"] = s["chart_volumes"] = []
                s["signal_idx"] = -1
                s["fwd_5d"] = s["fwd_10d"] = s["fwd_20d"] = None

        with ThreadPoolExecutor(max_workers=8) as ex:
            list(ex.map(fetch_chart, top))

        # ── 4. タグ付け ──
        for s in top:
            tags = []
            sr = s["surge_ratio"]
            cr = s["change_rate"]
            va = s["turnover"]
            mkt = s["market"]

            if sr >= 8.0:   tags.append("爆発×8↑")
            elif sr >= 5.0: tags.append("急増×5↑")
            elif sr >= 3.0: tags.append("増加×3↑")
            else:           tags.append("初動×2.5↑")

            if cr >= 10:    tags.append("急騰")
            elif cr >= 3:   tags.append("上昇")
            elif cr >= -1:  tags.append("堅調")
            else:           tags.append("調整中")

            rs = s["recent_surge"]
            if rs >= 1_000_000:   tags.append("大出来高")
            elif rs >= 500_000:   tags.append("中出来高")

            if va >= 10_000_000_000: tags.append("超大型")
            elif va >= 1_000_000_000: tags.append("大商い")

            if mkt == "グロース":  tags.append("グロース")
            elif mkt == "プライム": tags.append("プライム")

            s["tags"] = tags

        return top

    # ========== バックテスト最適化 ==========

    def run_backtest_optimization(self, test_date: str,
                                  multi_date: bool = True,
                                  top_n: int = 20) -> Dict:
        """
        パラメータグリッドサーチで最高勝率の条件を自動探索する。

        test_date を基点に ±3週間（7日刻み）の取引日でテストし、
        128通りのパラメータ組み合わせ × 全テスト日の勝率を集計して順位付けする。

        Returns:
            success, test_dates, combinations (勝率順上位20件),
            best_20d, best_10d, total_combinations, total_time
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import itertools

        t0 = time.time()
        today_real = datetime.now().strftime("%Y-%m-%d")

        # ── 1. テスト日付候補 ──
        base_dt = datetime.strptime(test_date, "%Y-%m-%d")
        offsets = range(-21, 22, 7) if multi_date else [0]
        candidate_test_dates = sorted({
            (base_dt + timedelta(days=o)).strftime("%Y-%m-%d")
            for o in offsets
            if (base_dt + timedelta(days=o)).strftime("%Y-%m-%d") < today_real
        })
        if not candidate_test_dates:
            return {"success": False, "error": "有効なテスト日付なし（未来の日付は指定できません）"}

        # ── 2. フェッチ範囲（テスト期間前後を含む） ──
        earliest_dt = datetime.strptime(min(candidate_test_dates), "%Y-%m-%d")
        latest_dt   = datetime.strptime(max(candidate_test_dates), "%Y-%m-%d")
        fetch_from  = earliest_dt - timedelta(days=40)
        fetch_to    = min((latest_dt + timedelta(days=35)).strftime("%Y-%m-%d"), today_real)

        cal_dates = []
        d = fetch_from
        while d.strftime("%Y-%m-%d") <= fetch_to:
            cal_dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(days=1)

        logger.info(f"最適化: {len(candidate_test_dates)}テスト日, {len(cal_dates)}日分フェッチ")

        # ── 3. 全期間を並列フェッチ ──
        all_data: Dict[str, Dict] = {}

        def _fetch(date):
            data = self._fetch_prices_for_date(date)
            if data and len(data) > 100:
                return date, {p["Code"]: p for p in data}
            return date, None

        with ThreadPoolExecutor(max_workers=4) as ex:  # レート制限対策
            futures = {ex.submit(_fetch, date): date for date in cal_dates}
            for fut in as_completed(futures):
                date, result = fut.result()
                if result:
                    all_data[date] = result

        trading_days_sorted = sorted(all_data.keys())
        if len(trading_days_sorted) < 10:
            return {"success": False, "error": "データ取得失敗（取引日データ不足）"}

        # ── 4. マスターデータ ──
        master = self.get_master()
        if not master:
            return {"success": False, "error": "マスターデータ取得失敗"}
        master_dict = {item["Code"]: item for item in master}
        valid_codes = {item["Code"] for item in master if item.get("MktNm") != "TOKYO PRO MARKET"}

        # ── 5. 各テスト日のユニバース算出 ──
        # trading_date -> list of {code, market, vol_ratio, price_5d_chg, turnover, fwd_5d/10d/20d}
        stock_universe: Dict[str, List[Dict]] = {}

        def _stats(vals):
            if not vals:
                return None, None, 0
            w = sum(1 for v in vals if v > 0)
            return round(w / len(vals) * 100, 1), round(sum(vals) / len(vals), 2), len(vals)

        for td in candidate_test_dates:
            before = [d for d in trading_days_sorted if d <= td]
            if len(before) < 8:
                continue
            before = before[-25:]
            today_date = before[-1]
            if today_date in stock_universe:
                continue  # 同一取引日への重複処理スキップ

            today_prices = all_data[today_date]
            after = [d for d in trading_days_sorted if d > today_date]

            # 順方向価格マップ（n=5,10,20営業日後）
            fwd_map: Dict[int, Dict[str, float]] = {}
            for n in [5, 10, 20]:
                if len(after) >= n:
                    t = after[n - 1]
                    fwd_map[n] = {
                        code: float(pdata.get("AdjC") or pdata.get("C"))
                        for code, pdata in all_data[t].items()
                        if (pdata.get("AdjC") or pdata.get("C"))
                    }

            stocks_list = []
            for code in valid_codes:
                if code not in today_prices:
                    continue

                closes, volumes = [], []
                for d in before:
                    pdata = all_data[d].get(code)
                    if not pdata:
                        continue
                    c = pdata.get("AdjC") or pdata.get("C")
                    v = pdata.get("AdjVo") or pdata.get("Vo") or 0
                    if c:
                        closes.append(float(c))
                        volumes.append(float(v))

                if len(closes) < 5:
                    continue

                today_close    = closes[-1]
                today_turnover = float(today_prices[code].get("Va") or 0)
                if today_close == 0:
                    continue

                # 週次出来高比率
                recent_vols   = volumes[-5:]
                recent_avg    = sum(recent_vols) / len(recent_vols)
                baseline_vols = (volumes[-20:-5] if len(volumes) >= 20
                                 else volumes[:-5] if len(volumes) > 5 else [])
                baseline_avg  = (sum(baseline_vols) / len(baseline_vols)
                                 if baseline_vols else recent_avg or 1)
                vol_ratio     = recent_avg / baseline_avg if baseline_avg > 0 else 0

                # 5日騰落率
                ref = closes[-6] if len(closes) >= 6 else closes[0]
                price_5d_chg = (today_close - ref) / ref * 100 if ref > 0 else 0.0

                # 順方向リターン
                fwd = {}
                for n in [5, 10, 20]:
                    fp = fwd_map.get(n, {}).get(code)
                    fwd[f'fwd_{n}d'] = round((fp / today_close - 1) * 100, 2) if fp and today_close else None

                m = master_dict.get(code, {})
                stocks_list.append({
                    "code":         code,
                    "market":       m.get("MktNm", ""),
                    "vol_ratio":    vol_ratio,
                    "price_5d_chg": price_5d_chg,
                    "turnover":     today_turnover,
                    **fwd,
                })

            stock_universe[today_date] = stocks_list
            logger.info(f"  {today_date}: {len(stocks_list)}銘柄")

        if not stock_universe:
            return {"success": False, "error": "有効なテストデータなし（データ不足）"}

        # ── 6. パラメータグリッドサーチ ──
        grid = {
            'vol_ratio_min':    [1.5, 2.0, 2.5, 3.0],
            'price_5d_chg_min': [0.0, 1.0, 3.0, 5.0],
            'min_turnover':     [50_000_000, 100_000_000, 500_000_000, 1_000_000_000],
            'market':           ['', 'プライム'],
        }
        grid_keys  = list(grid.keys())
        grid_combos = list(itertools.product(*grid.values()))

        combo_results = []
        for combo in grid_combos:
            p = dict(zip(grid_keys, combo))
            fwd_all = {5: [], 10: [], 20: []}
            total_picks = 0
            date_count  = 0

            for stocks in stock_universe.values():
                filtered = [
                    s for s in stocks
                    if s['vol_ratio']    >= p['vol_ratio_min']
                    and s['price_5d_chg'] > p['price_5d_chg_min']
                    and s['turnover']    >= p['min_turnover']
                    and (not p['market'] or s['market'] == p['market'])
                ]
                for s in filtered:
                    vs = min(s['vol_ratio'] / 5.0, 1.0)
                    ps = min(max(s['price_5d_chg'], 0) / 15.0, 1.0)
                    s['_s'] = vs * 0.5 + ps * 0.5
                filtered.sort(key=lambda x: x['_s'], reverse=True)
                top = filtered[:top_n]

                if not top:
                    continue
                date_count  += 1
                total_picks += len(top)
                for s in top:
                    for n in [5, 10, 20]:
                        v = s.get(f'fwd_{n}d')
                        if v is not None:
                            fwd_all[n].append(v)

            if not fwd_all[10]:
                continue

            wr5,  ar5,  n5  = _stats(fwd_all[5])
            wr10, ar10, n10 = _stats(fwd_all[10])
            wr20, ar20, n20 = _stats(fwd_all[20])

            combo_results.append({
                **p,
                'date_count':    date_count,
                'avg_picks':     round(total_picks / max(date_count, 1), 1),
                'win_rate_5d':   wr5,  'avg_return_5d':  ar5,  'n_5d':  n5,
                'win_rate_10d':  wr10, 'avg_return_10d': ar10, 'n_10d': n10,
                'win_rate_20d':  wr20, 'avg_return_20d': ar20, 'n_20d': n20,
            })

        # ── スコアリング（発動頻度ハードフィルター） ──
        # 「100%勝率・3日・1銘柄」は統計的に無意味 → 厳格に除外
        total_dates    = len(stock_universe)
        min_date_count = max(5, int(total_dates * 0.4))  # 40%以上の月で発動
        min_avg_picks  = 3.0                              # 平均3銘柄以上

        combo_results = [
            c for c in combo_results
            if c['date_count'] >= min_date_count
            and (c['avg_picks'] or 0) >= min_avg_picks
        ]

        # 勝率のみでソート（avg_returnは参考値。高リターンは少銘柄バイアスがあるため）
        def _score_20d(x):
            return (x['win_rate_20d'] or 0) * 2 + min((x['avg_return_20d'] or 0), 15)

        def _score_10d(x):
            return (x['win_rate_10d'] or 0) * 2 + min((x['avg_return_10d'] or 0), 15)

        combo_results.sort(key=_score_20d, reverse=True)
        best_20d = combo_results[0] if combo_results else None
        best_10d = sorted(combo_results, key=_score_10d, reverse=True)[0] if combo_results else None

        return {
            'success':            True,
            'test_dates':         sorted(stock_universe.keys()),
            'combinations':       combo_results[:20],
            'best_20d':           best_20d,
            'best_10d':           best_10d,
            'total_combinations': len(combo_results),
            'total_time':         round(time.time() - t0, 1),
        }

    def validate_params_at_dates(self, params: Dict, test_dates: List[str]) -> Dict:
        """
        指定したパラメータを各過去時点でテストし、各日付の結果を返す。

        全ウィンドウのカレンダー日付を一括並列フェッチ（高速）しつつ、
        各テスト日の評価は自分の窓データのみを使う（クロスコンタミネーション防止）。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        t0         = time.time()
        today_real = datetime.now().strftime("%Y-%m-%d")

        master      = self.get_master()
        master_dict = {item["Code"]: item for item in master}
        valid_codes = {item["Code"] for item in master
                       if item.get("MktNm") != "TOKYO PRO MARKET"}

        vol_ratio_min    = float(params.get('vol_ratio_min', 5.0))
        price_5d_chg_min = float(params.get('price_5d_chg_min', 0.0))
        min_turnover     = float(params.get('turnover_min', params.get('min_turnover', 500_000_000)))
        market           = params.get('market', '')
        top_n            = int(params.get('top_n', 20))

        def _fetch(date):
            data = self._fetch_prices_for_date(date)
            if data and len(data) > 100:
                return date, {p["Code"]: p for p in data}
            return date, None

        def _wr(stocks, n):
            vals = [s.get(f'fwd_{n}d') for s in stocks if s.get(f'fwd_{n}d') is not None]
            if not vals:
                return None, None
            w = sum(1 for v in vals if v > 0)
            return round(w / len(vals) * 100, 1), round(sum(vals) / len(vals), 2)

        results = []

        for i, td in enumerate(test_dates):
            if td >= today_real:
                results.append({'date': td, 'error': '未来の日付'})
                continue

            # ウィンドウ間に待機（レート制限対策: 前ウィンドウのリクエストが落ち着くまで）
            if i > 0:
                time.sleep(10)

            dt    = datetime.strptime(td, "%Y-%m-%d")
            start = dt - timedelta(days=40)
            end   = min(dt + timedelta(days=50),
                        datetime.strptime(today_real, "%Y-%m-%d"))

            # 平日のみフェッチ（土日はAPIが0件を返すだけなので省略して高速化）
            cal_dates = []
            d = start
            while d <= end:
                if d.weekday() < 5:   # 月〜金
                    cal_dates.append(d.strftime("%Y-%m-%d"))
                d += timedelta(days=1)

            logger.info(f"履歴検証 {td}: 平日{len(cal_dates)}日分フェッチ中...")

            window_data: Dict[str, Dict] = {}
            with ThreadPoolExecutor(max_workers=2) as ex:
                futures = {ex.submit(_fetch, date): date for date in cal_dates}
                for fut in as_completed(futures):
                    date, result = fut.result()
                    if result:
                        window_data[date] = result

            logger.info(f"  {td}: {len(window_data)}日取得")

            tds = sorted(window_data.keys())

            before = [d for d in tds if d <= td]
            if len(before) < 8:
                results.append({
                    'date': td,
                    'error': f'データ取得失敗（{len(before)}日分のみ取得、プランの取得期間外の可能性）',
                })
                continue

            before     = before[-25:]
            today_date = before[-1]
            after      = [d for d in tds if d > today_date]

            fwd_map: Dict[int, Dict] = {}
            for n in [5, 10, 20]:
                if len(after) >= n:
                    t = after[n - 1]
                    fwd_map[n] = {
                        code: float(pdata.get("AdjC") or pdata.get("C"))
                        for code, pdata in window_data[t].items()
                        if (pdata.get("AdjC") or pdata.get("C"))
                    }

            stocks_list = []
            today_prices = window_data.get(today_date, {})
            for code in valid_codes:
                if code not in today_prices:
                    continue

                closes, volumes = [], []
                for d in before:
                    pdata = window_data[d].get(code)
                    if not pdata:
                        continue
                    c = pdata.get("AdjC") or pdata.get("C")
                    v = pdata.get("AdjVo") or pdata.get("Vo") or 0
                    if c:
                        closes.append(float(c))
                        volumes.append(float(v))

                if len(closes) < 5:
                    continue

                today_close    = closes[-1]
                today_turnover = float(today_prices[code].get("Va") or 0)
                if today_close == 0:
                    continue

                recent_vols   = volumes[-5:]
                recent_avg    = sum(recent_vols) / len(recent_vols)
                baseline_vols = (volumes[-20:-5] if len(volumes) >= 20
                                 else volumes[:-5] if len(volumes) > 5 else [])
                baseline_avg  = (sum(baseline_vols) / len(baseline_vols)
                                 if baseline_vols else recent_avg or 1)
                vol_ratio     = recent_avg / baseline_avg if baseline_avg > 0 else 0

                ref          = closes[-6] if len(closes) >= 6 else closes[0]
                price_5d_chg = (today_close - ref) / ref * 100 if ref > 0 else 0.0

                fwd = {}
                for n in [5, 10, 20]:
                    fp = fwd_map.get(n, {}).get(code)
                    fwd[f'fwd_{n}d'] = round((fp / today_close - 1) * 100, 2) if fp and today_close else None

                m = master_dict.get(code, {})
                stocks_list.append({
                    "code":         code,
                    "name":         m.get("Name", code),
                    "market":       m.get("MktNm", ""),
                    "vol_ratio":    vol_ratio,
                    "price_5d_chg": price_5d_chg,
                    "turnover":     today_turnover,
                    **fwd,
                })

            filtered = [
                s for s in stocks_list
                if s['vol_ratio']    >= vol_ratio_min
                and s['price_5d_chg'] > price_5d_chg_min
                and s['turnover']    >= min_turnover
                and (not market or s['market'] == market)
            ]
            for s in filtered:
                vs = min(s['vol_ratio'] / 5.0, 1.0)
                ps = min(max(s['price_5d_chg'], 0) / 15.0, 1.0)
                s['_s'] = vs * 0.5 + ps * 0.5
            filtered.sort(key=lambda x: x['_s'], reverse=True)
            top = filtered[:top_n]

            wr20, ar20 = _wr(top, 20)
            wr10, ar10 = _wr(top, 10)
            wr5,  ar5  = _wr(top,  5)

            no_fwd = not fwd_map.get(20)  # 20日後データがない（直近すぎる）

            results.append({
                'date':           td,
                'actual_date':    today_date,
                'n_stocks':       len(top),
                'win_rate_20d':   wr20,
                'avg_return_20d': ar20,
                'win_rate_10d':   wr10,
                'avg_return_10d': ar10,
                'win_rate_5d':    wr5,
                'avg_return_5d':  ar5,
                'no_fwd_data':    no_fwd,
                'stocks': [
                    {
                        'code':         s['code'],
                        'name':         s.get('name', s['code']),
                        'market':       s['market'],
                        'vol_ratio':    round(s['vol_ratio'], 1),
                        'price_5d_chg': round(s['price_5d_chg'], 1),
                        'fwd_20d':      s.get('fwd_20d'),
                    }
                    for s in top
                ],
            })
            logger.info(f"  → actual={today_date}, 銘柄{len(top)}件, 勝率={wr20}%")

        return {
            'success':    True,
            'params':     params,
            'results':    results,
            'total_time': round(time.time() - t0, 1),
        }

    def run_large_scale_optimization(self,
                                     lookback_weeks: int = 12,
                                     step_weeks:     int = 2,
                                     n_trials:       int = 5000,
                                     top_n:          int = 20,
                                     base_params:    Optional[Dict] = None) -> Dict:
        """
        大規模ランダム探索最適化。

        base_params が指定された場合は「近傍探索（50%）+ 全体ランダム（50%）」で
        現在の最良条件を起点にさらに勝率を高める条件を探す。

        lookback_weeks / step_weeks で遡る期間と間隔を制御する。
        例: lookback_weeks=104, step_weeks=4 → 2年分を月次でテスト

        Returns:
            success, test_dates, combinations, best_20d, best_10d,
            total_combinations, total_time
        """
        import random
        from concurrent.futures import ThreadPoolExecutor, as_completed

        t0 = time.time()
        today_real = datetime.now()

        # ── 1. テスト日付を過去 lookback_weeks 週、step_weeks 刻みで生成 ──
        # 直近 25 日は forward data が取れないので避ける
        latest_test = today_real - timedelta(days=25)
        test_dates_candidates = []
        for w in range(0, lookback_weeks, step_weeks):
            d = (latest_test - timedelta(weeks=w)).strftime('%Y-%m-%d')
            test_dates_candidates.append(d)

        # ── 2. 必要なデータ範囲を一括フェッチ ──
        oldest_test = datetime.strptime(min(test_dates_candidates), '%Y-%m-%d')
        fetch_from  = oldest_test - timedelta(days=40)
        fetch_to    = min(
            (latest_test + timedelta(days=25)).strftime('%Y-%m-%d'),
            today_real.strftime('%Y-%m-%d')
        )

        # 土日をスキップ（API呼び出し数を約30%削減してレート制限回避）
        cal_dates = []
        d = fetch_from
        while d.strftime('%Y-%m-%d') <= fetch_to:
            if d.weekday() < 5:  # 月〜金のみ
                cal_dates.append(d.strftime('%Y-%m-%d'))
            d += timedelta(days=1)

        logger.info(f"大規模最適化: {len(test_dates_candidates)}テスト日, {n_trials}試行, {len(cal_dates)}営業日フェッチ")

        all_data: Dict[str, Dict] = {}

        def _fetch(date):
            data = self._fetch_prices_for_date(date)
            if data and len(data) > 100:
                # 必要な3フィールドのみ保持してメモリを削減（全フィールド保持だと270MB超になる）
                return date, {
                    p['Code']: {
                        'AdjC': p.get('AdjC'),
                        'C':    p.get('C'),
                        'AdjVo': p.get('AdjVo'),
                        'Vo':   p.get('Vo'),
                        'Va':   p.get('Va'),
                    }
                    for p in data
                }
            return date, None

        # max_workers=4 に抑えてレート制限を回避
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(_fetch, date): date for date in cal_dates}
            for fut in as_completed(futures):
                date, result = fut.result()
                if result:
                    all_data[date] = result

        trading_days_sorted = sorted(all_data.keys())
        if len(trading_days_sorted) < 10:
            return {
                'success': False,
                'error': f'データ取得失敗（取得できた取引日: {len(trading_days_sorted)}日 / 試行: {len(cal_dates)}日）'
                         ' - J-Quantsプランの履歴制限かレート制限の可能性があります'
            }

        # ── 3. マスターデータ ──
        master = self.get_master()
        if not master:
            return {'success': False, 'error': 'マスターデータ取得失敗'}
        master_dict = {item['Code']: item for item in master}
        valid_codes = {item['Code'] for item in master if item.get('MktNm') != 'TOKYO PRO MARKET'}

        def _stats(vals):
            if not vals:
                return None, None, 0
            w = sum(1 for v in vals if v > 0)
            return round(w / len(vals) * 100, 1), round(sum(vals) / len(vals), 2), len(vals)

        # ── 4. 各テスト日のユニバース算出 ──
        stock_universe: Dict[str, List[Dict]] = {}

        for td in test_dates_candidates:
            before = [d for d in trading_days_sorted if d <= td]
            if len(before) < 8:
                continue
            today_date = before[-1]
            if today_date in stock_universe:
                continue

            today_prices = all_data.get(today_date)
            if not today_prices:
                continue

            after = [d for d in trading_days_sorted if d > today_date]
            fwd_map: Dict[int, Dict[str, float]] = {}
            for n in [5, 10, 20]:
                if len(after) >= n:
                    t = after[n - 1]
                    fwd_map[n] = {
                        code: float(pdata.get('AdjC') or pdata.get('C'))
                        for code, pdata in all_data[t].items()
                        if (pdata.get('AdjC') or pdata.get('C'))
                    }

            before_window = before[-25:]
            stocks_list = []
            for code in valid_codes:
                if code not in today_prices:
                    continue
                closes, volumes = [], []
                for day in before_window:
                    pdata = all_data[day].get(code)
                    if not pdata:
                        continue
                    c = pdata.get('AdjC') or pdata.get('C')
                    v = pdata.get('AdjVo') or pdata.get('Vo') or 0
                    if c:
                        closes.append(float(c))
                        volumes.append(float(v))

                if len(closes) < 5:
                    continue

                today_close    = closes[-1]
                today_turnover = float(today_prices[code].get('Va') or 0)
                if today_close == 0:
                    continue

                recent_vols   = volumes[-5:]
                recent_avg    = sum(recent_vols) / len(recent_vols)
                baseline_vols = (volumes[-20:-5] if len(volumes) >= 20
                                 else volumes[:-5] if len(volumes) > 5 else [])
                baseline_avg  = (sum(baseline_vols) / len(baseline_vols)
                                 if baseline_vols else recent_avg or 1)
                vol_ratio     = recent_avg / baseline_avg if baseline_avg > 0 else 0

                ref          = closes[-6] if len(closes) >= 6 else closes[0]
                price_5d_chg = (today_close - ref) / ref * 100 if ref > 0 else 0.0

                fwd = {}
                for n in [5, 10, 20]:
                    fp = fwd_map.get(n, {}).get(code)
                    fwd[f'fwd_{n}d'] = round((fp / today_close - 1) * 100, 2) if fp and today_close else None

                m = master_dict.get(code, {})
                stocks_list.append({
                    'code':         code,
                    'market':       m.get('MktNm', ''),
                    'vol_ratio':    vol_ratio,
                    'price_5d_chg': price_5d_chg,
                    'turnover':     today_turnover,
                    **fwd,
                })

            stock_universe[today_date] = stocks_list
            logger.info(f"  {today_date}: {len(stocks_list)}銘柄")

        if not stock_universe:
            return {'success': False, 'error': '有効なテストデータなし'}

        # ── 5. ランダムサーチ n_trials 通り ──
        # パラメータの探索空間（top_nも変数化して勝率を最大化）
        vol_ratio_choices    = [round(x * 0.5, 1) for x in range(2, 31)]    # 1.0〜15.0（0.5刻み）
        price_5d_chg_choices = [round(x * 0.5, 1) for x in range(-4, 21)]   # -2.0〜10.0
        # 売買代金: 1000万〜30億（対数スケールで均等サンプリング）
        turnover_choices = [int(10 ** (math.log10(10_000_000) + i *
                             (math.log10(3_000_000_000) - math.log10(10_000_000)) / 49))
                            for i in range(50)]
        market_choices = ['', '', '', 'プライム', 'スタンダード']  # '' を多めに
        top_n_choices  = [3, 5, 7, 10, 15, 20]   # 上位何銘柄を選ぶか（少ないほど高シグナル）

        random.seed(None)  # 毎回異なる探索（base_paramsがある場合の近傍は毎回変化）
        seen = set()
        trials = []
        attempts = 0
        n_neighborhood = n_trials // 2 if base_params else 0  # base_paramsがあれば半数を近傍探索

        while len(trials) < n_trials and attempts < n_trials * 5:
            attempts += 1
            use_neighborhood = base_params and len(trials) < n_neighborhood

            if use_neighborhood:
                # ── 近傍探索: 現在の最良条件を起点に±調整 ──
                bv  = base_params.get('vol_ratio_min', 5.0)
                bp  = base_params.get('price_5d_chg_min', 0.0)
                bt  = base_params.get('turnover_min', 500_000_000)
                bm  = base_params.get('market', '')
                btn = int(base_params.get('top_n', 20))
                # 各パラメータに±ノイズを加えて近傍点を生成
                nv = round(max(1.0, bv * random.uniform(0.5, 2.0)), 1)
                np_ = round(bp + random.uniform(-3.0, 5.0), 1)
                nt = int(max(10_000_000, bt * random.uniform(0.2, 5.0)))
                nm = random.choice([bm, bm, bm, '', 'プライム', 'スタンダード'])
                nn = random.choice([max(3, btn - 5), max(3, btn - 2), btn,
                                    min(20, btn + 2), min(20, btn + 5)])
                # 最も近い候補値に丸める
                nv = min(vol_ratio_choices,    key=lambda x: abs(x - nv))
                np_ = min(price_5d_chg_choices, key=lambda x: abs(x - np_))
                nt = min(turnover_choices,      key=lambda x: abs(x - nt))
                p = (nv, np_, nt, nm, nn)
            else:
                # ── 全体ランダム探索 ──
                p = (
                    random.choice(vol_ratio_choices),
                    random.choice(price_5d_chg_choices),
                    random.choice(turnover_choices),
                    random.choice(market_choices),
                    random.choice(top_n_choices),
                )

            if p not in seen:
                seen.add(p)
                trials.append({
                    'vol_ratio_min':    p[0],
                    'price_5d_chg_min': p[1],
                    'min_turnover':     p[2],
                    'market':           p[3],
                    'top_n':            p[4],
                })

        combo_results = []
        for p in trials:
            fwd_all = {5: [], 10: [], 20: []}
            total_picks = 0
            date_count  = 0
            trial_top_n = p['top_n']

            for stocks in stock_universe.values():
                filtered = [
                    s for s in stocks
                    if s['vol_ratio']    >= p['vol_ratio_min']
                    and s['price_5d_chg'] > p['price_5d_chg_min']
                    and s['turnover']    >= p['min_turnover']
                    and (not p['market'] or s['market'] == p['market'])
                ]
                for s in filtered:
                    vs = min(s['vol_ratio'] / 10.0, 1.0)
                    ps = min(max(s['price_5d_chg'], 0) / 15.0, 1.0)
                    s['_s'] = vs * 0.5 + ps * 0.5
                filtered.sort(key=lambda x: x['_s'], reverse=True)
                top = filtered[:trial_top_n]
                if not top:
                    continue
                date_count  += 1
                total_picks += len(top)
                for s in top:
                    for n in [5, 10, 20]:
                        v = s.get(f'fwd_{n}d')
                        if v is not None:
                            fwd_all[n].append(v)

            if not fwd_all[10]:
                continue

            wr5,  ar5,  n5  = _stats(fwd_all[5])
            wr10, ar10, n10 = _stats(fwd_all[10])
            wr20, ar20, n20 = _stats(fwd_all[20])

            combo_results.append({
                **p,
                'date_count':    date_count,
                'avg_picks':     round(total_picks / max(date_count, 1), 1),
                'win_rate_5d':   wr5,  'avg_return_5d':  ar5,  'n_5d':  n5,
                'win_rate_10d':  wr10, 'avg_return_10d': ar10, 'n_10d': n10,
                'win_rate_20d':  wr20, 'avg_return_20d': ar20, 'n_20d': n20,
                'sample_size':   n20 or n10 or n5,  # 統計的信頼性の目安
            })

        # ── ハードフィルター: 発動頻度と最低銘柄数 ──
        # 「100%勝率・3日・1銘柄」を排除。統計的に意味ある条件のみ残す
        total_dates    = len(stock_universe)
        min_date_count = max(5, int(total_dates * 0.4))   # 40%以上の日付で発動
        min_avg_picks  = 3.0                               # 平均3銘柄以上
        combo_results = [
            c for c in combo_results
            if c['date_count'] >= min_date_count
            and (c['avg_picks'] or 0) >= min_avg_picks
        ]
        # avg_returnは上限15%でキャップ（少銘柄の外れ値バイアス対策）
        combo_results.sort(
            key=lambda x: ((x['win_rate_20d'] or 0) * 2 + min((x['avg_return_20d'] or 0), 15)),
            reverse=True
        )
        best_20d = combo_results[0] if combo_results else None
        best_10d = sorted(
            combo_results,
            key=lambda x: ((x['win_rate_10d'] or 0) * 2 + (x['avg_return_10d'] or 0)),
            reverse=True
        )[0] if combo_results else None

        return {
            'success':            True,
            'test_dates':         sorted(stock_universe.keys()),
            'combinations':       combo_results[:20],
            'best_20d':           best_20d,
            'best_10d':           best_10d,
            'total_combinations': len(combo_results),
            'total_time':         round(time.time() - t0, 1),
        }
