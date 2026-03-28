#Finmind_fetcher.py
import pandas as pd
from FinMind.data import DataLoader

class Finmind_fetcher:
    def __init__(self, api_key=None):
        self.api = DataLoader()
        if api_key:
            self.api.login(api_key)

    def fetch(self, ticker, start=None, end=None):
        # 1. 確保日期格式為字串
        start_date = pd.to_datetime(start).strftime('%Y-%m-%d') if start else "2020-01-01"
        end_date = pd.to_datetime(end).strftime('%Y-%m-%d') if end else None

        # 2. 抓取資料
        df = self.api.taiwan_stock_daily(
            stock_id=ticker,
            start_date=start,
            end_date=end
        )

        if df.empty:
            return pd.DataFrame()

        # 3. 清洗欄位名稱：移除空格、統一轉小寫
        df.columns = df.columns.str.strip().str.lower()

        # 4. 重新命名以對齊 Yfinance 的習慣
        rename_dict = {
            'stock_id': 'ticker',
            'max': 'high',
            'min': 'low',
            'trading_volume': 'volume',
            'trading_money': 'amount',
            'trading_turnover': 'turnover'
        }
        df = df.rename(columns=rename_dict)

        # 5. 確保資料型別正確（FinMind 有時會回傳 Object）
        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'amount']
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors='coerce')
        
        # 確保日期是 datetime 格式並放在欄位中 (不當 index)
        df['date'] = pd.to_datetime(df['date'])

        return df