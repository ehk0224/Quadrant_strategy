import pandas as pd
import vectorbt as vbt
import concurrent.futures
import time
import random
from backtest_utils.indicatorsbt import Indicators
import core_utils.yfinance_fetcher as yfinance_fetcher
import core_utils.Quadrant as Quadrant
from core_utils.strategy import QuadrantStrategy
import quantstats as qs

start = None
end = None
period = '3y'

def quadrant_analysis(ticker):
    ind = Indicators()
    fetcher = yfinance_fetcher.YfinanceFetcher()
    ana = Quadrant.MarketQuadrantAnalyzer()
    
    df = fetcher.fetch(ticker, start=start, end=end, period=period) 
    df_ind = ind.get_indicators(df)
    df_final = ana.analyze_dataframe(df_ind)
    df_final = ana.attach_descriptions(df_final)

    return df_final

def fetch_and_generate_signals(ticker):
    try:
        time.sleep(random.uniform(0.5, 1.5)) 
        
        df = quadrant_analysis(ticker)
        
        # ====== 【關鍵修復：把日期拉回 Index】 ======
        # 檢查日期是不是變成了一般的欄位，如果是，就把它設為 Index
        # (這裡涵蓋了常見的大小寫命名，請依你實際的欄位名稱為主)
        if 'Date' in df.columns:
            df = df.set_index('Date')
        elif 'date' in df.columns:
            df = df.set_index('date')
        elif 'Datetime' in df.columns:
            df = df.set_index('Datetime')
        
        # 強制將目前的 Index 轉換為標準的時間格式
        df.index = pd.to_datetime(df.index)
        # ============================================

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

    # ==========================================================
    # 抓取 TWII (台灣加權指數) 資料作為 Benchmark 視覺化用途
    # ==========================================================
    print("抓取 TWII (大盤) 資料作為 Benchmark...")
    try:
        fetcher = yfinance_fetcher.YfinanceFetcher()
        twii_df = fetcher.fetch("^TWII", start=start, end=end, period=period)
        
        # ====== 【新增修復：把大盤的日期也拉回 Index】 ======
        if 'Date' in twii_df.columns:
            twii_df = twii_df.set_index('Date')
        elif 'date' in twii_df.columns:
            twii_df = twii_df.set_index('date')
        elif 'Datetime' in twii_df.columns:
            twii_df = twii_df.set_index('Datetime')
        
        # 強制轉換為標準時間格式
        twii_df.index = pd.to_datetime(twii_df.index)
        # ====================================================

        twii_close = twii_df['close'].astype(float)
        benchmark_rets = twii_close.pct_change().dropna()
    except Exception as e:
        print(f"獲取 TWII 失敗: {e}")
        benchmark_rets = None
    # ==========================================================

    # 3. 向量化回測
    print("執行向量化回測...")
    pf = vbt.Portfolio.from_signals(
        close=close_df, 
        entries=entries_df, 
        exits=exits_df,
        fees=0.003,
        freq='1D', 
        init_cash=100000,
        slippage=0.002
        #tp_stop=0.5
    )

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

    # --- 績效計算與時間軸校正 ---
    original_index = close_df.index 
    total_equity = pf.value().sum(axis=1)
    
    # 強制校正時間軸
    total_equity.index = original_index
    overall_returns = total_equity.pct_change().dropna()
    
    # 因為 dropna() 刪掉了第一天，所以索引要從第二天 [1:] 開始對齊
    overall_returns.index = original_index[1:] 

    # ===== 產出 QuantStats HTML =====
    print("\n正在產出 QuantStats HTML 報表...")
    try:
        qs_input = overall_returns.copy()
        # 先移除策略報酬率的時區
        qs_input.index = pd.to_datetime(qs_input.index).tz_localize(None)

        qs_benchmark = '^TWII' 
        if 'benchmark_rets' in locals() and benchmark_rets is not None:
            qs_benchmark = benchmark_rets.copy()
            
            # 修正 1：同樣先移除大盤資料的時區
            qs_benchmark.index = pd.to_datetime(qs_benchmark.index).tz_localize(None)
            
            # 修正 2：避免使用 fillna(0) 破壞變異數
            # 改用 intersection 取交集，確保日期完全對齊且皆有真實數值
            common_index = qs_input.index.intersection(qs_benchmark.index)
            qs_input = qs_input.loc[common_index]
            qs_benchmark = qs_benchmark.loc[common_index]

        qs.reports.html(
            qs_input, 
            benchmark=qs_benchmark, 
            output='portfolio_tearsheet3.html',
            title='My Strategy Tearsheet'
        )
        print("報表產出成功！")
    except Exception as e:
        print(f"QuantStats 報表錯誤: {e}")

    print(f"\n總執行時間: {time.time() - start_time:.2f} 秒")

    fig = total_equity.vbt.plot(trace_kwargs=dict(name='Total Equity', line=dict(color='blue')))
    fig.update_layout(title_text='整體投資組合資金曲線', xaxis_title='日期', yaxis_title='總價值')
    fig.show()

if __name__ == "__main__":
    main()