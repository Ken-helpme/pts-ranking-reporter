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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create index for faster queries
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_stock_code ON pts_ranking(stock_code)
    ''')

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_created_at ON pts_ranking(created_at)
    ''')

    conn.commit()
    conn.close()

def save_pts_data(stock: Dict, news: List[Dict], company: Dict):
    """PTSデータを保存"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO pts_ranking
        (stock_code, stock_name, pts_price, change_rate, change_amount,
         volume, market, company_info, news, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        datetime.now().isoformat()
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

    # Get all stocks from that timestamp
    cursor.execute('''
        SELECT stock_code, stock_name, pts_price, change_rate, change_amount,
               volume, market, company_info, news, created_at
        FROM pts_ranking
        WHERE created_at = ?
        ORDER BY change_rate DESC
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
            'timestamp': row[9]
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
                   volume, market, company_info, news, created_at
            FROM pts_ranking
            WHERE stock_code = ? AND created_at >= ?
            ORDER BY created_at DESC
        ''', (stock_code, start_date))
    else:
        cursor.execute('''
            SELECT stock_code, stock_name, pts_price, change_rate, change_amount,
                   volume, market, company_info, news, created_at
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
            'timestamp': row[9]
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
