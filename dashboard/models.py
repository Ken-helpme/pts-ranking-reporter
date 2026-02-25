"""
Database models for PTS Ranking Dashboard
"""
import sqlite3
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'pts_data.db')

def init_db():
    """データベースを初期化"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # PTS ranking table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pts_ranking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            pts_price REAL,
            change_rate REAL,
            change_amount REAL,
            volume INTEGER,
            market TEXT,
            company_info TEXT,
            news TEXT,
            main_reason TEXT,
            analysis TEXT,
            future_potential TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Add new columns if they don't exist (for existing databases)
    try:
        cursor.execute('ALTER TABLE pts_ranking ADD COLUMN main_reason TEXT')
    except:
        pass  # Column already exists

    try:
        cursor.execute('ALTER TABLE pts_ranking ADD COLUMN analysis TEXT')
    except:
        pass

    try:
        cursor.execute('ALTER TABLE pts_ranking ADD COLUMN future_potential TEXT')
    except:
        pass

    # Create index for faster queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_stock_code ON pts_ranking(stock_code)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_created_at ON pts_ranking(created_at)
    ''')

    # Trending stocks table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trending_stocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            stock_name TEXT NOT NULL,
            price REAL,
            change_rate REAL,
            change_amount REAL,
            price_high REAL,
            price_low REAL,
            price_open REAL,
            volume TEXT,
            market TEXT,
            market_cap TEXT,
            per REAL,
            pbr REAL,
            synopsis TEXT,
            source_url TEXT,
            chart_data TEXT,
            fetch_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_trending_fetch_date ON trending_stocks(fetch_date)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_trending_code ON trending_stocks(stock_code)
    ''')

    conn.commit()
    conn.close()

def save_trending_stocks(stocks: List[Dict], fetch_date: str = None):
    """話題株データを保存"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if fetch_date is None:
        fetch_date = datetime.now().strftime('%Y-%m-%d')

    # 同じ日付の既存データを削除（更新扱い）
    cursor.execute('DELETE FROM trending_stocks WHERE fetch_date = ?', (fetch_date,))

    for stock in stocks:
        chart_json = json.dumps(stock.get('chart_data', []), ensure_ascii=False)
        cursor.execute('''
            INSERT INTO trending_stocks
            (stock_code, stock_name, price, change_rate, change_amount,
             price_high, price_low, price_open, volume, market, market_cap,
             per, pbr, synopsis, source_url, chart_data, fetch_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            stock['code'],
            stock['name'],
            stock.get('price'),
            stock.get('change_rate'),
            stock.get('change_amount'),
            stock.get('price_high'),
            stock.get('price_low'),
            stock.get('price_open'),
            stock.get('volume', ''),
            stock.get('market', ''),
            stock.get('market_cap', ''),
            stock.get('per'),
            stock.get('pbr'),
            stock.get('synopsis', ''),
            stock.get('source_url', ''),
            chart_json,
            fetch_date
        ))

    conn.commit()
    conn.close()

def get_trending_stocks(date: Optional[str] = None) -> List[Dict]:
    """話題株データを取得"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if date:
        cursor.execute('''
            SELECT stock_code, stock_name, price, change_rate, change_amount,
                   price_high, price_low, price_open, volume, market, market_cap,
                   per, pbr, synopsis, source_url, chart_data, fetch_date, created_at
            FROM trending_stocks
            WHERE fetch_date = ?
            ORDER BY id ASC
        ''', (date,))
    else:
        # 最新日付のデータを取得
        cursor.execute('SELECT MAX(fetch_date) FROM trending_stocks')
        latest_date = cursor.fetchone()[0]
        if not latest_date:
            conn.close()
            return []
        cursor.execute('''
            SELECT stock_code, stock_name, price, change_rate, change_amount,
                   price_high, price_low, price_open, volume, market, market_cap,
                   per, pbr, synopsis, source_url, chart_data, fetch_date, created_at
            FROM trending_stocks
            WHERE fetch_date = ?
            ORDER BY id ASC
        ''', (latest_date,))

    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            'code': row[0],
            'name': row[1],
            'price': row[2],
            'change_rate': row[3],
            'change_amount': row[4],
            'price_high': row[5],
            'price_low': row[6],
            'price_open': row[7],
            'volume': row[8] or '',
            'market': row[9] or '',
            'market_cap': row[10] or '',
            'per': row[11],
            'pbr': row[12],
            'synopsis': row[13] or '',
            'source_url': row[14] or '',
            'chart_data': json.loads(row[15]) if row[15] else [],
            'fetch_date': row[16],
            'timestamp': row[17],
        })

    return result

def get_trending_dates() -> List[str]:
    """話題株データがある日付リストを取得"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT fetch_date FROM trending_stocks ORDER BY fetch_date DESC LIMIT 30')
    dates = [row[0] for row in cursor.fetchall()]
    conn.close()
    return dates

def save_pts_data(stock: Dict, news: List[Dict], company: Dict, timestamp: str = None,
                 analysis: Dict = None):
    """PTSデータを保存"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if timestamp is None:
        timestamp = datetime.now().isoformat()

    # 分析データを取得
    main_reason = analysis.get('main_reason', '') if analysis else ''
    future_potential = analysis.get('future_potential', '') if analysis else ''
    analysis_json = json.dumps(analysis, ensure_ascii=False) if analysis else '{}'

    cursor.execute('''
        INSERT INTO pts_ranking
        (stock_code, stock_name, pts_price, change_rate, change_amount,
         volume, market, company_info, news, main_reason, analysis, future_potential, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        stock['code'],
        stock['name'],
        stock.get('pts_price'),
        stock.get('change_rate'),
        stock.get('change_amount'),
        stock.get('volume'),
        stock.get('market', ''),
        json.dumps(company, ensure_ascii=False),
        json.dumps(news, ensure_ascii=False),
        main_reason,
        analysis_json,
        future_potential,
        timestamp
    ))

    conn.commit()
    conn.close()

def get_latest_ranking(limit: int = 20) -> List[Dict]:
    """最新のPTSランキングを取得"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get the latest timestamp
    cursor.execute('SELECT MAX(created_at) FROM pts_ranking')
    latest_time = cursor.fetchone()[0]

    if not latest_time:
        conn.close()
        return []

    # Get all stocks from the latest batch (within 1 second window)
    cursor.execute('''
        SELECT stock_code, stock_name, pts_price, change_rate, change_amount,
               volume, market, company_info, news, main_reason, analysis, future_potential, created_at
        FROM pts_ranking
        WHERE datetime(created_at) >= datetime(?, '-1 second')
        ORDER BY change_rate DESC, created_at DESC
        LIMIT ?
    ''', (latest_time, limit))

    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            'code': row[0],
            'name': row[1],
            'pts_price': row[2],
            'change_rate': row[3],
            'change_amount': row[4],
            'volume': row[5],
            'market': row[6],
            'company_info': json.loads(row[7]) if row[7] else {},
            'news': json.loads(row[8]) if row[8] else [],
            'main_reason': row[9] or '',
            'analysis': json.loads(row[10]) if row[10] else {},
            'future_potential': row[11] or '',
            'timestamp': row[12]
        })

    return result

def get_historical_data(days: int = 7, stock_code: Optional[str] = None) -> List[Dict]:
    """過去N日分のデータを取得"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    start_date = (datetime.now() - timedelta(days=days)).isoformat()

    if stock_code:
        cursor.execute('''
            SELECT stock_code, stock_name, pts_price, change_rate, change_amount,
                   volume, market, company_info, news, main_reason, analysis, future_potential, created_at
            FROM pts_ranking
            WHERE stock_code = ? AND created_at >= ?
            ORDER BY created_at DESC
        ''', (stock_code, start_date))
    else:
        cursor.execute('''
            SELECT stock_code, stock_name, pts_price, change_rate, change_amount,
                   volume, market, company_info, news, main_reason, analysis, future_potential, created_at
            FROM pts_ranking
            WHERE created_at >= ?
            ORDER BY created_at DESC, change_rate DESC
        ''', (start_date,))

    rows = cursor.fetchall()
    conn.close()

    result = []
    for row in rows:
        result.append({
            'code': row[0],
            'name': row[1],
            'pts_price': row[2],
            'change_rate': row[3],
            'change_amount': row[4],
            'volume': row[5],
            'market': row[6],
            'company_info': json.loads(row[7]) if row[7] else {},
            'news': json.loads(row[8]) if row[8] else [],
            'main_reason': row[9] or '',
            'analysis': json.loads(row[10]) if row[10] else {},
            'future_potential': row[11] or '',
            'timestamp': row[12]
        })

    return result

def get_statistics() -> Dict:
    """統計情報を取得"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get latest data stats
    cursor.execute('SELECT MAX(created_at) FROM pts_ranking')
    latest_time = cursor.fetchone()[0]

    if not latest_time:
        conn.close()
        return {
            'total_stocks': 0,
            'avg_change_rate': 0,
            'max_change_rate': 0,
            'min_change_rate': 0,
            'total_volume': 0,
            'last_updated': None
        }

    cursor.execute('''
        SELECT
            COUNT(*) as total,
            AVG(change_rate) as avg_change,
            MAX(change_rate) as max_change,
            MIN(change_rate) as min_change,
            SUM(volume) as total_volume
        FROM pts_ranking
        WHERE created_at = ?
    ''', (latest_time,))

    row = cursor.fetchone()

    # Get historical count
    cursor.execute('SELECT COUNT(DISTINCT created_at) FROM pts_ranking')
    total_snapshots = cursor.fetchone()[0]

    conn.close()

    return {
        'total_stocks': row[0] or 0,
        'avg_change_rate': round(row[1] or 0, 2),
        'max_change_rate': round(row[2] or 0, 2),
        'min_change_rate': round(row[3] or 0, 2),
        'total_volume': int(row[4] or 0),
        'last_updated': latest_time,
        'total_snapshots': total_snapshots
    }

if __name__ == '__main__':
    # Test database
    init_db()
    print("✅ Database initialized successfully")
