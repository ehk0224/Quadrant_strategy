import pandas as pd
import vectorbt as vbt
import backtest_utils.signal_generator as signal_generator
import time
import numpy as np


def run_backtest():
    '''
    Runs the backtest using vectorbt and generates performance reports.
    '''
    start_time = time.time()  

    sg = signal_generator.SignalGenerator(ticker=None, start=None, end=None, period='3y', max_workers=5)
    dict_close, dict_entries, dict_exits = sg.generate_signals()
    close_df, entries_df, exits_df = sg.merge_dataframes(dict_close, dict_entries, dict_exits)

    pf = vbt.Portfolio.from_signals(
        close=close_df, 
        entries=entries_df, 
        exits=exits_df,
        fees=0.003,  
        freq='1D', 
        init_cash=100000,
        slippage=0.002
    )

    trade_counts = pf.trades.count(group_by=False)
    valid_tickers = trade_counts[trade_counts > 0].index

    if len(valid_tickers) == 0:
        print("所有標的皆未產生任何交易，無法計算績效。")
        return

    valid_pf = pf[list(valid_tickers)]
    trade_records = valid_pf.trades.records_readable

    try:
        stats_list = []
        
        for ticker in valid_pf.wrapper.columns:
            s = valid_pf[ticker].stats()
            s.name = ticker  
            stats_list.append(s)
            
        final_perf_df = pd.concat(stats_list, axis=1).T 
        final_perf_df.index.name = 'Ticker'
        final_perf_df.reset_index(inplace=True)

        with pd.ExcelWriter("0714_BTsummary.xlsx", engine='openpyxl') as writer:
            final_perf_df.to_excel(writer, sheet_name="標的績效總覽", index=False)
            trade_records.to_excel(writer, sheet_name="進出場交易明細", index=False)
            
        print("\n個別標的回測結果已輸出至 0714_BTsummary.xlsx (包含總覽與明細分頁)")
        
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

    return

if __name__ == "__main__":
    run_backtest()  