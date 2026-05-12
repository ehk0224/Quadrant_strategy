# indicators.py
import pandas as pd
import pandas_ta as ta
import yfinance as yf
import numpy as np

class Indicators:
    def __init__(self, period="3y", length=200, global_vix=False):
        self.period = period
        self.length = length
        self.latest_vix_p = global_vix # 是否全局快取 VIX 百分位數

    def get_vix_percentile(self, df, date_col='date'):
        # 1. 確保有日期欄位可以進行點對點對齊
        if date_col not in df.columns:
            raise ValueError(f"DataFrame 必須包含 '{date_col}' 欄位才能進行時間對齊。如果日期在 index，請先 reset_index()。")

        # 2. 下載 VIX 歷史序列 (保留原本的 rolling rank 與 shift 邏輯)
        vix_raw = yf.download("^VIX", period=self.period, progress=False, auto_adjust=True)['Close']
        
        # 處理 yfinance 可能回傳單行 DataFrame 或 Series 的情況
        if isinstance(vix_raw, pd.DataFrame):
            vix_raw = vix_raw.squeeze()
            
        vix_p = vix_raw.rolling(252).rank(pct=True)
        vix_p_shifted = vix_p.shift(1) # T 日使用 T-1 日的數據

        # 3. 建立時間序列 DataFrame 並統一日期的格式 (移除時區以利對齊)
        vix_df = vix_p_shifted.reset_index()
        vix_df.columns = [date_col, 'vix_percentile'] 
        
        vix_df[date_col] = pd.to_datetime(vix_df[date_col]).dt.tz_localize(None)
        df[date_col] = pd.to_datetime(df[date_col]).dt.tz_localize(None)

        # 4. 點對點合併：根據日期左關聯，每一天的股價都會配到對應日期的 VIX
        df = pd.merge(df, vix_df, on=date_col, how='left')
        
        return df

    def get_ma200(self, df):
        df['ma200'] = df.groupby('ticker')['adj_price'].transform(lambda x: ta.sma(x, length=self.length))
        return df
    
    def get_rsi(self, df):
        df['rsi'] = df.groupby('ticker')['adj_price'].transform(lambda x: ta.rsi(x, length=14))
        return df
    
    def get_adx(self, df):
        adx_df = df.groupby('ticker', group_keys=False).apply(
            lambda g: ta.adx(g['high'], g['low'], g['adj_price'], length=14), include_groups=False)
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
        atr_series = df.groupby('ticker', group_keys=False).apply(_calc_atr, include_groups=False)
        
        # 雙重保險：如果 groupby 彙整後又變成了 DataFrame，再次強制取第一欄
        if isinstance(atr_series, pd.DataFrame):
            df['atr'] = atr_series.iloc[:, 0]
        else:
            df['atr'] = atr_series
            
        return df
    
    def get_atr_60d_avg(self, df):
        if 'atr' in df.columns:
            df['atr_60d_avg'] = df.groupby('ticker')['atr'].transform(lambda x: x.rolling(60).mean())
        return df
    
    def get_bbw_percentile(self, df):
        # 1. 使用 groupby 與 apply 來處理 ta.bbands 回傳的 DataFrame
        # 設定 group_keys=False 以確保產出的 DataFrame Index 能與原始 df 對齊
        bbands = df.groupby('ticker', group_keys=False).apply(
            lambda g: ta.bbands(g['adj_price'], length=20, std=2), include_groups=False
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
       
    def get_yoy(self, df, ticker='ticker', date_col='date'):
        # 1. 檢查必備欄位
        if ticker not in df.columns or date_col not in df.columns:
            raise ValueError(f"DataFrame 必須包含 '{ticker}' 與 '{date_col}' 欄位")

        unique_tickers = df[ticker].dropna().unique()
        all_yoy_data = []

        # 2. 逐一計算並收集所有股票的歷史 YoY 時間表
        for tk_sym in unique_tickers:
            tk_str = str(tk_sym).strip()
            tk = yf.Ticker(tk_str)
            
            try:
                financials = tk.financials
                if financials is not None and not financials.empty:
                    revenue_col = 'Total Revenue' if 'Total Revenue' in financials.index else ('Operating Revenue' if 'Operating Revenue' in financials.index else None)
                    
                    if revenue_col:
                        rev = financials.loc[revenue_col].dropna()
                        
                        if len(rev) > 1:
                            # 為了點對點合併(merge_asof)，時間必須是「舊 -> 新」 (ascending=True)
                            rev.index = pd.to_datetime(rev.index)
                            rev = rev.sort_index(ascending=True)
                            
                            # 計算 YoY，因為排序已改為舊到新，所以 periods 改為正數 1
                            yoy = rev.pct_change(periods=1)
                            
                            # 將該股票的 YoY 紀錄做成 DataFrame，並加入 90 天的資訊落後
                            tk_yoy = pd.DataFrame({
                                ticker: tk_sym,
                                'release_date': yoy.index + pd.Timedelta(days=90), # 財報結算日 + 90 天
                                'yoy_now': yoy,
                                'yoy_t1': yoy.shift(1),
                                'yoy_t2': yoy.shift(2)
                            }).dropna(subset=['yoy_now']) # 移除無法計算初期的 NaN
                            
                            all_yoy_data.append(tk_yoy)
            except Exception as e:
                print(f"[錯誤] 處理 {tk_str} 時發生例外狀況: {e}")

        # 如果沒有抓到任何資料
        if not all_yoy_data:
            df['yoy_now'] = df['yoy_t1'] = df['yoy_t2'] = np.nan
            return df

        # 3. 整合所有財報歷史
        yoy_master = pd.concat(all_yoy_data, ignore_index=True)
        
        # 統一日期格式 (去除時區)
        yoy_master['release_date'] = pd.to_datetime(yoy_master['release_date']).dt.tz_localize(None)
        df[date_col] = pd.to_datetime(df[date_col]).dt.tz_localize(None)

        # 移除可能已存在的舊有欄位，避免合併時產生 _x, _y 後綴
        cols_to_update = ['yoy_now', 'yoy_t1', 'yoy_t2']
        df = df.drop(columns=[col for col in cols_to_update if col in df.columns], errors='ignore')

        # 4. 點對點合併 (Point-in-Time Merge)
        # 先決條件：兩邊的表都必須按時間欄位升冪排序
        df = df.sort_values([ticker, date_col])
        yoy_master = yoy_master.sort_values('release_date')

        # 對於 df 中的每一天 (date_col)，往回找最近一個已公佈的 release_date
        df = pd.merge_asof(
            df,
            yoy_master,
            left_on=date_col,
            right_on='release_date',
            left_by=ticker,
            right_by=ticker,
            direction='backward'
        )

        # 5. 清理暫存的公佈日欄位，並恢復原本的 DataFrame 順序
        df = df.drop(columns=['release_date'], errors='ignore').sort_index()
        
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