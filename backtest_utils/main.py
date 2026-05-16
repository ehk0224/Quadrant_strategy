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
    '''供多執行緒呼叫的獨立任務，加入隨機延遲避免被封鎖'''
    try:
        time.sleep(random.uniform(0.5, 1.5)) 
        
        df = quadrant_analysis(ticker)
        entries, exits = QuadrantStrategy.generate_signals(df)
        return ticker, df['close'], entries, exits, None
    except Exception as e:
        return ticker, None, None, None, str(e)

def main():
    '''主函式，負責整體流程控制'''
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

    print("合併資料為 2D DataFrame...")
    close_df = pd.DataFrame(dict_close)
    entries_df = pd.DataFrame(dict_entries)
    exits_df = pd.DataFrame(dict_exits)
    close_df = close_df.astype(float)
    entries_df = entries_df.fillna(False).astype(bool)
    exits_df = exits_df.fillna(False).astype(bool)

    print("執行向量化回測...")
    pf = vbt.Portfolio.from_signals(
        close=close_df, 
        entries=entries_df, 
        exits=exits_df,
        fees=0.003,  
        freq='1D', 
        init_cash=100000,
        slippage=0.002  
    )

    trade_counts = pf.trades.count()
    valid_tickers = trade_counts[trade_counts > 0].index

    if len(valid_tickers) == 0:
        print("所有標的皆未產生任何交易，無法計算績效。")
        return

    valid_pf = pf[list(valid_tickers)]

    try:
        stats_list = []
        
        for ticker in valid_pf.wrapper.columns:
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
        print(overall_returns.vbt.returns(freq='1D').stats())
    except Exception as e:
        print(f"計算整體總績效時發生錯誤: {e}")

    print(f"\n總執行時間: {time.time() - start_time:.2f} 秒")

    fig = total_equity.vbt.plot(trace_kwargs=dict(name='Total Equity', line=dict(color='blue')))
    fig.update_layout(title_text='整體投資組合資金曲線', xaxis_title='日期', yaxis_title='總價值')
    fig.show()

if __name__ == "__main__":
    main()