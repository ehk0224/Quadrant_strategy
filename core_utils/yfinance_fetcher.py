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
    

    def check_cache(self, ticker, start=None, end=None, period=None, max_age_days=1, use_parquet=True):
        '''
        Check if the cache file exists and is not older than max_age_days.
        '''
        
        cache_path = self.get_cache_path(
            ticker, 
            start=start, 
            end=end, 
            period=period, 
            use_parquet=use_parquet
            )
        
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

        if use_cache and self.check_cache(ticker, start, end, period, use_parquet=use_parquet):
            try:
                if use_parquet:
                    df = pd.read_parquet(cache_path)
                else:
                    df = pd.read_csv(cache_path, index_col=0, parse_dates=True, header=[0, 1])
                    df.columns.names = ['feature', 'ticker']  # 確保層級命名正確
                return df
            except Exception as e:
                print(f"⚠️ 快取讀取失敗，將重新下載: {e}")

        # Download data from yfinance
        params = {
            "tickers": ticker,
            "auto_adjust": False,
            "progress": False
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

        df.index = pd.to_datetime(df.index)
        df.index.name = 'date'

        if isinstance(df.columns, pd.MultiIndex):
            new_cols = []
            for col in df.columns:
                feat = str(col[0]).lower().replace(" ", "_")
                if feat == "adj_close":
                    feat = "adj_price"
                new_cols.append((feat, str(col[1])))
            
            df.columns = pd.MultiIndex.from_tuples(new_cols, names=['feature', 'ticker'])
            
            if 'adj_price' not in df.columns.get_level_values('feature') and 'close' in df.columns.get_level_values('feature'):
                close_df = df['close'].copy()
                close_df.columns = pd.MultiIndex.from_product([['adj_price'], close_df.columns], names=['feature', 'ticker'])
                df = pd.concat([df, close_df], axis=1)
            
            df = df.apply(pd.to_numeric, errors='coerce')
            
            if 'adj_price' in df.columns.get_level_values('feature'):
                df['adj_price'] = df['adj_price'].replace(0, pd.NA).ffill(axis=0).bfill(axis=0)
            if 'volume' in df.columns.get_level_values('feature'):
                df['volume'] = df['volume'].fillna(0)
                
        else:
            # 兼容處理：當輸入單一標的且 yfinance 回傳單一層級欄位時
            df.columns = [str(col).lower().replace(" ", "_") for col in df.columns]
            df = df.rename(columns={"adj_close": "adj_price"})

            if 'adj_price' not in df.columns and 'close' in df.columns:
                df['adj_price'] = df['close']

            cols_to_numeric = ['open', 'high', 'low', 'close', 'adj_price', 'volume']
            for col in cols_to_numeric:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            if 'adj_price' in df.columns:
                df['adj_price'] = df['adj_price'].replace(0, pd.NA).ffill().bfill()
            if 'volume' in df.columns:
                df['volume'] = df['volume'].fillna(0)

            t_name = ticker[0] if isinstance(ticker, (list, tuple, set)) else str(ticker)
            df.columns = pd.MultiIndex.from_product([df.columns, [t_name]], names=['feature', 'ticker'])

        self.save_to_cache(df, cache_path, use_parquet)

        return df
    

    def save_to_cache(self, df, cache_path, use_parquet=True):
        '''
        Save the DataFrame to cache in either Parquet or CSV format.
        '''
        try:
            if use_parquet:
                df.to_parquet(cache_path, index=True)
            else:
                df.to_csv(cache_path, encoding='utf-8-sig', index=True)

        except Exception as e:
            print(f"⚠️ 儲存快取失敗: {e}")


if __name__ == "__main__":
    fetcher = YfinanceFetcher()
    df = fetcher.fetch(ticker=("AAPL", "TSLA"), period="1y", use_cache=True, use_parquet=True)
    cache_path = fetcher.get_cache_path(ticker="AAPL", period="1y")
    print(df.head())
    print(cache_path)