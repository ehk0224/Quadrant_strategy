#yfinance_fetcher.py
import pandas as pd
import yfinance as yf

class Yfinance_fetcher:
    def __init__(self, api_key=None):
        self.api_key = api_key

    def fetch(self, ticker, start=None, end=None, period=None):
        # 1. 抓取參數：如果有 start 就不用 period
        params = {
            "tickers": ticker,
            "auto_adjust": False,
            "progress": False # 關閉進度條讓 console 乾淨點
        }
        
        if start:
            params["start"] = start
            params["end"] = end
        else:
            params["period"] = period or "3y"

        # 2. 執行抓取 (只抓這一次)
        df = yf.download(**params)

        # 3. 檢查是否抓到資料
        if df.empty:
            print(f"警告: 找不到 {ticker} 的資料")
            return pd.DataFrame()

        # 4. 處理 MultiIndex 
        if isinstance(df.columns, pd.MultiIndex):
            # 使用 stack 將 Ticker 維度（通常在 level 1）轉移到索引列
            # 這樣每一行資料就會對應到一個日期 + 一個股票代號
            df = df.stack(level=1, future_stack=True)

        #將索引名稱設為 Date 與 Ticker (確保 reset 後欄位名稱正確)
        df.index.names = ['Date', 'Ticker']
        #重設索引，把 Date 和 Ticker 變成一般的 DataFrame 欄位
        df = df.reset_index()
        #清除欄位結構的名稱（美化輸出的選配動作）
        df.columns.name = None
            
        # 5. 統一清洗資料格式
        df = df.reset_index()
        df.columns = [col.lower().replace(" ", "_") for col in df.columns]
        
        rename_dict = {
            "adj_close": "adj_price"
        }
        df = df.rename(columns=rename_dict)
        
        df['date'] = pd.to_datetime(df['date'])     # 確保 date 欄位是 datetime 格式

        return df