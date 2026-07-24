import pandas as pd
import vectorbt as vbt
import backtest_utils.signal_generator as signal_generator
import time
import numpy as np
import plotly.graph_objects as go



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


def run_bootstrap():
    start_time = time.time()  

    # 1. 產生訊號
    sg = signal_generator.SignalGenerator(start='2023-05-15', end='2026-05-15', period=None)
    close_df, entries_df, exits_df = sg.generate_signals()

    # 2. 建立原始策略投資組合 (共用資金池模式)
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

    print("\n--- 原始投資組合摘要 ---")
    print(pf.stats())

    if pf.trades.count() == 0:
        print("所有標的皆未產生任何交易，無法計算績效。")
        return
    
    # 由於設定了 group_by=True，pf.value() 直接就是 1D 的整體資金曲線
    total_equity = pf.value()
    overall_returns = total_equity.pct_change().dropna()

    # ==========================================
    # 加入 Block Bootstrap 檢定區塊
    # ==========================================
    print("\n--- 執行 Block Bootstrap 穩健性檢定 ---")
    try:
        # 設定區塊為 20 天 (保留約一個月的市場自相關性)，執行 1000 次模擬
        n_sim = 1000
        block_size = 1
        boot_final_equities = apply_block_bootstrap(overall_returns, block_size=block_size, n_iterations=n_sim)
        
        # 計算統計數據
        p5 = np.percentile(boot_final_equities, 5)
        p95 = np.percentile(boot_final_equities, 95)
        mean_equity = np.mean(boot_final_equities)
        median_equity = np.median(boot_final_equities)
        
        print(f"Bootstrap 模擬次數: {n_sim} 次, 區塊大小: {block_size} 天")
        print(f"平均最終淨值倍數 (相對於 1): {mean_equity:.2f}x")
        print(f"中位數最終淨值倍數: {median_equity:.2f}x")
        print(f"90% 信心區間: [{p5:.2f}x, {p95:.2f}x]")
        
        # 評估破產風險或負報酬機率 (最終淨值倍數 < 1)
        loss_prob = sum(1 for x in boot_final_equities if x < 1.0) / n_sim
        print(f"模擬路徑中最終虧損機率: {loss_prob * 100:.1f}%")

    except Exception as e:
        print(f"執行 Block Bootstrap 時發生錯誤: {e}")

    print(f"\n總執行時間: {time.time() - start_time:.2f} 秒")

    # 原有的資金曲線繪製
    fig = total_equity.vbt.plot(trace_kwargs=dict(name='Total Equity', line=dict(color='blue')))
    fig.update_layout(title_text='整體投資組合資金曲線', xaxis_title='日期', yaxis_title='總價值')
    fig.show()

    # Bootstrap 模擬的分布圖
    boot_series = pd.Series(boot_final_equities)
    boot_series.vbt.histplot(title='Bootstrap 模擬最終淨值倍數分布', xaxis_title='最終淨值倍數', yaxis_title='頻率').show()

if __name__ == "__main__":
    run_bootstrap()