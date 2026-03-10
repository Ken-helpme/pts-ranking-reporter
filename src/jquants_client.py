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
        """API GETリクエスト"""
        url = f"{self.BASE_URL}{path}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"J-Quants API error: {e} - {resp.text[:200]}")
            return {"data": [], "error": str(e)}
        except Exception as e:
            logger.error(f"J-Quants request failed: {e}")
            return {"data": [], "error": str(e)}

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

    # ========== 出来高急増×上昇トレンド ==========

    def get_volume_breakout_stocks(self, days: int = 20, top_n: int = 20,
                                   target_date: Optional[str] = None,
                                   vol_ratio_min: float = 1.5,
                                   price_5d_chg_min: float = 0.0,
                                   turnover_min: int = 50_000_000,
                                   market: str = '') -> List[Dict]:
        """
        出来高急増 × 上昇トレンド銘柄を検出

        - 過去 days 日分の株価データを並列取得
        - 出来高比率（対象日 ÷ 前5日平均）と株価騰落率でスコアリング
        - 上位銘柄の6ヶ月日足チャートデータを並列取得して付与

        Args:
            days:        スコアリング用ルックバック日数
            top_n:       上位N銘柄を返す
            target_date: 対象基準日 (YYYY-MM-DD)。None=最新取引日

        Returns:
            List[Dict] with extra fields:
                vol_ratio_5d   : 今日出来高 ÷ 前5日平均出来高
                price_5d_chg   : 5日間株価騰落率(%)
                price_10d_chg  : 10日間株価騰落率(%)
                chart_dates    : 過去6ヶ月の日付リスト (YYYY-MM-DD)
                chart_prices   : 過去6ヶ月の終値リスト
                chart_volumes  : 過去6ヶ月の出来高リスト
                tags           : 特徴タグリスト
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        master = self.get_master()
        if not master:
            return []

        master_dict = {item["Code"]: item for item in master}
        valid_codes = {
            item["Code"]
            for item in master
            if item.get("MktNm") != "TOKYO PRO MARKET"
        }

        # ── 1. 過去 days+10 営業日候補を並列フェッチ ──
        if target_date:
            base = datetime.strptime(target_date, "%Y-%m-%d")
        else:
            base = datetime.now()

        candidate_dates = [
            (base - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(0, days + 10)
        ]

        date_data: Dict[str, Dict] = {}   # date -> {code: price_dict}

        def fetch_one(date: str):
            data = self._fetch_prices_for_date(date)
            if data and len(data) > 100:
                return date, {p["Code"]: p for p in data}
            return date, None

        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(fetch_one, d): d for d in candidate_dates}
            for fut in as_completed(futures):
                date, result = fut.result()
                if result:
                    date_data[date] = result

        # 有効な取引日を新しい順にソート
        trading_days = sorted(date_data.keys(), reverse=True)
        if len(trading_days) < 3:
            logger.warning("有効な取引日データが不足しています")
            return []

        # 直近 days 日分に絞る
        trading_days = trading_days[:days]
        today_date   = trading_days[0]   # 最新（or 対象）取引日
        today_prices = date_data[today_date]

        # ── 2. 銘柄ごとに指標を計算 ──
        results = []

        for code in valid_codes:
            if code not in today_prices:
                continue

            # 直近 days 日の終値・出来高を収集（新しい順 → 反転して古い順）
            closes  = []
            volumes = []
            for d in trading_days:
                p = date_data[d].get(code)
                if p is None:
                    continue
                c = p.get("AdjC") or p.get("C")
                v = p.get("AdjVo") or p.get("Vo") or 0
                if c:
                    closes.append(c)
                    volumes.append(v)

            if len(closes) < 3:
                continue

            # 古い順に並べ替え
            closes  = list(reversed(closes))
            volumes = list(reversed(volumes))

            today_close    = closes[-1]
            today_vol      = volumes[-1]
            today_turnover = today_prices[code].get("Va") or 0

            if today_close == 0:
                continue

            # ── 週次出来高比率（直近5日平均 ÷ 基準期間平均）──
            # 直近5日の平均
            recent_vols = volumes[-5:] if len(volumes) >= 5 else volumes
            recent_avg  = sum(recent_vols) / len(recent_vols) if recent_vols else 0
            # 基準期間（6〜20日前）の平均 — 十分なデータがない場合は利用可能な分を使う
            if len(volumes) >= 10:
                baseline_vols = volumes[-20:-5] if len(volumes) >= 20 else volumes[:-5]
            else:
                baseline_vols = volumes[:-1]  # データ不足時は前日までで代用
            baseline_avg = sum(baseline_vols) / len(baseline_vols) if baseline_vols else recent_avg or 1
            vol_ratio    = recent_avg / baseline_avg if baseline_avg > 0 else 0

            # 株価騰落率
            price_5d_chg  = 0.0
            price_10d_chg = 0.0
            if len(closes) >= 6:
                price_5d_chg  = (today_close - closes[-6]) / closes[-6] * 100
            elif len(closes) >= 2:
                price_5d_chg  = (today_close - closes[0]) / closes[0] * 100
            if len(closes) >= 10:
                price_10d_chg = (today_close - closes[-11]) / closes[-11] * 100 \
                    if len(closes) >= 11 else (today_close - closes[0]) / closes[0] * 100

            # 当日変化率（表示用）
            today_change = 0.0
            if len(closes) >= 2:
                prev_close = closes[-2]
                if prev_close > 0:
                    today_change = (today_close - prev_close) / prev_close * 100

            # ── フィルター（パラメータ化済み） ──
            if vol_ratio < vol_ratio_min:
                continue
            if price_5d_chg <= price_5d_chg_min:
                continue
            if today_turnover < turnover_min:
                continue
            if market and master_dict.get(code, {}).get("MktNm", "") != market:
                continue

            # スコア: 週次出来高比率 × 0.5 + 5日騰落率 × 0.5
            vol_score   = min(vol_ratio / 5.0, 1.0)
            price_score = min(max(price_5d_chg, 0) / 15.0, 1.0)
            score       = vol_score * 0.5 + price_score * 0.5

            m = master_dict.get(code, {})
            results.append({
                "code":           self._normalize_code(code),
                "_raw_code":      code,   # 5桁コード（チャートデータ取得用）
                "name":           m.get("CoName", ""),
                "market":         m.get("MktNm", ""),
                "sector":         m.get("S33Nm", ""),
                "date":           today_date,
                "close":          today_close,
                "volume":         today_vol,
                "turnover":       today_turnover,
                "change_rate":    round(today_change, 2),
                "vol_ratio_5d":   round(vol_ratio, 2),
                "price_5d_chg":   round(price_5d_chg, 2),
                "price_10d_chg":  round(price_10d_chg, 2),
                "_score":         score,
            })

        if not results:
            return []

        results.sort(key=lambda x: x["_score"], reverse=True)
        top = results[:top_n]

        # ── 3. 上位銘柄の6ヶ月チャートデータを並列取得 ──
        today_dt    = datetime.strptime(today_date, "%Y-%m-%d")
        today_real  = datetime.now().strftime("%Y-%m-%d")
        chart_from  = (today_dt - timedelta(days=185)).strftime("%Y-%m-%d")
        # 過去日付指定時はシグナル日以降のパフォーマンスも取得（バックテスト用）
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
                        s["chart_dates"]   = dates_l
                        s["chart_prices"]  = prices_l
                        s["chart_volumes"] = vols_l

                        # ── シグナル日インデックス特定 ──
                        sig_idx = -1
                        for i in range(len(dates_l) - 1, -1, -1):
                            if dates_l[i] <= today_date:
                                sig_idx = i
                                break
                        s["signal_idx"] = sig_idx

                        # ── 順方向リターン計算 ──
                        if sig_idx >= 0 and sig_idx < len(prices_l):
                            sig_p = prices_l[sig_idx]
                            def _fwd(n):
                                idx = sig_idx + n
                                return round((prices_l[idx] / sig_p - 1) * 100, 2) \
                                    if idx < len(prices_l) and sig_p else None
                            s["fwd_5d"]  = _fwd(5)
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
            vr  = s["vol_ratio_5d"]   # 週次平均出来高比率
            cr  = s["change_rate"]    # 当日変化率（表示用）
            va  = s["turnover"]
            mkt = s["market"]
            p5  = s["price_5d_chg"]

            # 週次出来高増加の強さ
            if vr >= 4:   tags.append("週次×4↑")
            elif vr >= 3: tags.append("週次×3↑")
            elif vr >= 2: tags.append("週次×2↑")
            else:         tags.append("週次増加")

            if cr >= 10:    tags.append("急騰")
            elif cr >= 5:   tags.append("上昇")
            else:           tags.append("堅調")

            if p5 >= 20:    tags.append("5日+20%↑")
            elif p5 >= 10:  tags.append("5日+10%↑")

            if va >= 10_000_000_000:  tags.append("超大型")
            elif va >= 1_000_000_000: tags.append("大商い")

            if mkt == "グロース":    tags.append("グロース")
            elif mkt == "プライム":  tags.append("プライム")

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

        with ThreadPoolExecutor(max_workers=8) as ex:
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

        # 20日勝率×2 + 平均リターン でスコアリング（勝率重視）
        combo_results.sort(
            key=lambda x: ((x['win_rate_20d'] or 0) * 2 + (x['avg_return_20d'] or 0)),
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

    def run_large_scale_optimization(self,
                                     lookback_weeks: int = 24,
                                     step_weeks:     int = 2,
                                     n_trials:       int = 5000,
                                     top_n:          int = 20) -> Dict:
        """
        大規模ランダム探索最適化。

        過去 lookback_weeks 週分（step_weeks 刻み）のテスト日を生成し、
        n_trials 通りのランダムパラメータ組み合わせを評価して
        最も勝率の高い条件を返す。

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

        cal_dates = []
        d = fetch_from
        while d.strftime('%Y-%m-%d') <= fetch_to:
            cal_dates.append(d.strftime('%Y-%m-%d'))
            d += timedelta(days=1)

        logger.info(f"大規模最適化: {len(test_dates_candidates)}テスト日, {n_trials}試行, {len(cal_dates)}日フェッチ")

        all_data: Dict[str, Dict] = {}

        def _fetch(date):
            data = self._fetch_prices_for_date(date)
            if data and len(data) > 100:
                return date, {p['Code']: p for p in data}
            return date, None

        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(_fetch, date): date for date in cal_dates}
            for fut in as_completed(futures):
                date, result = fut.result()
                if result:
                    all_data[date] = result

        trading_days_sorted = sorted(all_data.keys())
        if len(trading_days_sorted) < 15:
            return {'success': False, 'error': 'データ取得失敗（取引日データ不足）'}

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
        # パラメータの探索空間（グリッドより大幅に広い連続空間）
        vol_ratio_choices    = [round(x * 0.1, 1) for x in range(10, 51)]   # 1.0〜5.0
        price_5d_chg_choices = [round(x * 0.5, 1) for x in range(-4, 21)]   # -2.0〜10.0
        # 売買代金: 1000万〜30億（対数スケールで均等サンプリング）
        import math as _math
        turnover_choices = [int(10 ** (_math.log10(10_000_000) + i *
                             (_math.log10(3_000_000_000) - _math.log10(10_000_000)) / 49))
                            for i in range(50)]
        market_choices = ['', '', '', 'プライム', 'スタンダード']  # '' を多めに

        random.seed(42)  # 再現性のため固定シード（毎回同じ探索空間）
        seen = set()
        trials = []
        attempts = 0
        while len(trials) < n_trials and attempts < n_trials * 3:
            attempts += 1
            p = (
                random.choice(vol_ratio_choices),
                random.choice(price_5d_chg_choices),
                random.choice(turnover_choices),
                random.choice(market_choices),
            )
            if p not in seen:
                seen.add(p)
                trials.append({
                    'vol_ratio_min':    p[0],
                    'price_5d_chg_min': p[1],
                    'min_turnover':     p[2],
                    'market':           p[3],
                })

        combo_results = []
        for p in trials:
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

        combo_results.sort(
            key=lambda x: ((x['win_rate_20d'] or 0) * 2 + (x['avg_return_20d'] or 0)),
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
