#yfinance_fetcher.py
import pandas as pd
import yfinance as yf

class YfinanceFetcher:
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
            if len(df.index.names) == 2:
                df.index.names = ['Date', 'Ticker']
            #重設索引，把 Date 和 Ticker 變成一般的 DataFrame 欄位
            df = df.reset_index()
        else:
            df = df.reset_index()

        #清除欄位結構的名稱（美化輸出的選配動作）
        df.columns.name = None
            
        # 5. 統一清洗資料格式
        df.columns = [str(col).lower().replace(" ", "_") for col in df.columns]
        
        rename_dict = {
            "adj_close": "adj_price"
        }
        df = df.rename(columns=rename_dict)

        #確保adj_price欄位存在，若不存在則嘗試從 close 或其他欄位推斷
        if 'adj_price' not in df.columns and 'close' in df.columns:
            df['adj_price'] = df['close']

        df['adj_price'] = df['adj_price'].replace(0, pd.NA)  # 將價格為 0 的資料視為缺失值，避免後續計算錯誤
        
        #強制轉換數值型態，如果有非數值的資料會被轉成 NaN
        cols_to_numeric = ['open', 'high', 'low', 'close', 'adj_price', 'volume']
        for col in cols_to_numeric:
            if col in df.columns:
                # errors='coerce' 會將無法轉換的亂碼或字串強制轉為 NaN
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # 確保 date 欄位是 datetime 格式
        df['date'] = pd.to_datetime(df['date'])
        
        #填補缺失值
        df = df.ffill()

        return df