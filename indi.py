import pandas as pd
import pandas_ta as ta
import yfinance as yf
import numpy as np

#1. 讀取股票清單
Ticker = [line.strip() for line in open('Mystocks.txt', encoding='utf-16') if line.strip()]

# 2. 抓取大盤 VIX 數據 (只需抓一次，取 Close 欄位)
vix_raw = yf.download("^VIX", period="2y", progress=False)['Close']
# 計算 252 天滾動百分位
vix_p = vix_raw.rolling(252).rank(pct=True)
# 確保只取最後一個值，並徹底轉為 float
if not vix_p.empty:
    # 這裡用 values.flatten() 確保不管它是 Series 還是 DataFrame 都能降維
    latest_vix_p = float(vix_p.values.flatten()[-1])
else:
    latest_vix_p = np.nan

# 3. 定義核心計算函數 (逐檔處理)
def get_indicators(Ticker):
    results = [] # 用來收集所有股票的最新數據
    
    for ticker in Ticker:
        # 1. 明確設定 auto_adjust=False 嘗試保留 Adj Close 欄位
        df = yf.download(ticker, period="2y", auto_adjust=False)
        
        # 確保有足夠的資料列數計算 MA200 (至少 200 天)
        if df.empty or len(df) < 200:
            continue
            
        # 2. 處理 yfinance 新版可能的 MultiIndex 欄位問題
        # 使用 get_level_values(0) 抽取第一層 (即 Price 名稱層) 會比 droplevel 更穩定
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # 3. 欄位防呆機制：優先使用 Adj Close，若無則降級使用 Close
        if 'Adj Close' in df.columns:
            df['adj_price'] = df['Adj Close']
        elif 'Close' in df.columns:
            df['adj_price'] = df['Close']
        else:
            print(f"警告：{ticker} 缺少價格欄位，略過此檔。")
            continue
        
        # --- 計算技術指標 ---
        df['ma200'] = ta.sma(df['adj_price'], length=200)
        df['rsi'] = ta.rsi(df['adj_price'], length=14)

        # ADX
        adx_df = ta.adx(df['High'], df['Low'], df['adj_price'], length=14)
        df['adx'] = adx_df['ADX_14'] if adx_df is not None else np.nan

        # ATR 相關
        df['atr'] = ta.atr(df['High'], df['Low'], df['adj_price'], length=14)
        df['atr_60d_avg'] = df['atr'].rolling(window=60).mean()

        # --- 百分位指標 (Percentile) ---
        # BBW Percentile
        bbands = ta.bbands(df['adj_price'], length=20, std=2)
        if bbands is not None and not bbands.empty:
            # 動態比對並取得正確的欄位名稱
            bbu_col = [col for col in bbands.columns if 'BBU' in col][0]
            bbl_col = [col for col in bbands.columns if 'BBL' in col][0]
            bbm_col = [col for col in bbands.columns if 'BBM' in col][0]
            
            # 使用抓取到的正確名稱進行計算
            bbw = (bbands[bbu_col] - bbands[bbl_col]) / bbands[bbm_col]
            df['bbw_percentile'] = bbw.rolling(252).rank(pct=True)
        else:
            df['bbw_percentile'] = np.nan
                
        # HV Percentile
        log_ret = np.log(df['adj_price'] / df['adj_price'].shift(1))
        hv = log_ret.rolling(20).std() * np.sqrt(252)
        df['hv_percentile'] = hv.rolling(252).rank(pct=True)

        # --- 基本面 YoY ---
        tk = yf.Ticker(ticker)
        financials = tk.financials
        
        if financials is not None and 'Total Revenue' in financials.index:
            rev = financials.loc['Total Revenue']
            yoy = rev.pct_change(periods=-1) # 計算年增率
            yoy_now = yoy.iloc[0] if len(yoy) > 0 else np.nan
            yoy_t1 = yoy.iloc[1] if len(yoy) > 1 else np.nan
            yoy_t2 = yoy.iloc[2] if len(yoy) > 2 else np.nan
        else:
            yoy_now = yoy_t1 = yoy_t2 = np.nan

        # --- 整合該檔股票最後一天的所有數據 ---
        latest_data = {
            'ticker': ticker,
            # 使用 float(np.array(...).flatten()[-1]) 是最保險的「脫殼」方式
            'adj_price': round(float(df['adj_price'].values.flatten()[-1]), 2),
            'ma200': round(float(df['ma200'].values.flatten()[-1]), 2),
            'adx': round(float(df['adx'].values.flatten()[-1]), 2),
            'rsi': round(float(df['rsi'].values.flatten()[-1]), 2),
            'atr': round(float(df['atr'].values.flatten()[-1]), 2),
            'atr_60d_avg': round(float(df['atr_60d_avg'].values.flatten()[-1]), 2),
            'bbw_percentile': round(float(df['bbw_percentile'].values.flatten()[-1]), 4),
            'hv_percentile': round(float(df['hv_percentile'].values.flatten()[-1]), 4),
            'vix_percentile': round(latest_vix_p, 4), 
            'yoy_now': round(float(yoy_now), 4) if pd.notna(yoy_now) else np.nan,
            'yoy_t1': round(float(yoy_t1), 4) if pd.notna(yoy_t1) else np.nan,
            'yoy_t2': round(float(yoy_t2), 4) if pd.notna(yoy_t2) else np.nan
        }
        
        # 將字典加入清單
        results.append(latest_data)
            
    # 將包含所有股票最新數據的清單轉為 DataFrame
    final_df = pd.DataFrame(results)
    if not final_df.empty:
        final_df = final_df.set_index('ticker')
        
    return final_df

# 4. 執行並顯示最終結果
final_report = get_indicators(Ticker)
