# indicators.py
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import numpy as np

class Indicators:
    def __init__(self, period="3y", length=200):
        self.period = period
        self.length = length

    def get_vix_percentile(self, df):
        # 檢查是否已經計算過 VIX，若無則進行第一次下載與計算
        if not hasattr(self, 'latest_vix_p'):
            vix_raw = yf.download("^VIX", period="3y", progress=False)['Close']
            vix_p = vix_raw.rolling(252).rank(pct=True)
            
            if not vix_p.empty:
                self.latest_vix_p = float(vix_p.values.flatten()[-1])
            else:
                self.latest_vix_p = np.nan

        # 直接套用已儲存（快取）的單一數值到當前 DataFrame
        df['vix_percentile'] = self.latest_vix_p
        return df

    def get_ma200(self, df):
       #df['ma200'] = ta.sma(df['adj_price'], length=self.length) # 使用 init 設定的 length
        df['ma200'] = df.groupby('ticker')['adj_price'].transform(lambda x: ta.sma(x, length=self.length))
        return df
    
    def get_rsi(self, df):
        #df['rsi'] = ta.rsi(df['adj_price'], length=14)
        df['rsi'] = df.groupby('ticker')['adj_price'].transform(lambda x: ta.rsi(x, length=14))
        return df
    
    def get_adx(self, df):
        #adx_df = ta.adx(df['high'], df['low'], df['adj_price'], length=14)
        adx_df = df.groupby('ticker', group_keys=False).apply(
            lambda g: ta.adx(g['high'], g['low'], g['adj_price'], length=14))
        if adx_df is not None and not adx_df.empty:
            # 動態抓取 ADX 欄位名稱 (通常為 ADX_14)
            adx_col = [col for col in adx_df.columns if col.startswith('ADX')][0]
            df['adx'] = adx_df[adx_col]
        else:
            df['adx'] = np.nan
        return df

    def get_atr(self, df):
        def _calc_atr(g):
            # 計算 ATR
            res = ta.atr(g['high'], g['low'], g['adj_price'], length=14)
            # 如果回傳的是 DataFrame，強制取出第一欄的 Series
            if isinstance(res, pd.DataFrame):
                return res.iloc[:, 0]
            return res

        # 執行 groupby 並套用計算
        atr_series = df.groupby('ticker', group_keys=False).apply(_calc_atr)
        
        # 雙重保險：如果 groupby 彙整後又變成了 DataFrame，再次強制取第一欄
        if isinstance(atr_series, pd.DataFrame):
            df['atr'] = atr_series.iloc[:, 0]
        else:
            df['atr'] = atr_series
            
        return df
    
    def get_atr_60d_avg(self, df):
        if 'atr' in df.columns:
            #df['atr_60d_avg'] = df['atr'].groupby('ticker').rolling(60).mean()
            df['atr_60d_avg'] = df.groupby('ticker')['atr'].transform(lambda x: x.rolling(60).mean())
        return df
    
    def get_bbw_percentile(self, df):
        # 1. 使用 groupby 與 apply 來處理 ta.bbands 回傳的 DataFrame
        # 設定 group_keys=False 以確保產出的 DataFrame Index 能與原始 df 對齊
        bbands = df.groupby('ticker', group_keys=False).apply(
            lambda g: ta.bbands(g['adj_price'], length=20, std=2)
        )
        
        if bbands is not None and not bbands.empty:
            # 取得對應的欄位名稱
            bbu_col = [col for col in bbands.columns if 'BBU' in col][0]
            bbl_col = [col for col in bbands.columns if 'BBL' in col][0]
            bbm_col = [col for col in bbands.columns if 'BBM' in col][0]
            
            # 計算布林通道寬度 (Bollinger Band Width)
            bbw = (bbands[bbu_col] - bbands[bbl_col]) / bbands[bbm_col]
            
            # 2. 將 bbw 暫存至 df，以便進行 groupby 計算 rolling rank
            df['temp_bbw'] = bbw
            
            # 3. 針對每個 ticker 獨立計算 252 天的滾動百分位數
            df['bbw_percentile'] = df.groupby('ticker')['temp_bbw'].transform(
                lambda x: x.rolling(252).rank(pct=True)
            )
            
            # 移除暫存的計算欄位
            df = df.drop(columns=['temp_bbw'])
        else:
            df['bbw_percentile'] = np.nan
            
        return df
    
    def get_hv_percentile(self, df):
        # 1. 計算對數報酬率 (Log Returns)
        # df.groupby('ticker')['adj_price'].shift(1) 會回傳已經按 ticker 分組平移並對齊原 df 的 Series
        log_returns = np.log(df['adj_price'] / df.groupby('ticker')['adj_price'].shift(1))
        
        # 2. 計算 20 日歷史波動率 (HV)
        # 由於 log_returns 是獨立的 Series，需傳入 df['ticker'] 才能進行 groupby
        hv = log_returns.groupby(df['ticker']).transform(
            lambda x: x.rolling(20).std() * np.sqrt(252)
        )
        
        # 3. 計算 252 日歷史波動率的百分位數 (Percentile)
        # 同樣傳入 df['ticker'] 作為分組依據
        df['hv_percentile'] = hv.groupby(df['ticker']).transform(
            lambda x: x.rolling(252).rank(pct=True)
        )
        
        return df
       
    def get_yoy(self, df, ticker='ticker'):
        # 1. 檢查 ticker 欄位是否存在於 df 中
        if ticker not in df.columns:
            df['yoy_now'] = df['yoy_t1'] = df['yoy_t2'] = np.nan
            return df

        # 2. 取得不重複的 ticker
        unique_tickers = df[ticker].dropna().unique()
        yoy_data = []

        # 3. 逐一計算每檔股票的 YoY
        for tk_sym in unique_tickers:
            # 確保代碼為字串
            tk_str = str(tk_sym).strip()
            tk = yf.Ticker(tk_str)
            
            yoy_now = yoy_t1 = yoy_t2 = np.nan
            
            try:
                financials = tk.financials
                if financials is not None and not financials.empty:
                    # 處理不同產業可能的營收欄位名稱
                    revenue_col = None
                    if 'Total Revenue' in financials.index:
                        revenue_col = 'Total Revenue'
                    elif 'Operating Revenue' in financials.index:
                        revenue_col = 'Operating Revenue'
                    
                    if revenue_col:
                        rev = financials.loc[revenue_col].dropna()
                        
                        if len(rev) > 1: # 至少需要兩筆資料才能算 YoY
                            # 確保 index 轉換為 datetime，並確保以日期降冪排列 (新 -> 舊)
                            rev.index = pd.to_datetime(rev.index)
                            rev = rev.sort_index(ascending=False)
                            
                            # 計算 YoY
                            yoy = rev.pct_change(periods=-1)
                            
                            yoy_now = yoy.iloc[0] if len(yoy) > 0 else np.nan
                            yoy_t1  = yoy.iloc[1] if len(yoy) > 1 else np.nan
                            yoy_t2  = yoy.iloc[2] if len(yoy) > 2 else np.nan
                    else:
                        print(f"[警告] {tk_str}: 找不到 Total Revenue 或 Operating Revenue")
                else:
                    print(f"[警告] {tk_str}: 財報資料為空 (請確認代碼格式，如台股需加 .TW/.TWO)")
                    
            except Exception as e:
                # 將真正的錯誤印出以便 Debug
                print(f"[錯誤] 處理 {tk_str} 時發生例外狀況: {e}")
                
            yoy_data.append({
                ticker: tk_sym,
                'yoy_now': yoy_now,
                'yoy_t1': yoy_t1,
                'yoy_t2': yoy_t2
            })

        # 4. 合併結果
        yoy_df = pd.DataFrame(yoy_data)
        
        cols_to_update = ['yoy_now', 'yoy_t1', 'yoy_t2']
        df = df.drop(columns=[col for col in cols_to_update if col in df.columns])

        df = df.merge(yoy_df, on=ticker, how='left')
        
        return df
    
    def get_indicators(self, df):
        df = self.get_ma200(df)
        df = self.get_rsi(df)
        df = self.get_adx(df)
        df = self.get_atr(df)
        df = self.get_atr_60d_avg(df)
        df = self.get_bbw_percentile(df)
        df = self.get_vix_percentile(df) # 修正：傳入 df 並確保方法名稱一致
        df = self.get_hv_percentile(df)
        df = self.get_yoy(df)
        
        # 修正：確保有 ticker 才呼叫，避免報錯
        ticker = df['ticker'].iloc[0] if 'ticker' in df.columns else None
        #df = self.get_yoy(df, ticker=ticker)
        #df = df.groupby('ticker').tail(1).copy()       
        return df