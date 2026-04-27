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

    # ==========================================
    # 新增：隨機模擬驗證 (Monte Carlo Benchmark)
    # ==========================================
    print("\n執行隨機模擬驗證中 (Monte Carlo Benchmark)...")
    n_sims = 500  # 測試次數
    
    # 1. 取得你原始策略的整體平均夏普值 (將 NaN 填補為 0 避免計算錯誤)
    actual_sharpe = valid_pf.sharpe_ratio().fillna(0).mean()
    
    # 2. 計算原始訊號的進場與出場機率
    # 這樣會讓「隨機產生器」的交易頻率，跟你的四象限策略幾乎一模一樣
    entry_prob = entries_df.mean().mean() 
    exit_prob = exits_df.mean().mean()
    
    # 防呆：如果你的策略目前完全沒有出場訊號，給定一個預設機率 (0.1 代表平均持倉 10 天)
    if pd.isna(exit_prob) or exit_prob == 0: 
        exit_prob = 0.1
        
    print(f"基準參數 -> 每日進場機率: {entry_prob:.4f}, 每日出場機率: {exit_prob:.4f}")
    
    sim_sharpes = []
    
    # 3. 使用迴圈進行多次隨機模擬
    for i in range(n_sims):
        rand_pf = vbt.Portfolio.from_random_signals(
            close_df, 
            entry_prob=entry_prob,
            exit_prob=exit_prob,
            fees=0.001425,
            init_cash=100000,
            slippage=0.001,
            freq='1D'
        )
        # 把這次隨機模擬的「所有標的平均夏普值」存起來
        sim_sharpes.append(rand_pf.sharpe_ratio().fillna(0).mean())
        
    sim_sharpes = np.array(sim_sharpes)
    
    # 4. 計算 P-value
    #p_value = (sim_sharpes >= actual_sharpe).sum() / n_sims
    p_value = ((sim_sharpes >= actual_sharpe).sum() + 1) / (n_sims + 1)  # 加 1 是為了避免 p-value 為 0 的情況，提供更穩健的估計
    
    print(f"\n--- 隨機模擬統計結果 ---")
    print(f"原始策略平均夏普值: {actual_sharpe:.4f}")
    print(f"隨機模擬平均夏普值: {sim_sharpes.mean():.4f}")
    print(f"P-value: {p_value:.4f}")

    if p_value < 0.05:
        print(">>> 結論：統計顯著 (p < 0.05)！你的策略邏輯確實具備優勢，非隨機致勝。")
    else:
        print(">>> 結論：未達顯著標準，目前的績效分佈與隨機亂買差異不大。")
    # ==========================================

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
        final_perf_df.to_excel("backtest_summary_random.xlsx", index=False)
        print("\n個別標的回測結果已輸出至 backtest_summary_random.xlsx")
        
    except Exception as e:
        print(f"產出個別標的報表時發生錯誤: {e}")

    total_equity = pf.value().sum(axis=1)
    overall_returns = total_equity.pct_change().dropna()
    
    print("\n--- 整體投資組合總績效 ---")
    try:
        print(overall_returns.vbt.returns(freq='1D').stats())
    except Exception as e:
        print(f"計算整體總績效時發生錯誤: {e}")

    print(f"\n總執行時間: {time.time() - start_time:.2f} 秒")

    fig = total_equity.vbt.plot(trace_kwargs=dict(name='Total Equity', line=dict(color='blue')))
    fig.update_layout(title_text='整體投資組合資金曲線', xaxis_title='日期', yaxis_title='總價值')
    fig.show()

if __name__ == "__main__":
    main()