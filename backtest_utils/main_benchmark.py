import pandas as pd
import vectorbt as vbt
import concurrent.futures
import time
import random
from backtest_utils.indicatorsbt import Indicators
import core_utils.yfinance_fetcher as yfinance_fetcher
import core_utils.Quadrant as Quadrant
from core_utils.strategy import QuadrantStrategy

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
    #供多執行緒呼叫的獨立任務，加入隨機延遲避免被封鎖
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

    # 強制轉換資料型態
    close_df = close_df.astype(float)
    entries_df = entries_df.fillna(False).astype(bool)
    exits_df = exits_df.fillna(False).astype(bool)

    # ==========================================================
    # 抓取 TWII (台灣加權指數) 資料作為 Benchmark 視覺化用途
    # ==========================================================
    print("抓取 TWII (大盤) 資料作為 Benchmark...")
    try:
        fetcher = yfinance_fetcher.YfinanceFetcher()
        twii_df = fetcher.fetch("^TWII", start=start, end=end, period=period)
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
        fees=0.001425,
        freq='1D', 
        init_cash=100000,
        slippage=0.001,
        tp_stop=0.5
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
        
        for ticker in valid_pf.wrapper.columns:
            # 移除 benchmark_rets 參數，回歸預設統計計算
            s = valid_pf[ticker].stats()
            s.name = ticker
            stats_list.append(s)
            
        final_perf_df = pd.concat(stats_list, axis=1).T
        final_perf_df.index.name = 'Ticker'
        final_perf_df.reset_index(inplace=True)
        
        final_perf_df.to_excel("backtest_summary.xlsx", index=False)
        print("\n個別標的回測結果已輸出至 backtest_summary.xlsx")
        
    except Exception as e:
        print(f"產出個別標的報表時發生錯誤: {e}")

    total_equity = pf.value().sum(axis=1)
    overall_returns = total_equity.pct_change().dropna()
    
    print("\n--- 整體投資組合總績效 ---")
    try:
        # 移除 benchmark_rets 參數
        print(overall_returns.vbt.returns(freq='1D').stats())
    except Exception as e:
        print(f"計算整體總績效時發生錯誤: {e}")

    print(f"\n總執行時間: {time.time() - start_time:.2f} 秒")

    if benchmark_rets is not None:
        print("\n--- 相對績效指標 (相對於 ^TWII) ---")
        
        # 1. 對齊日期：這是量化回測非常重要的一步，確保投組與大盤的交易日完全一致
        aligned_rets = pd.concat([overall_returns, benchmark_rets], axis=1, join='inner').dropna()
        port_rets = aligned_rets.iloc[:, 0]
        bench_rets = aligned_rets.iloc[:, 1]
        
        try:
            # 2. 直接呼叫 vectorbt 的 returns 模組來計算單一指標
            # 注意：這裡的 freq 必須設定，否則 vectorbt 無法年化數據
            vbt_beta = port_rets.vbt.returns(freq='1D').beta(benchmark_rets=bench_rets)
            vbt_alpha = port_rets.vbt.returns(freq='1D').alpha(benchmark_rets=bench_rets)
            
            print(f"Beta (系統性風險): {vbt_beta:.4f}")
            print(f"Alpha (年化超額報酬): {vbt_alpha:.4%}")
            
        except Exception as e:
            print(f"計算 Alpha/Beta 時發生錯誤: {e}")

    # 繪製圖表
    fig = total_equity.vbt.plot(trace_kwargs=dict(name='Total Equity', line=dict(color='blue')))
    
    # ==========================================================
    # 將 Benchmark 資金曲線疊加於同一圖表
    # ==========================================================
    if benchmark_rets is not None:
        initial_value = total_equity.iloc[0] 
        benchmark_equity = initial_value * (1 + benchmark_rets).cumprod()
        fig = benchmark_equity.vbt.plot(trace_kwargs=dict(name='Benchmark (^TWII)', line=dict(color='gray', dash='dash')), fig=fig)
    # ==========================================================

    fig.update_layout(title_text='整體投資組合資金曲線與大盤比較', xaxis_title='日期', yaxis_title='總價值')
    fig.show()

if __name__ == "__main__":
    main()