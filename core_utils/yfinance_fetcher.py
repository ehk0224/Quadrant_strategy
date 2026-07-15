#yfinance_fetcher.py
import pandas as pd
import yfinance as yf
import os
from datetime import datetime, timedelta

class YfinanceFetcher:
    def __init__(self, cache_dir="data_cache"):
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)

    def get_cache_path(self, ticker, start=None, end=None, period=None, use_parquet=True):
        '''
        Generate a cache file path based on the ticker and date range.
        '''
        if isinstance(ticker, list):
            ticker_str = "_".join(ticker)[:50]
        else:
            ticker_str = str(ticker)
            
        ticker_clean = ticker_str.upper().replace("^", "").replace("/", "_").replace(" ", "")
        
        if start and end:
            key = f"{ticker_clean}_{start}_{end}"
        elif start:
            key = f"{ticker_clean}_{start}_latest"
        else:
            key = f"{ticker_clean}_{period or '3y'}"
        
        ext = ".parquet" if use_parquet else ".csv"
        return os.path.join(self.cache_dir, f"{key}{ext}")
    
    def check_cache(self, ticker, start=None, end=None, period=None, max_age_days=1):
        '''
        Check if the cache file exists and is not older than max_age_days.
        '''
        cache_path = self.get_cache_path(ticker, start=start, end=end, period=period)
        
        if not os.path.exists(cache_path):
            return False
            
        file_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
        return datetime.now() - file_time < timedelta(days=max_age_days)

    def fetch(self, ticker, start=None, end=None, period=None, 
              use_cache=True, use_parquet=True):
        '''
        1. Check if cached data exists and is valid. If so, load from cache.
        2. If not, fetch data from yfinance, clean it, and save to cache.
        '''
        cache_path = self.get_cache_path(ticker, start, end, period, use_parquet)

        if use_cache and self.check_cache(ticker, start, end, period, use_parquet):
            try:
                if use_parquet:
                    df = pd.read_parquet(cache_path)
                else:
                    df = pd.read_csv(cache_path)
                    if 'date' in df.columns:
                        df['date'] = pd.to_datetime(df['date'])
                #print(f"✅ 從快取讀取: {cache_path}")
                return df
            except Exception as e:
                print(f"⚠️ 快取讀取失敗，將重新下載: {e}")

        # Download data from yfinance
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

        df = yf.download(**params)
        
        if df.empty:
            print(f"警告: 找不到 {ticker} 的資料")
            return pd.DataFrame()

        # 處理 MultiIndex 
        if isinstance(df.columns, pd.MultiIndex):
            
            df = df.stack(level=1, future_stack=True)   # 使用 stack 將 Ticker 維度（通常在 level 1）轉移到索引列
            if len(df.index.names) == 2:    #將索引名稱設為 Date 與 Ticker (確保 reset 後欄位名稱正確)
                df.index.names = ['Date', 'Ticker']
            df = df.reset_index()   #重設索引，把 Date 和 Ticker 變成一般的 DataFrame 欄位
        else:
            df = df.reset_index()

        df.columns.name = None
        df.columns = [str(col).lower().replace(" ", "_") for col in df.columns]
        
        rename_dict = {
            "adj_close": "adj_price"
        }
        df = df.rename(columns=rename_dict)

        #確保adj_price欄位存在，若不存在則嘗試從 close 或其他欄位推斷
        if 'adj_price' not in df.columns and 'close' in df.columns:
            df['adj_price'] = df['close']

        df['adj_price'] = df['adj_price'].replace(0, pd.NA)  # 將價格為 0 的資料視為缺失值，避免後續計算錯誤
        
        cols_to_numeric = ['open', 'high', 'low', 'close', 'adj_price', 'volume']
        for col in cols_to_numeric:
            if col in df.columns:
                # errors='coerce' 會將無法轉換的亂碼或字串強制轉為 NaN
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df['date'] = pd.to_datetime(df['date'])

        df['adj_price'] = df['adj_price'].ffill().bfill()
        if 'volume' in df.columns:
            df['volume'] = df['volume'].fillna(0)

        self.save_to_cache(df, cache_path, use_parquet)

        return df
    
    def save_to_cache(self, df, cache_path, use_parquet=True):
        '''
        Save the DataFrame to cache in either Parquet or CSV format.
        '''
        try:
            if use_parquet:
                # 儲存為 Parquet，不保留 DataFrame 的預設整數 Index
                df.to_parquet(cache_path, index=False)
            else:
                df.to_csv(cache_path, encoding='utf-8-sig', index=False)
            #print(f"✅ 已儲存快取: {cache_path}")
        except Exception as e:
            print(f"⚠️ 儲存快取失敗: {e}")

if __name__ == "__main__":
    fetcher = YfinanceFetcher()
    df = fetcher.fetch(ticker="AAPL", period="1y", use_cache=True, use_parquet=True)
    cache_path = fetcher.get_cache_path(ticker="AAPL", period="1y")
    print(df.head())
    print(cache_path)