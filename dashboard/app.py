"""
PTS ランキング ダッシュボード - Flask ウェブアプリケーション
モダンなデザインでPTSランキングを表示・管理
"""
from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
_base = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_base, '..', 'src'))
sys.path.insert(0, os.path.join(_base, '..', 'quant_research'))

from models import (init_db, save_pts_data, get_latest_ranking, get_historical_data,
                     get_statistics, save_trending_stocks, get_trending_stocks,
                     get_trending_dates, save_optimization_result, get_latest_optimization,
                     save_auto_optimization_log, get_auto_optimization_history,
                     save_signal_history, get_signal_history)
from trending_stock_fetcher import TrendingStockFetcher
from scraper import KabutanScraper
from analyzer import PTSAnalyzer
from news_fetcher import NewsFetcher
from stock_analyzer import StockAnalyzer
from disclosure_fetcher import DisclosureFetcher
from earnings_analyzer import EarningsAnalyzer
from pdf_analyzer import PDFAnalyzer
from stock_evaluator import StockEvaluator
from jquants_client import JQuantsClient

app = Flask(__name__)
app.config['SECRET_KEY'] = 'pts-ranking-dashboard-secret-key'

# Initialize database
init_db()

# Claude API Key
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

# J-Quants APIクライアント
jquants = JQuantsClient()

@app.route('/')
def index():
    """メインダッシュボード"""
    return render_template('dashboard.html')

@app.route('/api/latest')
def get_latest():
    """最新のPTSランキングを取得"""
    try:
        data = get_latest_ranking()
        return jsonify({
            'success': True,
            'data': data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/fetch')
def fetch_new_data():
    """新しいPTSデータをスクレイピングして保存"""
    try:
        api_key = os.getenv('ANTHROPIC_API_KEY')

        # Initialize all components
        scraper = KabutanScraper()
        analyzer = PTSAnalyzer(min_volume=100, top_n=20)
        news_fetcher = NewsFetcher(max_news=3)
        stock_analyzer = StockAnalyzer()
        disclosure_fetcher = DisclosureFetcher()
        earnings_analyzer = EarningsAnalyzer(api_key=api_key)
        pdf_analyzer = PDFAnalyzer()
        stock_evaluator = StockEvaluator()

        stocks = scraper.fetch_pts_ranking()

        if not stocks:
            return jsonify({
                'success': False,
                'error': 'PTSランキングの取得に失敗しました'
            }), 500

        filtered_stocks = analyzer.filter_and_rank(stocks)
        timestamp = datetime.now().isoformat()
        saved_count = 0

        for stock in filtered_stocks:
            code = stock['code']

            if not stock.get('name'):
                stock['name'] = scraper.fetch_stock_name(code)

            # ニュースと会社情報を取得
            news = news_fetcher.fetch_stock_news(code)
            company = news_fetcher.get_company_info(code) or {}

            # 開示情報を取得
            disclosure_info = disclosure_fetcher.fetch_disclosure_info(code)
            earnings_detail = None

            # 決算発表がある場合はPDF分析 + Claude API分析
            if disclosure_info.get('has_earnings'):
                disclosure_title = disclosure_info['disclosures'][0]['title'] if disclosure_info['disclosures'] else disclosure_info['earnings_summary']
                pdf_url = disclosure_info['disclosures'][0].get('pdf_url') if disclosure_info['disclosures'] else None

                # PDFがあればダウンロード＆テキスト抽出
                pdf_text = None
                if pdf_url:
                    pdf_text = pdf_analyzer.download_and_extract_pdf(pdf_url)

                # Claude APIで分析（PDFがあれば全文、なければタイトルのみ）
                if pdf_text and api_key:
                    earnings_detail = earnings_analyzer.analyze_with_pdf_text(pdf_text, stock)
                else:
                    earnings_detail = earnings_analyzer.analyze_earnings_detail(
                        disclosure_title, news, stock
                    )

                # 決算ニュースをリストの先頭に追加
                if earnings_detail and earnings_detail.get('earnings_reason'):
                    earnings_news = {
                        'title': f"【決算】{disclosure_info['earnings_summary']} - {earnings_detail['earnings_reason'][:80]}",
                        'date': disclosure_info['disclosures'][0]['date'] if disclosure_info['disclosures'] else '',
                        'url': disclosure_info['disclosures'][0]['url'] if disclosure_info['disclosures'] else '',
                        'source': '開示情報',
                        'has_pdf_analysis': pdf_text is not None
                    }
                    news.insert(0, earnings_news)

            # 上昇理由を分析
            analysis = stock_analyzer.analyze_price_increase_reason(news, stock)

            # 決算分析を追加
            if earnings_detail:
                analysis['earnings_detail'] = earnings_detail

            # 総合評価を算出
            evaluation = stock_evaluator.evaluate_stock(stock, company, analysis)
            analysis['evaluation'] = evaluation

            save_pts_data(stock, news, company, timestamp, analysis)
            saved_count += 1

        # Cleanup
        scraper.close()
        news_fetcher.close()
        disclosure_fetcher.close()

        return jsonify({
            'success': True,
            'message': f'{saved_count}銘柄のデータを取得・保存しました',
            'count': saved_count
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/history')
def get_history():
    """過去データを取得"""
    try:
        days = request.args.get('days', 7, type=int)
        code = request.args.get('code', None)
        data = get_historical_data(days=days, stock_code=code)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stats')
def get_stats():
    """統計情報を取得"""
    try:
        stats = get_statistics()
        return jsonify({'success': True, 'data': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/stock/<code>')
def get_stock_detail(code):
    """特定銘柄の詳細情報を取得"""
    try:
        data = get_historical_data(days=30, stock_code=code)
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== 話題株ピックアップ ==========

@app.route('/trending')
def trending():
    """話題株ピックアップページ"""
    return render_template('trending.html')

@app.route('/api/trending/latest')
def get_trending_latest():
    """最新の話題株データを取得"""
    try:
        date = request.args.get('date', None)
        data = get_trending_stocks(date=date)
        return jsonify({
            'success': True,
            'data': data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/trending/fetch')
def fetch_trending_data():
    """話題株データを新規取得・保存"""
    try:
        fetcher = TrendingStockFetcher()
        try:
            stocks = fetcher.fetch_trending_stocks()
            if not stocks:
                return jsonify({
                    'success': False,
                    'error': '話題株データの取得に失敗しました'
                }), 500

            # 保存
            fetch_date = datetime.now().strftime('%Y-%m-%d')
            save_trending_stocks(stocks, fetch_date)

            return jsonify({
                'success': True,
                'message': f'{len(stocks)}銘柄の話題株データを取得・保存しました',
                'count': len(stocks)
            })
        finally:
            fetcher.close()

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/trending/dates')
def get_trending_date_list():
    """話題株データがある日付リストを取得"""
    try:
        dates = get_trending_dates()
        return jsonify({'success': True, 'dates': dates})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== J-Quants PTSランキング ==========

@app.route('/api/jquants/ranking')
def jquants_ranking():
    """J-QuantsデータでPTSランキング（出来高上位）"""
    try:
        market = request.args.get('market', '')
        sort_by = request.args.get('sort', 'volume')
        limit = request.args.get('limit', 20, type=int)

        filters = {
            'market': market,
            'volume_min': 100000,
            'sort_by': sort_by,
            'sort_desc': True,
            'limit': limit,
        }
        results = jquants.screen_stocks(filters)

        return jsonify({
            'success': True,
            'data': results,
            'total': len(results),
            'source': 'J-Quants API'
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/jquants/stock/<code>')
def jquants_stock_detail(code):
    """J-Quantsで個別銘柄の詳細データ取得"""
    try:
        # マスター情報
        master = jquants.get_master(code + '0' if len(code) == 4 else code)
        # 株価データ（直近30日）
        from datetime import timedelta
        to_date = datetime.now().strftime('%Y-%m-%d')
        from_date = (datetime.now() - timedelta(days=40)).strftime('%Y-%m-%d')
        prices = jquants.get_prices(code + '0' if len(code) == 4 else code, from_date, to_date)
        # 決算サマリー
        fins = jquants.get_financial_summary(code + '0' if len(code) == 4 else code)

        return jsonify({
            'success': True,
            'master': master[0] if master else {},
            'prices': prices[-10:] if prices else [],  # 直近10日分
            'financials': fins[-2:] if fins else [],    # 直近2期分
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ========== 銘柄スクリーニング ==========

@app.route('/screening')
def screening_page():
    """銘柄スクリーニングページ"""
    return render_template('screening.html')

@app.route('/api/screening/sectors')
def screening_sectors():
    """業種一覧"""
    try:
        sectors = jquants.get_sectors()
        return jsonify({'success': True, 'sectors': sectors})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/screening/search', methods=['POST'])
def screening_search():
    """スクリーニング実行"""
    try:
        filters = request.get_json() or {}
        results = jquants.screen_stocks(filters)
        date = results[0]['date'] if results else ''
        return jsonify({
            'success': True,
            'results': results,
            'total': len(results),
            'date': date
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

_validate_jobs: dict = {}        # job_id -> {status, progress, result, cancelled}
_current_validate_job: list = [None]  # [job_id] — 現在実行中のジョブ（1つだけ）

@app.route('/api/screening/validate_history', methods=['POST'])
def screening_validate_history():
    """バックグラウンドで履歴検証を開始し、job_id を返す（前のジョブは自動キャンセル）"""
    import threading, uuid
    try:
        body   = request.get_json(silent=True) or {}
        params = body.get('params', {})
        if not params:
            return jsonify({'success': False, 'error': 'params が指定されていません'})

        # 前のジョブをキャンセル（同時実行防止）
        prev = _current_validate_job[0]
        if prev and prev in _validate_jobs:
            _validate_jobs[prev]['cancelled'] = True

        from datetime import date
        today = date.today()

        def months_ago(m):
            import calendar
            y, mo = divmod(today.month - m - 1, 12)
            last_day = calendar.monthrange(today.year + y, mo + 1)[1]
            return date(today.year + y, mo + 1, min(today.day, last_day)).isoformat()

        def years_ago(y):
            try:
                return date(today.year - y, today.month, today.day).isoformat()
            except ValueError:
                return date(today.year - y, today.month, 28).isoformat()

        test_dates = [months_ago(3), months_ago(6), years_ago(1), years_ago(2), years_ago(3)]
        labels     = ['3ヶ月前', '6ヶ月前', '1年前', '2年前', '3年前']

        job_id = str(uuid.uuid4())[:8]
        _validate_jobs[job_id] = {'status': 'running', 'progress': [], 'result': None, 'cancelled': False}
        _current_validate_job[0] = job_id

        def _run():
            try:
                results = []
                for td, label in zip(test_dates, labels):
                    if _validate_jobs[job_id].get('cancelled'):
                        break
                    _validate_jobs[job_id]['progress'].append(f'{label}（{td}）を処理中...')
                    partial = jquants.validate_params_at_dates(params=params, test_dates=[td])
                    if _validate_jobs[job_id].get('cancelled'):
                        break
                    if partial.get('success') and partial.get('results'):
                        results.append(partial['results'][0])
                    else:
                        results.append({'date': td, 'error': partial.get('error', '取得失敗')})

                if not _validate_jobs[job_id].get('cancelled'):
                    _validate_jobs[job_id]['status'] = 'done'
                    _validate_jobs[job_id]['result'] = {
                        'success': True, 'params': params,
                        'results': results, 'total_time': '–'
                    }
            except Exception as e:
                _validate_jobs[job_id]['status'] = 'error'
                _validate_jobs[job_id]['result'] = {'success': False, 'error': str(e)}

        threading.Thread(target=_run, daemon=True).start()
        return jsonify({'success': True, 'job_id': job_id})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/screening/validate_history_poll/<job_id>')
def screening_validate_history_poll(job_id):
    """ポーリング: 履歴検証の進捗・結果を返す"""
    job = _validate_jobs.get(job_id)
    if not job:
        return jsonify({'success': False, 'error': 'job not found'})
    return jsonify({
        'status':   job['status'],
        'progress': job.get('progress', []),
        'result':   job.get('result'),
    })

@app.route('/api/screening/optimize', methods=['GET', 'POST'])
def screening_optimize():
    """大規模ランダム探索最適化（近傍探索 + グローバル探索）"""
    try:
        body        = request.get_json(silent=True) or {}
        n_trials    = body.get('n',        request.args.get('n',        5000, type=int))
        lookback    = body.get('lookback', request.args.get('lookback', 12,   type=int))
        step        = body.get('step',     request.args.get('step',     2,    type=int))
        base_params = body.get('base_params', None)   # 現在の最良条件（近傍探索に使用）
        result = jquants.run_large_scale_optimization(
            lookback_weeks=lookback,
            step_weeks=step,
            n_trials=n_trials,
            base_params=base_params,
        )
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/screening/volume_breakout')
def screening_volume_breakout():
    """出来高急増×上昇トレンド銘柄"""
    try:
        days             = request.args.get('days', 10, type=int)
        top_n            = request.args.get('n', 20, type=int)
        target_date      = request.args.get('date', None)
        vol_ratio_min    = request.args.get('vol_ratio_min', 1.5, type=float)
        price_5d_chg_min = request.args.get('price_5d_chg_min', 0.0, type=float)
        turnover_min     = request.args.get('turnover_min', 50_000_000, type=int)
        market_filter    = request.args.get('market', '')
        stocks = jquants.get_volume_breakout_stocks(
            days=days, top_n=top_n, target_date=target_date,
            vol_ratio_min=vol_ratio_min, price_5d_chg_min=price_5d_chg_min,
            turnover_min=turnover_min, market=market_filter,
        )
        date = stocks[0]['date'] if stocks else ''

        # ── バックテスト勝率集計 ──
        win_stats = None
        today_str = datetime.now().strftime('%Y-%m-%d')
        if target_date and target_date < today_str and stocks:
            ws = {}
            for n, key in [(5, '5d'), (10, '10d'), (20, '20d')]:
                vals = [s[f'fwd_{key}'] for s in stocks if s.get(f'fwd_{key}') is not None]
                if vals:
                    wins = sum(1 for v in vals if v > 0)
                    ws[f'win_rate_{key}']   = round(wins / len(vals) * 100, 1)
                    ws[f'avg_return_{key}'] = round(sum(vals) / len(vals), 2)
                    ws[f'count_{key}']      = len(vals)
            win_stats = ws if ws else None

        return jsonify({
            'success': True,
            'stocks': stocks,
            'total': len(stocks),
            'date': date,
            'days': days,
            'win_stats': win_stats,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/screening/top_picks')
def screening_top_picks():
    """今買うべき銘柄トップ10"""
    try:
        n = request.args.get('n', 10, type=int)
        picks = jquants.get_top_picks(n=n)
        date = picks[0]['date'] if picks else ''
        return jsonify({
            'success': True,
            'picks': picks,
            'total': len(picks),
            'date': date
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/screening/auto_optimize', methods=['POST'])
def screening_auto_optimize():
    """Cloud Schedulerから呼ばれる自動最適化（夜間バッチ）"""
    # 簡易認証: OPTIMIZE_SECRET ヘッダーで保護
    secret = os.getenv('OPTIMIZE_SECRET', '')
    if secret and request.headers.get('X-Optimize-Secret', '') != secret:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401

    try:
        # 過去6ヶ月 × 5000通りのランダム探索
        result = jquants.run_large_scale_optimization(
            lookback_weeks=24,
            step_weeks=2,
            n_trials=5000,
        )

        if not result.get('success'):
            return jsonify({'success': False, 'error': result.get('error', 'optimization failed')}), 500

        best = result.get('best_20d') or (result['combinations'][0] if result.get('combinations') else None)
        if not best:
            return jsonify({'success': False, 'error': 'No best params found'}), 500

        best_params = {
            'vol_ratio_min':    best['vol_ratio_min'],
            'price_5d_chg_min': best['price_5d_chg_min'],
            'turnover_min':     best.get('min_turnover', best.get('turnover_min', 50_000_000)),
            'market':           best.get('market', ''),
        }
        win_stats = {
            'win_rate_20d':      best.get('win_rate_20d'),
            'avg_return_20d':    best.get('avg_return_20d'),
            'win_rate_10d':      best.get('win_rate_10d'),
            'avg_return_10d':    best.get('avg_return_10d'),
            'total_combinations': result.get('total_combinations', 0),
        }
        center_date = result['test_dates'][len(result['test_dates'])//2] if result.get('test_dates') else ''
        save_optimization_result(best_params, win_stats, center_date, result.get('test_dates', []))

        return jsonify({
            'success': True,
            'best_params': best_params,
            'win_stats': win_stats,
            'center_date': center_date,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/screening/best_params')
def screening_best_params():
    """フロントエンドが起動時に呼ぶ：DB保存済み最良パラメータを返す"""
    try:
        opt = get_latest_optimization()
        if not opt:
            return jsonify({'success': False, 'error': 'No optimization result yet'})
        return jsonify({
            'success': True,
            'best_params':    opt['best_params'],
            'win_rate_20d':   opt['win_rate_20d'],
            'avg_return_20d': opt['avg_return_20d'],
            'score':          opt['score'],
            'center_date':    opt['test_center_date'],
            'created_at':     opt['created_at'],
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/screening/save_best_params', methods=['POST'])
def screening_save_best_params():
    """手動最適化ボタンで「適用」したときにDBへ保存"""
    try:
        body = request.get_json() or {}
        best_params = {
            'vol_ratio_min':    body.get('vol_ratio_min', 1.5),
            'price_5d_chg_min': body.get('price_5d_chg_min', 0.0),
            'turnover_min':     body.get('turnover_min', 50_000_000),
            'market':           body.get('market', ''),
        }
        win_stats = {
            'win_rate_20d':      body.get('win_rate_20d'),
            'avg_return_20d':    body.get('avg_return_20d'),
            'win_rate_10d':      body.get('win_rate_10d'),
            'avg_return_10d':    body.get('avg_return_10d'),
            'total_combinations': body.get('total_combinations', 0),
        }
        test_center_date = body.get('center_date', datetime.now().strftime('%Y-%m-%d'))
        test_dates       = body.get('test_dates', [])
        save_optimization_result(best_params, win_stats, test_center_date, test_dates)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/screening/optimization_history')
def screening_optimization_history():
    """自動最適化の実行履歴を返す（グラフ表示用）"""
    try:
        history = get_auto_optimization_history(limit=100)
        return jsonify({'success': True, 'history': history})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/screening/run_auto_optimize', methods=['POST'])
def screening_run_auto_optimize():
    """手動で自動最適化を今すぐ実行（cronと同じロジック）"""
    try:
        body         = request.get_json(silent=True) or {}
        lookback     = body.get('lookback', 52)
        n_trials     = body.get('n', 5000)
        dry_run      = body.get('dry_run', False)

        current      = get_latest_optimization()
        current_score    = current['score']        if current else 0.0
        current_win_rate = current['win_rate_20d'] if current else 0.0
        current_params   = current['best_params']  if current else None

        step   = 4 if lookback >= 52 else 2
        result = jquants.run_large_scale_optimization(
            lookback_weeks=lookback,
            step_weeks=step,
            n_trials=n_trials,
            base_params=current_params,
        )

        if not result.get('success'):
            msg = result.get('error', '最適化失敗')
            save_auto_optimization_log(
                improved=False, prev_score=current_score, new_score=current_score,
                prev_win_rate=current_win_rate, new_win_rate=current_win_rate,
                best_params=current_params or {}, lookback_weeks=lookback,
                test_dates=[], note=msg,
            )
            return jsonify({'success': False, 'error': msg})

        best = result.get('best_20d')
        if not best:
            return jsonify({'success': False, 'error': '有効な結果なし'})

        new_win_rate = best.get('win_rate_20d', 0) or 0
        new_avg      = best.get('avg_return_20d', 0) or 0
        new_score    = new_win_rate * 2 + new_avg
        improved     = new_score > current_score

        if improved and not dry_run:
            new_params = {
                'vol_ratio_min':    best['vol_ratio_min'],
                'price_5d_chg_min': best['price_5d_chg_min'],
                'turnover_min':     best.get('min_turnover', best.get('turnover_min', 50_000_000)),
                'market':           best.get('market', ''),
                'top_n':            best.get('top_n', 20),
            }
            win_stats = {
                'win_rate_20d':       new_win_rate,
                'avg_return_20d':     new_avg,
                'win_rate_10d':       best.get('win_rate_10d'),
                'avg_return_10d':     best.get('avg_return_10d'),
                'total_combinations': result.get('total_combinations', 0),
            }
            test_dates  = result.get('test_dates', [])
            center_date = test_dates[len(test_dates) // 2] if test_dates else ''
            save_optimization_result(new_params, win_stats, center_date, test_dates)

        if not dry_run:
            save_auto_optimization_log(
                improved=improved,
                prev_score=current_score,
                new_score=new_score if improved else current_score,
                prev_win_rate=current_win_rate,
                new_win_rate=new_win_rate if improved else current_win_rate,
                best_params=best if improved else (current_params or {}),
                lookback_weeks=lookback,
                test_dates=result.get('test_dates', []),
                note='improved' if improved else 'no_change',
            )

        return jsonify({
            'success':         True,
            'improved':        improved,
            'prev_score':      current_score,
            'new_score':       new_score if improved else current_score,
            'prev_win_rate':   current_win_rate,
            'new_win_rate':    new_win_rate,
            'best_params':     best,
            'total_time':      result.get('total_time'),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


# ========== シグナル監視 ==========

@app.route('/signals')
def signals_page():
    """シグナル監視ページ"""
    return render_template('signals.html')


@app.route('/api/signals/list')
def signals_list():
    """現在のシグナル一覧（カテゴリ別 + チャートデータ付き）"""
    try:
        from signal_monitor import get_signal_stocks
        data_dir = os.path.join(_base, '..', 'quant_research', 'data')
        result = get_signal_stocks(data_dir)
        if 'error' in result:
            return jsonify({'success': False, 'error': result['error']})

        # Persist current signals to DB for future disappearance tracking
        all_sigs = result.get('all_signals', [])
        if all_sigs:
            db_records = []
            for s in all_sigs:
                db_records.append({
                    'code_full': s.get('code_full', s.get('code', '')),
                    'name': s.get('name', ''),
                    'sector': s.get('sector', ''),
                    'signal_date': result['latest_date'],
                    'close': s.get('close'),
                    'vol_base_ratio': s.get('vol_base_ratio'),
                    'vol_above_count': s.get('vol_above_count'),
                    'turnover_avg': s.get('turnover_avg'),
                    'rsi': s.get('rsi'),
                    'ma25_dev': s.get('ma25_dev'),
                    'op_growth': s.get('op_growth'),
                    'eps_growth': s.get('eps_growth'),
                    'first_detected': s.get('first_detected', ''),
                })
            save_signal_history(db_records)

        return jsonify({'success': True, **result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/signals/refresh', methods=['POST'])
def signals_refresh():
    """シグナルを再計算して最新データを返す（キャッシュ無視）"""
    try:
        from signal_monitor import get_signal_stocks
        data_dir = os.path.join(_base, '..', 'quant_research', 'data')
        result = get_signal_stocks(data_dir, force=True)
        if 'error' in result:
            return jsonify({'success': False, 'error': result['error']})
        return jsonify({'success': True, **result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/signals/scheduled-refresh', methods=['POST', 'GET'])
def signals_scheduled_refresh():
    """
    Cloud Scheduler から毎朝6時・夕方4時の自動更新用。
    ヘッダ X-Scheduler-Secret が環境変数 SIGNALS_SCHEDULER_SECRET と一致する場合のみ実行。
    """
    expected = os.environ.get('SIGNALS_SCHEDULER_SECRET', '').strip()
    if not expected:
        return jsonify({'success': False, 'error': 'SIGNALS_SCHEDULER_SECRET not set'}), 503
    got = request.headers.get('X-Scheduler-Secret', '').strip()
    if got != expected:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    try:
        from signal_monitor import get_signal_stocks
        data_dir = os.path.join(_base, '..', 'quant_research', 'data')
        result = get_signal_stocks(data_dir, force=True)
        if 'error' in result:
            return jsonify({'success': False, 'error': result['error']}), 500
        return jsonify({'success': True, 'latest_date': result.get('latest_date')})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/signals/optimal-conditions')
def signals_optimal_conditions():
    """深層探索で発見された最適売買条件を返す"""
    try:
        import json as _json
        data_dir = os.path.join(_base, '..', 'quant_research', 'data')
        results_path = os.path.join(data_dir, 'deep_strategy_results.json')
        pkl_path = os.path.join(data_dir, '_results_deep_strategy.pkl')

        for fname in ['deep_strategy_results.json', '_results_deep_strategy.pkl']:
            local = os.path.join(data_dir, fname)
            if not os.path.exists(local):
                try:
                    from google.cloud import storage
                    client = storage.Client()
                    bucket = client.bucket('pts-ranking-data')
                    blob = bucket.blob(f'quant_data/{fname}')
                    if blob.exists():
                        os.makedirs(data_dir, exist_ok=True)
                        blob.download_to_filename(local)
                except Exception:
                    pass

        if not os.path.exists(results_path):
            return jsonify({'success': False, 'error': 'No strategy results found'})
        with open(results_path) as f:
            data = _json.load(f)

        import pickle
        pkl_path = os.path.join(_base, '..', 'quant_research', 'data', '_results_deep_strategy.pkl')
        high_n_strats = []
        if os.path.exists(pkl_path):
            with open(pkl_path, 'rb') as f:
                all_strats = pickle.load(f)
            for min_n, label in [(50, 'reliable'), (30, 'moderate'), (10, 'selective')]:
                bucket = [s for s in all_strats if s['test']['n'] >= min_n]
                bucket.sort(key=lambda x: (x['test']['wr'], x['test']['pf']), reverse=True)
                for s in bucket[:5]:
                    s_copy = dict(s)
                    s_copy['reliability'] = label
                    high_n_strats.append(s_copy)

        return jsonify({
            'success': True,
            'summary': data.get('summary', {}),
            'train_end': data.get('train_end', ''),
            'wr90_plus': data.get('wr90_plus', [])[:10],
            'wr80_90': data.get('wr80_90', [])[:10],
            'high_n_strategies': high_n_strats[:15],
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})


# ========== クオンツ分析 ==========

# .env ファイルを読み込み
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))
except ImportError:
    pass

_quant_jobs: dict = {}  # job_id -> {status, logs, current_step, progress, report, error}

@app.route('/quant')
def quant_page():
    """クオンツ分析ページ"""
    return render_template('quant.html')

@app.route('/api/quant/run', methods=['POST'])
def quant_run():
    """クオンツ分析パイプラインをバックグラウンドで実行"""
    import threading
    import uuid

    body = request.get_json(silent=True) or {}
    step = body.get('step', 'all')
    fast = body.get('fast', True)

    job_id = str(uuid.uuid4())[:8]
    _quant_jobs[job_id] = {
        'status': 'running',
        'logs': [],
        'current_step': None,
        'progress': 0,
        'progress_label': '開始中...',
        'report': None,
        'error': None,
    }

    def _run():
        import logging

        job = _quant_jobs[job_id]

        class JobLogHandler(logging.Handler):
            def emit(self, record):
                msg = record.getMessage()
                log_type = 'info'
                if record.levelno >= logging.ERROR:
                    log_type = 'error'
                elif record.levelno >= logging.WARNING:
                    log_type = 'error'
                elif 'complete' in msg.lower() or '完了' in msg:
                    log_type = 'success'
                elif 'STEP' in msg or '===' in msg:
                    log_type = 'step'
                job['logs'].append({'msg': msg, 'type': log_type})

        logger = logging.getLogger('quant_research')
        logger.setLevel(logging.INFO)
        handler = JobLogHandler()
        logger.addHandler(handler)

        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

            steps_order = ['data', 'features', 'backtest', 'optimize', 'ml', 'regime', 'report']
            if step == 'all':
                target_steps = steps_order
            else:
                idx = steps_order.index(step) if step in steps_order else 0
                target_steps = steps_order[:idx + 1]

            total = len(target_steps)

            # STEP 1: data
            if 'data' in target_steps:
                job['current_step'] = 'data'
                job['progress'] = 0 / total
                job['progress_label'] = 'データ取得中...'

                from quant_research.data_fetcher import fetch_all, prepare_price_dataframe
                from quant_research.config import DATA_YEARS

                raw_data = fetch_all(years=DATA_YEARS)
                df = prepare_price_dataframe(raw_data['prices'], raw_data['master'])

                import pandas as pd
                data_dir = os.path.join(os.path.dirname(__file__), '..', 'quant_research', 'data')
                df.to_pickle(os.path.join(data_dir, '_intermediate_df_prepared.pkl'))
                pd.to_pickle(raw_data, os.path.join(data_dir, '_intermediate_raw_data.pkl'))
                job['logs'].append({'msg': f'データ取得完了: {df["Code"].nunique():,}銘柄, {len(df):,}行', 'type': 'success'})

            # STEP 2: features
            if 'features' in target_steps:
                job['current_step'] = 'features'
                job['progress'] = 1 / total
                job['progress_label'] = '特徴量計算中...'

                import pandas as pd
                data_dir = os.path.join(os.path.dirname(__file__), '..', 'quant_research', 'data')
                df = pd.read_pickle(os.path.join(data_dir, '_intermediate_df_prepared.pkl'))
                raw_data = pd.read_pickle(os.path.join(data_dir, '_intermediate_raw_data.pkl'))

                from quant_research.feature_engine import compute_all_features
                from quant_research.config import FORWARD_PERIODS
                from quant_research.fundamental import compute_fundamental_features

                df = compute_all_features(df, fins=raw_data.get('fins_summary'), forward_periods=FORWARD_PERIODS)

                fins_data = raw_data.get('fins_summary')
                if fins_data is not None and not fins_data.empty:
                    df = compute_fundamental_features(df, fins_data)
                    job['logs'].append({'msg': 'ファンダメンタル特徴量をマージしました', 'type': 'info'})

                df.to_pickle(os.path.join(data_dir, '_intermediate_df_features.pkl'))
                job['logs'].append({'msg': f'特徴量計算完了: {len(df.columns)}列', 'type': 'success'})

            # STEP 3-4: backtest
            if 'backtest' in target_steps:
                job['current_step'] = 'backtest'
                job['progress'] = 2 / total
                job['progress_label'] = 'バックテスト中...'

                import pandas as pd
                data_dir = os.path.join(os.path.dirname(__file__), '..', 'quant_research', 'data')
                df = pd.read_pickle(os.path.join(data_dir, '_intermediate_df_features.pkl'))

                from quant_research.backtester import split_train_test, run_batch_backtest, results_to_dataframe
                from quant_research.screener import generate_random_conditions
                train_df, test_df = split_train_test(df)
                n_conds = 5000 if fast else 50000
                conditions = generate_random_conditions(n=n_conds, seed=42)
                results = run_batch_backtest(train_df, conditions, show_progress=False)

                train_df.to_pickle(os.path.join(data_dir, '_intermediate_train_df.pkl'))
                test_df.to_pickle(os.path.join(data_dir, '_intermediate_test_df.pkl'))
                pd.to_pickle(results, os.path.join(data_dir, '_results_backtest.pkl'))
                job['logs'].append({'msg': f'バックテスト完了: {len(results):,}条件が有効', 'type': 'success'})

            # STEP 5: optimize
            if 'optimize' in target_steps:
                job['current_step'] = 'optimize'
                job['progress'] = 3 / total
                job['progress_label'] = '最適化中...'

                import pandas as pd
                data_dir = os.path.join(os.path.dirname(__file__), '..', 'quant_research', 'data')
                train_df = pd.read_pickle(os.path.join(data_dir, '_intermediate_train_df.pkl'))
                test_df = pd.read_pickle(os.path.join(data_dir, '_intermediate_test_df.pkl'))

                from quant_research.optimizer import run_full_optimization
                from quant_research.backtester import evaluate_out_of_sample
                opt_results = run_full_optimization(
                    train_df,
                    random_trials=5000 if fast else 50000,
                    bayesian_trials=200 if fast else 2000,
                    ga_pop=50 if fast else 200,
                    ga_gen=20 if fast else 100,
                    show_progress=False,
                )
                oos = evaluate_out_of_sample(opt_results['all'], test_df, top_n=30)

                pd.to_pickle(opt_results, os.path.join(data_dir, '_results_optimization_results.pkl'))
                pd.to_pickle(oos, os.path.join(data_dir, '_results_oos_results.pkl'))
                job['logs'].append({'msg': f'最適化完了: {len(opt_results["all"]):,}条件', 'type': 'success'})

            # STEP 6: ml
            if 'ml' in target_steps:
                job['current_step'] = 'ml'
                job['progress'] = 4 / total
                job['progress_label'] = '機械学習モデル訓練中...'

                import pandas as pd
                data_dir = os.path.join(os.path.dirname(__file__), '..', 'quant_research', 'data')
                df = pd.read_pickle(os.path.join(data_dir, '_intermediate_df_features.pkl'))

                from quant_research.ml_models import run_walk_forward_cv
                ml_results = run_walk_forward_cv(df, optimize=(not fast))
                pd.to_pickle(ml_results, os.path.join(data_dir, '_results_ml_results.pkl'))

                for name, res in ml_results.items():
                    avg = res.get('metrics_avg', {})
                    job['logs'].append({'msg': f'{name}: AUC={avg.get("roc_auc", 0):.4f}', 'type': 'success'})

            # STEP 7: regime
            if 'regime' in target_steps:
                job['current_step'] = 'regime'
                job['progress'] = 5 / total
                job['progress_label'] = 'レジーム分析中...'

                import pandas as pd
                data_dir = os.path.join(os.path.dirname(__file__), '..', 'quant_research', 'data')
                df = pd.read_pickle(os.path.join(data_dir, '_intermediate_df_features.pkl'))
                raw_data = pd.read_pickle(os.path.join(data_dir, '_intermediate_raw_data.pkl'))

                from quant_research.regime_analyzer import classify_regime, merge_regime, backtest_by_regime, regime_performance_summary, get_current_regime

                index_df = raw_data.get('topix')
                if index_df is None or (hasattr(index_df, 'empty') and index_df.empty):
                    index_df = raw_data.get('nikkei')

                current_regime = 'unknown'
                regime_summary = pd.DataFrame()
                regime_bt = {}

                if index_df is not None and not index_df.empty:
                    regime_df = classify_regime(index_df)
                    current_regime = get_current_regime(index_df)

                    opt_results = pd.read_pickle(os.path.join(data_dir, '_results_optimization_results.pkl'))
                    top_conditions = [r.condition for r in opt_results.get('all', [])[:20]]
                    if top_conditions:
                        df_regime = merge_regime(df, regime_df)
                        regime_bt = backtest_by_regime(df_regime, top_conditions)
                        regime_summary = regime_performance_summary(regime_bt)

                pd.to_pickle(regime_bt, os.path.join(data_dir, '_results_regime_results.pkl'))
                regime_summary.to_pickle(os.path.join(data_dir, '_intermediate_regime_summary.pkl'))
                pd.to_pickle(current_regime, os.path.join(data_dir, '_results_current_regime.pkl'))

                job['logs'].append({'msg': f'現在の市場レジーム: {current_regime}', 'type': 'success'})

            # STEP 8: report
            if 'report' in target_steps:
                job['current_step'] = 'report'
                job['progress'] = 6 / total
                job['progress_label'] = 'レポート生成中...'

                import pandas as pd
                data_dir = os.path.join(os.path.dirname(__file__), '..', 'quant_research', 'data')
                df = pd.read_pickle(os.path.join(data_dir, '_intermediate_df_features.pkl'))
                opt_results = pd.read_pickle(os.path.join(data_dir, '_results_optimization_results.pkl'))

                ml_results = None
                try: ml_results = pd.read_pickle(os.path.join(data_dir, '_results_ml_results.pkl'))
                except FileNotFoundError: pass

                regime_results = None
                try: regime_results = pd.read_pickle(os.path.join(data_dir, '_results_regime_results.pkl'))
                except FileNotFoundError: pass

                regime_summary = pd.DataFrame()
                try: regime_summary = pd.read_pickle(os.path.join(data_dir, '_intermediate_regime_summary.pkl'))
                except FileNotFoundError: pass

                current_regime = 'unknown'
                try: current_regime = pd.read_pickle(os.path.join(data_dir, '_results_current_regime.pkl'))
                except FileNotFoundError: pass

                from quant_research.reporter import (
                    generate_final_report,
                    plot_equity_curves, plot_optimization_landscape,
                    plot_feature_importance, plot_regime_performance,
                    plot_holding_period_comparison, plot_theme_performance,
                )
                from quant_research.theme_analyzer import (
                    classify_themes, analyze_theme_performance,
                    find_tenbaggers, detect_institutional_accumulation,
                    get_tenbagger_common_features,
                )

                theme_performance = pd.DataFrame()
                tenbagger_analysis = {}
                institutional_accum = {}
                theme_map = {}

                raw_data2 = pd.read_pickle(os.path.join(data_dir, '_intermediate_raw_data.pkl'))
                master_data = raw_data2.get('master')
                if master_data is not None and not master_data.empty:
                    theme_map = classify_themes(master_data)
                    theme_performance = analyze_theme_performance(df, theme_map)
                    job['logs'].append({'msg': f'テーマ分類完了: {len(theme_map)}銘柄', 'type': 'info'})

                tenbaggers_df = find_tenbaggers(df, min_multiple=2.0)
                tenbagger_analysis = get_tenbagger_common_features(tenbaggers_df, theme_map)

                accum_mask = detect_institutional_accumulation(df)
                n_accum = int(accum_mask.sum())
                institutional_accum = {
                    'total_signals': n_accum,
                    'unique_stocks': int(df.loc[accum_mask, 'Code'].nunique()) if n_accum > 0 else 0,
                }
                if n_accum > 0:
                    latest_date = df['Date'].max()
                    latest_accum = df.loc[accum_mask & (df['Date'] == latest_date)]
                    institutional_accum['current_candidates'] = (
                        latest_accum[['Code', 'Close', 'vol_ratio']].to_dict('records')
                        if not latest_accum.empty else []
                    )
                    job['logs'].append({'msg': f'機関仕込みシグナル: {n_accum}件検出', 'type': 'info'})

                report = generate_final_report(
                    optimization_results=opt_results or {},
                    ml_results=ml_results or {},
                    regime_results=regime_results or {},
                    regime_summary=regime_summary,
                    df=df,
                    current_regime=current_regime or 'unknown',
                    theme_performance=theme_performance,
                    tenbagger_analysis=tenbagger_analysis,
                    institutional_accumulation=institutional_accum,
                )

                report_dir = os.path.join(data_dir, 'reports')
                os.makedirs(report_dir, exist_ok=True)

                charts = []
                if opt_results and 'all' in opt_results and opt_results['all']:
                    top3 = opt_results['all'][:3]
                    plot_equity_curves(top3, labels=['Best WR', 'Best Return', 'Best Stable'],
                                       save_path=os.path.join(report_dir, 'equity_curves.png'))
                    charts.append('equity_curves.png')
                    plot_optimization_landscape(opt_results['all'][:500],
                                                save_path=os.path.join(report_dir, 'optimization_landscape.png'))
                    charts.append('optimization_landscape.png')

                if ml_results:
                    plot_feature_importance(ml_results, save_path=os.path.join(report_dir, 'feature_importance.png'))
                    charts.append('feature_importance.png')

                if regime_summary is not None and not regime_summary.empty:
                    plot_regime_performance(regime_summary, save_path=os.path.join(report_dir, 'regime_performance.png'))
                    charts.append('regime_performance.png')

                holding_comp = report.get('holding_period_comparison', [])
                if holding_comp:
                    plot_holding_period_comparison(holding_comp,
                                                   save_path=os.path.join(report_dir, 'holding_period_comparison.png'))
                    charts.append('holding_period_comparison.png')

                if not theme_performance.empty:
                    plot_theme_performance(theme_performance,
                                           save_path=os.path.join(report_dir, 'theme_performance.png'))
                    charts.append('theme_performance.png')

                report['charts'] = charts

                # Historical validation
                if opt_results and 'all' in opt_results and opt_results['all']:
                    from quant_research.historical_validator import run_full_historical_validation
                    job['logs'].append({'msg': '過去時点スクリーニング検証を実行中...', 'type': 'info'})
                    best_cond = opt_results['all'][0].condition
                    try:
                        hist_validation = run_full_historical_validation(
                            df, best_cond,
                            months_back=[3, 6, 12],
                            forward_days=[20, 60, 120],
                        )
                        report['historical_validation'] = hist_validation.get('summary', {})
                        report['historical_details'] = {
                            'win_analysis': hist_validation.get('win_analysis', {}),
                            'winners_vs_losers': hist_validation.get('winners_vs_losers', {}),
                            'examples': hist_validation.get('examples', {}),
                            'hit_stats': hist_validation.get('hit_stats', {}),
                        }
                        pd.to_pickle(hist_validation, os.path.join(data_dir, '_results_historical_validation.pkl'))

                        summary = hist_validation.get('summary', {})
                        wr = summary.get('actual_win_rate', 0)
                        avg_ret = summary.get('average_return', 0)
                        best_pd = summary.get('best_holding_period', '?')
                        job['logs'].append({
                            'msg': f'過去検証完了: 勝率{wr:.1%}, 平均リターン{avg_ret:.2%}, 最良期間={best_pd}',
                            'type': 'success'
                        })
                    except Exception as val_e:
                        job['logs'].append({'msg': f'過去検証でエラー: {val_e}', 'type': 'error'})

                from quant_research.reporter import _sanitize_for_json
                job['report'] = _sanitize_for_json(report)
                job['logs'].append({'msg': f'レポート生成完了 — シグナル銘柄: {len(report.get("current_signals", []))}件', 'type': 'success'})

            job['status'] = 'done'
            job['progress'] = 1.0
            job['progress_label'] = '完了'

        except Exception as e:
            import traceback
            traceback.print_exc()
            job['status'] = 'error'
            job['error'] = str(e)
            job['logs'].append({'msg': f'ERROR: {e}', 'type': 'error'})
        finally:
            logger.removeHandler(handler)

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({'success': True, 'job_id': job_id})


@app.route('/api/quant/status/<job_id>')
def quant_status(job_id):
    """ジョブの進捗・結果を返す"""
    job = _quant_jobs.get(job_id)
    if not job:
        return jsonify({'status': 'not_found', 'error': 'Job not found'})
    return jsonify({
        'status': job['status'],
        'logs': job['logs'],
        'current_step': job['current_step'],
        'progress': job['progress'],
        'progress_label': job['progress_label'],
        'report': job['report'],
        'error': job['error'],
    })


@app.route('/api/quant/chart/<filename>')
def quant_chart(filename):
    """生成されたチャート画像を返す"""
    from flask import send_from_directory
    report_dir = os.path.join(os.path.dirname(__file__), '..', 'quant_research', 'data', 'reports')
    return send_from_directory(report_dir, filename)


if __name__ == '__main__':
    if ANTHROPIC_API_KEY:
        print("✅ Claude API Key: 設定済み")
    else:
        print("⚠️  Claude API Key: 未設定（環境変数 ANTHROPIC_API_KEY を設定してください）")

    jquants_key = os.getenv('JQUANTS_API_KEY', '')
    if jquants_key:
        print("✅ J-Quants API Key: 設定済み")
    else:
        print("⚠️  J-Quants API Key: 未設定")

    print("=" * 60)
    print("🚀 PTSランキング ダッシュボード 起動中...")
    print("=" * 60)
    print("\n📊 Dashboard URL: http://localhost:5001")
    print("🧪 クオンツ分析: http://localhost:5001/quant")
    print("💡 Press Ctrl+C to stop\n")

    app.run(debug=True, host='0.0.0.0', port=5001)
