import pandas as pd
import vectorbt as vbt
import backtest_utils.signal_generator as signal_generator
import time
import numpy as np


def run_backtest():
    '''
    Runs the backtest using vectorbt and generates performance reports.
    With cash sharing.
    '''
    start_time = time.time()  

    sg = signal_generator.SignalGenerator(start='2018-01-01', end='2023-12-31', period=None)
    close_df, entries_df, exits_df = sg.generate_signals()

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

    # --- 5. 繪製並顯示總資產曲線 ---
    fig = total_equity.vbt.plot(trace_kwargs=dict(name='Total Equity', line=dict(color='blue')))
    fig.update_layout(
        title_text='整體投資組合資金曲線', 
        xaxis_title='日期', 
        yaxis_title='總價值',
        template='plotly_white'
    )
    fig.show()

    return

if __name__ == "__main__":
    run_backtest()  