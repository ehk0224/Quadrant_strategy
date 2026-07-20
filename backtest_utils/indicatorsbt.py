# indicators.py
import pandas as pd
import yfinance as yf
import numpy as np

class Indicators:
    def __init__(self, period="3y", length=200, global_vix=False):
        self.period = period
        self.length = length
        self.latest_vix_p = global_vix # 是否全局快取 VIX 百分位數

    def get_vix_percentile(self, df):
        # 1. 防呆：檢查 df 的 index 是否為時間索引，並標準化（移除時區以利絕對對齊）
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError(" DataFrame 的 Index 必須是 DatetimeIndex 才能進行時序對齊！")
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # 2. 下載 VIX 歷史序列並計算 252 日滾動百分位數 (維持 T-1 日邏輯)
        # 💡 加上 autoadjust=True 並直接取 'Close'，確保拿到 1D Series
        vix_raw = yf.download("^VIX", period=self.period, progress=False, auto_adjust=True)['Close']
        if isinstance(vix_raw, pd.DataFrame):
            vix_raw = vix_raw.squeeze()
            
        vix_p_shifted = vix_raw.rolling(252).rank(pct=True).shift(1)
        
        # 同樣將 VIX 的時區移除，準備進行點對點對齊
        if vix_p_shifted.index.tz is not None:
            vix_p_shifted.index = vix_p_shifted.index.tz_localize(None)

        # 3. 【關鍵：矩陣廣播與自動對齊】
        # 獲取目前的股票代號清單 (Level 1)
        tickers = df.columns.get_level_values(1).unique()
        
        # 利用 dict.fromkeys 將 VIX Series 廣播給每一個 Ticker
        # 並且傳入 index=df.index，讓 Pandas 底層秒速完成「日期左對齊與裁切」！
        vix_matrix = pd.DataFrame(
            dict.fromkeys(tickers, vix_p_shifted), 
            index=df.index
        )

        # 4. 掛上與原本 df 一致的 MultiIndex 外衣
        vix_matrix.columns = pd.MultiIndex.from_product(
            [['vix_percentile'], tickers], 
            names=['feature', 'ticker']
        )
        
        return vix_matrix

    def get_ma200(self, df):
        # 1. 防禦性檢查：確認是否有 MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            price_matrix = df.xs('adj_price', axis=1, level='feature')
        else:
            # 2. 備援處理：若已經是單層索引，直接確認是否有目標欄位
            if 'adj_price' in df.columns:
                price_matrix = df['adj_price']
            else:
                # 3. 輸出詳細狀態以利除錯
                raise TypeError(
                    f"DataFrame 欄位結構錯誤。預期為 MultiIndex 或包含 'adj_price'，"
                    f"實際 columns 型態為 {type(df.columns)}，內容: {df.columns[:5]}"
                )
            
        # --- 計算 200 日移動平均 ---
        ma200_matrix = price_matrix.rolling(200).mean()

        # --- 為新計算的矩陣「重新掛上」雙層欄位標籤 ---
        ma200_matrix.columns = pd.MultiIndex.from_product(
            [['ma200'], ma200_matrix.columns], 
            names=['feature', 'ticker']
        )

        return ma200_matrix
    
    def get_rsi(self, df):
        # 1. 向量化計算每日漲跌 (直接對整個 2D 矩陣相減)
        delta = df.xs('adj_price', axis=1, level='feature').diff()

        # 2. 將漲與跌分離成兩個獨立矩陣
        gain = delta.clip(lower=0)
        loss = -1 * delta.clip(upper=0)

        # 3. 向量化計算 Wilder's 平滑移動平均 (等同於 ta.rsi 底層的 RMA/EMA)
        # RSI 的 alpha 參數固定為 1 / length
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

        # 4. 向量化算出相對強弱 RS 與 RSI 矩陣
        rs = avg_gain / avg_loss
        rsi_matrix = 100 - (100 / (1 + rs))

        rsi_matrix.columns = pd.MultiIndex.from_product(
            [['rsi'], rsi_matrix.columns], 
            names=['feature', 'ticker']
        )

        return rsi_matrix

    def get_adx(self, df, length=14):
        high = df.xs('high', axis=1, level='feature')
        low = df.xs('low', axis=1, level='feature')
        close = df.xs('adj_price', axis=1, level='feature')
        
        prev_close = close.shift(1)
        prev_high = high.shift(1)
        prev_low = low.shift(1)

        # 1. 向量化計算 True Range (TR) 的三個分量
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        
        # 矩陣元素級別取最大值 (Element-wise maximum)
        tr = pd.DataFrame(
            np.maximum(np.maximum(tr1.values, tr2.values), tr3.values),
            index=tr1.index,
            columns=tr1.columns
        )
        
        # 2. 向量化方向變動 (Directional Movement)
        up_move = high - prev_high
        down_move = prev_low - low

        # 使用 Pandas 原生 .where 進行純矩陣條件篩選 (取代迴圈與 if-else)
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        # 3. Wilder's Smoothing (等同於 RMA / alpha = 1/length)
        tr_smooth = tr.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
        plus_dm_smooth = plus_dm.ewm(alpha=1/length, min_periods=length, adjust=False).mean()
        minus_dm_smooth = minus_dm.ewm(alpha=1/length, min_periods=length, adjust=False).mean()

        # 4. 向量化計算 +DI 與 -DI 矩陣
        plus_di = 100 * (plus_dm_smooth / tr_smooth)
        minus_di = 100 * (minus_dm_smooth / tr_smooth)

        # 5. 計算 DX 與最終 ADX 矩陣
        di_sum = plus_di + minus_di
        di_diff = (plus_di - minus_di).abs()
        
        # .replace(0, np.nan) 避免分母為 0 產生無限大
        dx = 100 * (di_diff / di_sum.replace(0, np.nan))
        adx_matrix = dx.ewm(alpha=1/length, min_periods=length, adjust=False).mean()

        adx_matrix.columns = pd.MultiIndex.from_product(
            [['adx'], adx_matrix.columns], 
            names=['feature', 'ticker']
        ) 

        return adx_matrix

    def get_atr(self, df, length=14):
        high = df.xs('high', axis=1, level='feature')
        low = df.xs('low', axis=1, level='feature')
        close = df.xs('adj_price', axis=1, level='feature')
        prev_close = close.shift(1)

        # 向量化計算 TR
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        tr = np.maximum(np.maximum(tr1, tr2), tr3)

        # 向量化 Wilder's Smoothing
        atr_matrix = tr.ewm(alpha=1/length, min_periods=length, adjust=False).mean()

        # 2. 直接在同一個步驟算出 60 日均線
        atr_60d_avg_matrix = atr_matrix.rolling(window=60).mean()

        # 3. 【關鍵升級】分別幫兩個指標掛上 MultiIndex
        atr_matrix.columns = pd.MultiIndex.from_product(
            [['atr'], atr_matrix.columns], 
            names=['feature', 'ticker']
        )
        atr_60d_avg_matrix.columns = pd.MultiIndex.from_product(
            [['atr_60d_avg'], atr_60d_avg_matrix.columns], 
            names=['feature', 'ticker']
        )

        df = pd.concat([atr_matrix, atr_60d_avg_matrix], axis=1)
        
        return df

    def get_bbw_percentile(self, df, length=20, std_mult=2):
        close = df.xs('adj_price', axis=1, level='feature')
        
        # 【數學簡化極速版】
        # 因為 Upper = BBM + 2*STD, Lower = BBM - 2*STD
        # Upper - Lower = 4 * STD
        # 所以 BBW = (4 * STD) / BBM，完全不需要真的算上下軌！
        bbm = close.rolling(window=length).mean()
        std = close.rolling(window=length).std()
        
        bbw_matrix = (2 * std_mult * std) / bbm
        
        # 對全市場二維矩陣直接進行 252 日滾動百分位數排序
        bbw_percentile_matrix = bbw_matrix.rolling(window=252).rank(pct=True)

        # 3. 【關鍵升級】掛上 MultiIndex 並併入原表
        bbw_percentile_matrix.columns = pd.MultiIndex.from_product(
            [['bbw_percentile'], bbw_percentile_matrix.columns], 
            names=['feature', 'ticker']
        )

        return bbw_percentile_matrix

    def get_hv_percentile(self, df):
        drt = df.xs('adj_price', axis=1, level='feature')
        # 1. 對數報酬率矩陣
        log_returns = np.log(drt/ drt.shift(1))
        
        # 2. 20 日歷史波動率矩陣 (年化)
        hv_matrix = log_returns.rolling(window=20).std() * np.sqrt(252)
        
        # 3. 252 日滾動百分位數矩陣
        hv_percentile_matrix = hv_matrix.rolling(window=252).rank(pct=True)
        
        # 3. 【關鍵升級】掛上 MultiIndex 並併入原表
        hv_percentile_matrix.columns = pd.MultiIndex.from_product(
            [['hv_percentile'], hv_percentile_matrix.columns], 
            names=['feature', 'ticker']
        )
        
        return hv_percentile_matrix
       
    def get_yoy(self, df):
        # 1. 防呆檢查與索引標準化 (確保 index 是 DatetimeIndex 且無時區)
        if not isinstance(df.index, pd.DatetimeIndex):
            raise ValueError("DataFrame 的 Index 必須是 DatetimeIndex！")
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        # 2. 從目前的 MultiIndex 提取所有不重複的股票代號
        tickers = df.columns.get_level_values(1).unique()
        
        # 準備三個字典來收集各檔股票的 YoY 時間序列
        dict_yoy_now = {}
        dict_yoy_t1 = {}
        dict_yoy_t2 = {}

        # 3. 逐一下載財報並計算 YoY
        for tk_sym in tickers:
            tk_str = str(tk_sym).strip()
            tk = yf.Ticker(tk_str)
            try:
                financials = tk.financials
                if financials is not None and not financials.empty:
                    # 自動尋找營收欄位
                    rev_col = 'Total Revenue' if 'Total Revenue' in financials.index else ('Operating Revenue' if 'Operating Revenue' in financials.index else None)
                    
                    if rev_col:
                        rev = financials.loc[rev_col].dropna()
                        if len(rev) > 1:
                            # 轉為 Timestamp 並升冪排序 (舊 -> 新)
                            rev.index = pd.to_datetime(rev.index).tz_localize(None)
                            rev = rev.sort_index(ascending=True)
                            
                            # 計算 YoY，因為是年報/季報，期數為 1
                            yoy = rev.pct_change(periods=1)
                            
                            # 【防止未來函數】：加上 90 天作為財報發布日的保守估計
                            yoy.index = yoy.index + pd.Timedelta(days=90)
                            
                            # 收集數據 (移除初期的 NaN)
                            yoy_clean = yoy.dropna()
                            dict_yoy_now[tk_sym] = yoy_clean
                            dict_yoy_t1[tk_sym] = yoy_clean.shift(1)
                            dict_yoy_t2[tk_sym] = yoy_clean.shift(2)
            except Exception as e:
                print(f"[警告] 處理 {tk_str} YoY 失敗: {e}")

        # 4. 【核心黑魔法：建立寬格式矩陣 + 低頻自動填充至高頻日曆】
        def build_aligned_matrix(data_dict, feature_name):
            if not data_dict:
                # 如果都沒抓到資料，產出一張全 NaN 的矩陣
                matrix = pd.DataFrame(np.nan, index=df.index, columns=tickers)
            else:
                # 建立 [公佈日 x Ticker] 的初步矩陣
                raw_matrix = pd.DataFrame(data_dict)
                # 補齊原本 DataFrame 裡有的標的 (避免某些股票抓不到財報漏失欄位)
                raw_matrix = raw_matrix.reindex(columns=tickers)
                
                # 【關鍵防護】將財報公佈日與原本的日每日股價 Index 合併排序
                # 接著使用 method='ffill' (向前填充)，最後切除不要的日子，只保留 df 原本的營業日！
                combined_index = raw_matrix.index.union(df.index).sort_values()
                matrix = raw_matrix.reindex(combined_index).ffill().reindex(df.index)
            
            # 掛上標準的雙層 MultiIndex 標籤
            matrix.columns = pd.MultiIndex.from_product(
                [[feature_name], matrix.columns], 
                names=['feature', 'ticker']
            )
            return matrix

        # 5. 向量化生成三個指標矩陣
        matrix_now = build_aligned_matrix(dict_yoy_now, 'yoy_now')
        matrix_t1  = build_aligned_matrix(dict_yoy_t1, 'yoy_t1')
        matrix_t2  = build_aligned_matrix(dict_yoy_t2, 'yoy_t2')

        df = pd.concat([matrix_now, matrix_t1, matrix_t2], axis=1)

        return df
    
    def get_indicators(self, df):
        indicators = [
            df,
            self.get_ma200(df),
            self.get_rsi(df),
            self.get_adx(df),
            self.get_atr(df),
            self.get_bbw_percentile(df),
            self.get_vix_percentile(df),
            self.get_hv_percentile(df),
            self.get_yoy(df)
        ]
        
        '''
        names = ['df', 'ma200', 'rsi', 'adx', 'atr', 'bbw', 'vix', 'hv', 'yoy']
        print("\n" + "="*40 + " 指標維度診斷報告 " + "="*40)
        for name, ind_df in zip(names, indicators):
            # 取得該指標目前的標的總數與矩陣形狀
            t_count = ind_df.columns.get_level_values('ticker').nunique()
            print(f"指標: {name:<10} | 標的數量: {t_count:<5} | 總欄位數 (shape[1]): {ind_df.shape[1]}")
        print("="*100 + "\n")
        '''

        return pd.concat(indicators, axis=1)
    
if __name__ == "__main__":
    import pandas as pd
    # 這裡引入你之前寫好的 fetcher，用來撈取或讀取既有的快取資料
    import core_utils.yfinance_fetcher as yfinance_fetcher

    print("⏳ 正在讀取測試資料...")
    
    # 1. 準備測試資料 (強烈建議直接讀取你剛剛跑出 296/306 報錯的那份快取檔案或標的清單)
    fetcher = yfinance_fetcher.YfinanceFetcher()
    
    # 【方式 B】或者直接調用 fetcher 載入你平常跑的標的：
    # 這裡放上你平常測試的股票清單，讓它從快取讀入
    #df_raw = fetcher.fetch(ticker=["2330.TW", "2317.TW", "2454.TW"], period="3y", use_cache=True)

    df_raw = pd.read_parquet("data_cache/1101.TW_1102.TW_1210.TW_1216.TW_1229.TW_1301.TW_13_3y.parquet")

    if df_raw.empty:
        print("❌ 測試資料為空，請檢查標的或快取路徑！")
    else:
        print(f"✅ 成功載入原始資料！目前原始 DataFrame 的形狀為: {df_raw.shape}")
        print("-" * 50)
        
        # 2. 實體化你的指標類別 (請把 Indicators 換成你程式碼裡 class 的名字)
        ind = Indicators()
        
        # 3. 呼叫 get_indicators() 
        # 👉 執行到這一步時，你在函式內部加的那段 for 迴圈 diagnostic print 就會自動在終端機噴出！
        print("🚀 開始執行計算與指標診斷...\n")
        df_ind = ind.get_indicators(df_raw)
        
        print("-" * 50)
        print(f"🏁 全矩陣運算完畢！最終合併後的形狀為: {df_ind.shape}")