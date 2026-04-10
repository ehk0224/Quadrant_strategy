import yfinance as yf
import pandas as pd
import numpy as np

# 1. 設定參數
# 讀取檔案，逐行去除空白與換行符號
#Ticker = ["^TWII"] 過濾大盤狀態用
Ticker = [line.strip() for line in open('Mystocks.txt', encoding='utf-16') if line.strip()]
#Ticker = ["2330.TW", "2454.TW", "2317.TW", "2603.TW", "2881.TW"] # 你感興趣的清單
LOOKBACK_WINDOW = 60    # 計算熵的區間
THRESHOLD = 0.8         # 熵值過濾門檻 (0-1)
N_BINS = 10             # 報酬率切分的桶子數
startDate = "2024-01-31"
endDate = "2026-1-31"

def get_stock_data(Ticker, startDate, endDate):
    #抓取還原股價資料
    df = yf.download(Ticker, start=startDate, end=endDate, auto_adjust=False)["Adj Close"]
    return df

def calculate_normalized_entropy(price_series, bins=10):
    #計算單一序列的正規化香農熵
    #計算對數報酬率
    log_returns = np.log(price_series / price_series.shift(1)).dropna()
    
    if len(log_returns) < bins:
        return np.nan
        
    # 離散化並計算機率分布
    counts, _ = np.histogram(log_returns, bins=bins)
    probs = counts / len(log_returns)
    probs = probs[probs > 0]  # 避免 log2(0)
    
    # 香農熵公式
    #H(X) = -Σ p(x) log2(p(x))
    h = -np.sum(probs * np.log2(probs))
    # 正規化 (0~1)
    #H(x)=H(X)/log2(n)，其中 n 是桶子數
    return h / np.log2(bins)

def execute_entropy_filter(Ticker, LOOKBACK_WINDOW=60, THRESHOLD=0.8, N_BINS=10):
    """
    執行完整的熵過濾流程
    輸入：
        ticker_list: 股票代號清單 (e.g., ['2330.TW', '2317.TW'])
        lookback_window: 計算熵的窗口天數 (預設 60)
        threshold: 判定穩定的門檻 (預設 0.8)
        n_bins: 報酬率分佈的桶子數 (預設 10)
        startDate: 起始日期 (預設 2024-01-31)
        endDate: 結束日期 (預設 2026-1-31)
    輸出：
        passed_list: 通過過濾的股票代號清單
        filter_df: 包含詳細熵值的報表 (DataFrame)
    """
    
    # 1. 抓取資料 (調用你原本寫好的 get_stock_data)
    price_df = get_stock_data(Ticker, startDate, endDate)
    
    if price_df.empty:
        print("警告：抓取不到任何價格資料。")
        return [], pd.DataFrame()

    # 2. 建立結果清單
    entropy_results = []

    # 3. 核心過濾循環
    for col in price_df.columns:
        # 取得最後 60 天價格 (LOOKBACK_WINDOW + 1)
        recent_prices = price_df[col].tail(LOOKBACK_WINDOW + 1)
        
        # 防止資料長度不足導致報錯 (例如新股)
        if len(recent_prices.dropna()) < LOOKBACK_WINDOW:
            continue
            
        # 調用你原本寫好的 calculate_normalized_entropy
        entropy_score = calculate_normalized_entropy(recent_prices, bins=N_BINS)
        
        entropy_results.append({
            "Stock": col,
            "Entropy_Score": round(entropy_score, 4),
            "Is_Stable": entropy_score < THRESHOLD
        })

    # 4. 轉成 DataFrame
    filter_df = pd.DataFrame(entropy_results)
    if not filter_df.empty:
        filter_df = filter_df.set_index("Stock")
    else:
        return [], pd.DataFrame()

    # 5. 取得通過過濾的清單
    passed_list = filter_df[filter_df['Is_Stable']].index.tolist()

    # 顯示報表 (如果是 .py 檔建議用 print；Jupyter 用 display)
    print("\n--- 熵過濾結果 ---")
    print(filter_df)
    print(f"\n✅ 通過過濾（雜訊低）的個股: {passed_list}")

    return passed_list

