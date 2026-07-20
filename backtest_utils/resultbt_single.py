import pandas as pd
import vectorbt as vbt
import backtest_utils.signal_generator as signal_generator
import time
import numpy as np


def run_backtest():
    '''
    Runs the backtest using vectorbt and generates performance reports.
    Invest an equal amount in each ticker.
    '''
    start_time = time.time()  

    sg = signal_generator.SignalGenerator(start='2023-05-15', end='2026-05-15', period=None)
    close_df, entries_df, exits_df = sg.generate_signals()

    pf = vbt.Portfolio.from_signals(
        close=close_df.droplevel(0, axis=1), 
        entries=entries_df.droplevel(0, axis=1), 
        exits=exits_df.droplevel(0, axis=1),
        fees=0.003,  
        slippage=0.002,
        freq='1D', 
        init_cash=100000        
    )

    print(pf.stats())

    
    # --- 1. 篩選有交易的標的 ---
    trade_counts = pf.trades.count(group_by=False)
    valid_tickers = trade_counts[trade_counts > 0].index

    if len(valid_tickers) == 0:
        print("所有標的皆未產生任何交易，無法計算績效。")
        return

    valid_pf = pf[list(valid_tickers)]
    trade_records = valid_pf.trades.records_readable  

    # --- 2. 標的績效總覽 ---
    try:
        print("\n開始計算各標的績效指標...")
        t0 = time.time()
        
        final_perf_df = pd.DataFrame({
            '總報酬率 (%)': valid_pf.total_return() * 100,
            '年化報酬率 (%)': valid_pf.annualized_return() * 100,
            '夏普比率 (Sharpe)': valid_pf.sharpe_ratio(),
            '最大回檔 (%)': valid_pf.max_drawdown() * 100,
            '總交易次數': valid_pf.trades.count(),
            '勝率 (%)': valid_pf.trades.win_rate() * 100,
            '獲利因子 (Profit Factor)': valid_pf.trades.profit_factor()
        })
        
        # 處理可能產生的無限大 (inf) 數值（例如從未虧損時的獲利因子），並四捨五入
        final_perf_df = final_perf_df.replace([np.inf, -np.inf], np.nan).round(2)
        final_perf_df.index.name = 'Ticker'
        final_perf_df.reset_index(inplace=True)
        
        print(f"極速績效計算完成，耗時: {time.time() - t0:.4f} 秒")

        # --- 3. 輸出至 Excel  ---
        with pd.ExcelWriter("0714_BTsummary.xlsx", engine='openpyxl') as writer:
            final_perf_df.to_excel(writer, sheet_name="標的績效總覽", index=False)
            trade_records.to_excel(writer, sheet_name="進出場交易明細", index=False)
            
        print(f"個別標的回測結果已輸出至 0714_BTsummary.xlsx (包含總覽與明細分頁)")
        
    except Exception as e:
        print(f"產出個別標的報表時發生錯誤: {e}")

    # --- 4. 整體投資組合總績效 ---
    total_equity = pf.value().sum(axis=1) 
    overall_returns = total_equity.pct_change().dropna()

    print("\n--- 整體投資組合總績效 ---")
    try:
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