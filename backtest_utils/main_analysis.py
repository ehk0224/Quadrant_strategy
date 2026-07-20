import pandas as pd
import vectorbt as vbt
import time
import backtest_utils.signal_generator as signal_generator
import quantstats as qs
    

def main():
    start_time = time.time()  

    sg = signal_generator.SignalGenerator(start='2023-05-15', end='2026-05-15', period=None)
    close_df, entries_df, exits_df = sg.generate_signals()
    benchmark_rets = sg.benchmark()

    pf = vbt.Portfolio.from_signals(
        close=close_df.droplevel(0, axis=1), 
        entries=entries_df.droplevel(0, axis=1), 
        exits=exits_df.droplevel(0, axis=1),
        fees=0.003,  
        slippage=0.002,
        freq='1D', 
        
        init_cash=29600000,      
        cash_sharing=True,       
        group_by=True,          
        size=100000,             
        size_type='Value'        
    )

    print(pf.stats())

    if pf.trades.count() == 0:
        print("所有標的皆未產生任何交易，無法計算績效。")
        return
    
    total_equity = pf.value()
    overall_returns = total_equity.pct_change().dropna()

    print("\n--- 整體投資組合總績效 ---")
    try:
        # 針對加總後的單一總資產報酬率，呼叫 stats() 速度極快
        print(overall_returns.vbt.returns(freq='1D').stats())
    except Exception as e:
        print(f"計算整體總績效時發生錯誤: {e}")

    print(f"\n總執行時間: {time.time() - start_time:.2f} 秒")
    

    print("=== 進入 try 之前的變數狀態大檢查 ===")
    print("主程式的 benchmark_rets 是否為 None:", benchmark_rets is None)
    if benchmark_rets is not None:
        print("主程式的 benchmark_rets 結構:\n", benchmark_rets.head(2))

    # ===== 產出 QuantStats HTML =====
    print("\n正在產出 QuantStats HTML 報表...")

    qs_benchmark = None  

    try:
        qs_input = overall_returns.copy()
        qs_input.index = pd.to_datetime(qs_input.index).tz_localize(None)

        if benchmark_rets is not None:
            qs_benchmark = benchmark_rets.iloc[:, 0].copy()
            qs_benchmark.name = 'Benchmark'

            qs_input.index = pd.to_datetime(qs_input.index).date
            qs_benchmark.index = pd.to_datetime(qs_benchmark.index).date
            
            qs_input.index = pd.DatetimeIndex(qs_input.index)
            qs_benchmark.index = pd.DatetimeIndex(qs_benchmark.index)
            
            common_index = qs_input.index.intersection(qs_benchmark.index)

            qs_input = qs_input.loc[common_index]
            qs_benchmark = qs_benchmark.loc[common_index]

        print("qs_input 範例:", qs_input.head(2))
        print("qs_benchmark 範例:", qs_benchmark.head(2))
        qs.reports.html(
            qs_input, 
            benchmark=qs_benchmark, 
            output='portfolio_tearsheet.html',
            title='My Strategy Tearsheet'
        )
        print("報表產出成功！")

    except Exception as e:
        print(f"QuantStats 報表錯誤: {e}")

    print(f"\n總執行時間: {time.time() - start_time:.2f} 秒")

    fig = total_equity.vbt.plot(trace_kwargs=dict(name='Total Equity', line=dict(color='blue')))
    fig.update_layout(title_text='整體投資組合資金曲線', xaxis_title='日期', yaxis_title='總價值')
    fig.show()
    return


if __name__ == "__main__":
    main()