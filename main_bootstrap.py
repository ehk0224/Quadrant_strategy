import pandas as pd
import vectorbt as vbt
import concurrent.futures
import time
import random
import numpy as np
from indicators import Indicators
import yfinance_fetcher
import Quadrant
from strategy import QuadrantStrategy

def apply_block_bootstrap(returns_series, block_size=20, n_iterations=1000):
    """
    對報酬率序列執行 Block Bootstrap
    
    參數:
    returns_series: pd.Series, 每日報酬率序列
    block_size: int, 區塊大小(天數)。例如 20 代表大約一個交易月
    n_iterations: int, 模擬次數
    """
    returns_array = returns_series.values
    n = len(returns_array)
    bootstrapped_equities = []
    
    for _ in range(n_iterations):
        # 隨機抽取區塊的起始索引
        # 確保區塊不會超出陣列邊界
        block_starts = np.random.randint(0, n - block_size + 1, size=(n // block_size) + 1)
        
        # 拼接區塊以建立新的報酬率序列
        boot_returns = []
        for start in block_starts:
            boot_returns.extend(returns_array[start : start + block_size])
        
        # 截斷至與原始序列相同的長度
        boot_returns = np.array(boot_returns[:n])
        
        # 計算該次模擬的累積權益 (假設初始為 1 單位)
        boot_equity = np.cumprod(1 + boot_returns)
        bootstrapped_equities.append(boot_equity[-1]) 
        
    return bootstrapped_equities

def quadrant_analysis(ticker):
    ind = Indicators()
    fetcher = yfinance_fetcher.YfinanceFetcher()
    ana = Quadrant.MarketQuadrantAnalyzer()
    
    df = fetcher.fetch(ticker, period="3y") 
    df_ind = ind.get_indicators(df)
    df_final = ana.analyze_dataframe(df_ind)
    df_final = ana.attach_descriptions(df_final)
    return df_final

def fetch_and_generate_signals(ticker):
    """供多執行緒呼叫的獨立任務，加入隨機延遲避免被封鎖"""
    try:
        # 隨機暫停 0.5 到 1.5 秒，打散請求頻率
        time.sleep(random.uniform(0.5, 1.5)) 
        
        df = quadrant_analysis(ticker)
        entries, exits = QuadrantStrategy.generate_signals(df)
        return ticker, df['close'], entries, exits, None
    except Exception as e:
        return ticker, None, None, None, str(e)

def main():
    try:
        with open('Mystocks.txt', encoding='utf-16') as f:
            ticker_list = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("錯誤：找不到 'Mystocks.txt' 檔案。")
        return

    start_time = time.time()
    print(f"開始平行獲取 {len(ticker_list)} 檔標的資料與計算訊號...")

    dict_close = {}
    dict_entries = {}
    dict_exits = {}

    # 1. 使用多執行緒加速資料獲取
    # 將 max_workers 降低至安全範圍 (建議 3 到 5)
    with concurrent.futures.ProcessPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_and_generate_signals, t): t for t in ticker_list}
        
        for future in concurrent.futures.as_completed(futures):
            ticker, close, entries, exits, error_msg = future.result()
            if error_msg:
                print(f"獲取 {ticker} 失敗: {error_msg}")
            else:
                dict_close[ticker] = close
                dict_entries[ticker] = entries
                dict_exits[ticker] = exits

    print(f"資料準備完成，耗時: {time.time() - start_time:.2f} 秒")

    if not dict_close:
        print("未成功取得任何數據。")
        return

    # 2. 轉換為 2D DataFrame
    print("合併資料為 2D DataFrame...")
    close_df = pd.DataFrame(dict_close)
    entries_df = pd.DataFrame(dict_entries)
    exits_df = pd.DataFrame(dict_exits)

    # --- 新增：強制轉換資料型態，解決 Numba 編譯錯誤 ---
    # 將價格強制轉為浮點數 (float)
    close_df = close_df.astype(float)
    
    # 將訊號中的空值 (NaN) 視為不動作 (False)，並強制轉為布林值 (bool)
    entries_df = entries_df.fillna(False).astype(bool)
    exits_df = exits_df.fillna(False).astype(bool)

    # 3. 向量化回測
    print("執行向量化回測...")
    pf = vbt.Portfolio.from_signals(
        close=close_df, 
        entries=entries_df, 
        exits=exits_df,
        fees=0.001425,
        freq='1D', 
        init_cash=100000,
        slippage=0.001,
        tp_stop=0.1
    )

    # --- 防呆過濾 ---
    trade_counts = pf.trades.count()
    valid_tickers = trade_counts[trade_counts > 0].index

    if len(valid_tickers) == 0:
        print("所有標的皆未產生任何交易，無法計算績效。")
        return

    valid_pf = pf[list(valid_tickers)]

    # 4. 產出報告
    try:
        stats_list = []
        
        # 走訪 valid_pf 中所有產生交易的股票代碼
        for ticker in valid_pf.wrapper.columns:
            # 取得單一標的的績效數據
            s = valid_pf[ticker].stats()
            s.name = ticker  # 設定 Series 的名稱為股票代碼
            stats_list.append(s)
            
        # 將列表中的 Series 合併為一個 2D DataFrame，並進行轉置 (T)
        final_perf_df = pd.concat(stats_list, axis=1).T
        
        # 讓股票代碼成為獨立的一個欄位，方便在 Excel 中查看
        final_perf_df.index.name = 'Ticker'
        final_perf_df.reset_index(inplace=True)
        
        # 輸出成 Excel
        final_perf_df.to_excel("backtest_summary.xlsx", index=False)
        print("\n個別標的回測結果已輸出至 backtest_summary.xlsx")
        
    except Exception as e:
        print(f"產出個別標的報表時發生錯誤: {e}")

    total_equity = pf.value().sum(axis=1)
    overall_returns = total_equity.pct_change().dropna()
    
    print("\n--- 整體投資組合總績效 ---")
    try:
        print(overall_returns.vbt.returns(freq='1D').stats())
    except Exception as e:
        print(f"計算整體總績效時發生錯誤: {e}")

    # ==========================================
    # 加入 Block Bootstrap 檢定區塊
    # ==========================================
    print("\n--- 執行 Block Bootstrap 穩健性檢定 ---")
    try:
        # 設定區塊為 20 天 (保留約一個月的市場自相關性)，執行 1000 次模擬
        n_sim = 1000
        boot_final_equities = apply_block_bootstrap(overall_returns, block_size=20, n_iterations=n_sim)
        
        # 計算統計數據
        p5 = np.percentile(boot_final_equities, 5)
        p95 = np.percentile(boot_final_equities, 95)
        mean_equity = np.mean(boot_final_equities)
        median_equity = np.median(boot_final_equities)
        
        print(f"Bootstrap 模擬次數: {n_sim} 次, 區塊大小: 20 天")
        print(f"平均最終淨值倍數 (相對於 1): {mean_equity:.2f}x")
        print(f"中位數最終淨值倍數: {median_equity:.2f}x")
        print(f"90% 信心區間: [{p5:.2f}x, {p95:.2f}x]")
        
        # 評估破產風險或負報酬機率 (最終淨值倍數 < 1)
        loss_prob = sum(1 for x in boot_final_equities if x < 1.0) / n_sim
        print(f"模擬路徑中最終虧損機率: {loss_prob * 100:.1f}%")

    except Exception as e:
        print(f"執行 Block Bootstrap 時發生錯誤: {e}")

    #print(f"\n總執行時間: {time.time() - start_time:.2f} 秒")

    # 原有的資金曲線繪製
    fig = total_equity.vbt.plot(trace_kwargs=dict(name='Total Equity', line=dict(color='blue')))
    fig.update_layout(title_text='整體投資組合資金曲線', xaxis_title='日期', yaxis_title='總價值')
    fig.show()

if __name__ == "__main__":
    main()