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

    sg = signal_generator.SignalGenerator(start='2016-01-01', end='2026-05-15', period=None)
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
    '''
    fig = total_equity.vbt.plot(trace_kwargs=dict(name='Total Equity', line=dict(color='blue')))
    fig.update_layout(
        title_text='整體投資組合資金曲線', 
        xaxis_title='日期', 
        yaxis_title='總價值',
        template='plotly_white'
    )
    fig.show()
    '''
    # 1. 基礎繪圖
    fig = total_equity.vbt.plot(
        trace_kwargs=dict(name="Total Equity", line=dict(color="blue", width=2))
    )

    # 2. 標示 OOS 1 區間 (2016-01-01 ~ 2019-01-01)
    fig.add_vrect(
        x0="2016-12-06",
        x1="2019-01-01",
        fillcolor="rgba(200, 200, 200, 0.2)",
        layer="below",
        line_width=0,
        annotation_text="OOS 1",
        annotation_position="top left",
        annotation_font_size=10,
        annotation_font_color="gray",
    )

    # 3. 標示 OOS 2 區間 (2018-01-01 ~ 2023-12-31)
    # 註：雖然 2018-2019 與 OOS1 重疊，這樣畫能明確表示這段屬於長線 OOS 壓力測試
    fig.add_vrect(
        x0="2018-01-01",
        x1="2023-12-31",
        fillcolor="rgba(100, 149, 237, 0.15)",  # 淡藍色背景
        layer="below",
        line_width=0,
        annotation_text="OOS 2",
        annotation_position="top left",
        annotation_font_size=10,
        annotation_font_color="dimgray",
    )

    # 4. 標示 IS 區間與起點垂直分隔線 (2023-05-15 ~ 2026-05-15)
    fig.add_vrect(
        x0="2023-05-15",
        x1="2026-05-15",
        fillcolor="rgba(255, 165, 0, 0.15)",  # 淡橘色背景，突顯 IS 區域
        layer="below",
        line_width=0,
        annotation_text="IS",
        annotation_position="top left",
        annotation_font_size=11,
        annotation_font_color="darkorange",
    )

    # 加入 IS 起始點分割線
    fig.add_vline(
        x="2023-05-15",
        line_width=1.5,
        line_dash="dash",
        line_color="darkorange",
    )

    # 5. 版面細節調整
    fig.update_layout(
        title_text="整體投資組合資金曲線 (IS & OOS 劃分)",
        xaxis_title="日期",
        yaxis_title="總價值",
        template="plotly_white",
        hovermode="x unified",  # 游標停留時顯示統一時間點資料
    )

    fig.show()
    return

if __name__ == "__main__":
    run_backtest()  