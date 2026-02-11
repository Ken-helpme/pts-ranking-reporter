"""
AWS Lambda用ハンドラー
"""
import sys
import os

# srcディレクトリをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from main import PTSReporter


def lambda_handler(event, context):
    """
    AWS Lambda ハンドラー関数

    Args:
        event: Lambdaイベントデータ
        context: Lambdaコンテキスト

    Returns:
        dict: レスポンスデータ
    """
    # 環境変数から設定を取得
    min_volume = int(os.getenv('MIN_VOLUME', '10000'))
    top_n = int(os.getenv('TOP_N', '10'))

    try:
        # レポーターを実行
        reporter = PTSReporter(min_volume=min_volume, top_n=top_n)
        success = reporter.run()

        return {
            'statusCode': 200 if success else 500,
            'body': {
                'message': 'PTS report sent successfully' if success else 'Failed to send report',
                'success': success
            }
        }

    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': {
                'message': f'Error: {str(e)}',
                'success': False
            }
        }
