import pandas as pd
import vectorbt as vbt
import backtest_utils.signal_generator as signal_generator
import time
import numpy as np
import plotly.graph_objects as go

def run_backtest():
    '''
    Runs the backtest using vectorbt and generates performance reports.
    With cash sharing, Monte Carlo benchmark, and Plotly visualization.
    '''
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
    # 3. 隨機模擬驗證 (Monte Carlo Benchmark)
    # ==========================================
    print("\n執行隨機模擬驗證中 (Monte Carlo Benchmark)...")
    n_sims = 1000  # 測試次數
    
    actual_sharpe = pf.sharpe_ratio() # 群組化後直接是純量 float
    if pd.isna(actual_sharpe):
        actual_sharpe = 0.0
        
    entry_prob = entries_df.mean().mean() 
    exit_prob = exits_df.mean().mean()
    
    if pd.isna(exit_prob) or exit_prob == 0: 
        exit_prob = 0.1
        
    print(f"基準參數 -> 每日進場機率: {entry_prob:.4f}, 每日出場機率: {exit_prob:.4f}")
    
    sim_sharpes = []
    sim_equities = []  
    
    for i in range(n_sims):
        # 關鍵修正：套用與原始策略完全相同的資金池與群組設定，確保 Y 軸起跑線一致
        rand_pf = vbt.Portfolio.from_random_signals(
            close=close_df.droplevel(0, axis=1), 
            entry_prob=entry_prob,
            exit_prob=exit_prob,
            fees=0.003,
            slippage=0.002,
            freq='1D',
            init_cash=29600000,
            cash_sharing=True,
            group_by=True,
            size=100000,
            size_type='Value'
        )
        
        # 記錄組合夏普值
        r_sharpe = rand_pf.sharpe_ratio()
        sim_sharpes.append(0.0 if pd.isna(r_sharpe) or np.isinf(r_sharpe) else r_sharpe)
            
        # 記錄該次模擬的「整體投資組合資金曲線」
        sim_equities.append(rand_pf.value())
        
    sim_sharpes = np.array(sim_sharpes)
    p_value = ((sim_sharpes >= actual_sharpe).sum() + 1) / (n_sims + 1)
    
    print(f"\n--- 隨機模擬統計結果 ---")
    print(f"原始策略組合夏普值: {actual_sharpe:.4f}")
    print(f"隨機模擬平均夏普值: {sim_sharpes.mean():.4f}")
    print(f"P-value: {p_value:.12f}")

    if p_value < 0.05:
        print(">>> 結論：統計顯著 (p < 0.05)！你的策略邏輯確實具備優勢，非隨機致勝。")
    else:
        print(">>> 結論：未達顯著標準，目前的績效分佈與隨機亂買差異不大。")

    # ==========================================
    # 4. 產出 Excel 綜合報表
    # ==========================================
    try:
        print("\n正在產出整體回測與隨機驗證 Excel 報表...")
        
        # 4.1 整體組合績效表
        summary_df = pd.DataFrame(pf.stats()).reset_index()
        summary_df.columns = ['Metric', 'Original_Strategy']
        
        # 4.2 蒙地卡羅驗證表
        mc_summary = pd.DataFrame([
            {"Metric": "Monte Carlo - Simulations", "Value": n_sims},
            {"Metric": "Monte Carlo - Daily Entry Prob", "Value": round(entry_prob, 4)},
            {"Metric": "Monte Carlo - Daily Exit Prob", "Value": round(exit_prob, 4)},
            {"Metric": "Original Strategy Sharpe Ratio", "Value": round(actual_sharpe, 4)},
            {"Metric": "Random Benchmark Mean Sharpe Ratio", "Value": round(sim_sharpes.mean(), 4)},
            {"Metric": "P-value", "Value": round(p_value, 4)},
            {"Metric": "Statistical Significance (p < 0.05)", "Value": "Yes" if p_value < 0.05 else "No"}
        ])

        # 4.3 建立獨立標的績效表 (不考慮資金共享，用以觀察個別勝率)
        ind_pf = vbt.Portfolio.from_signals(
            close=close_df.droplevel(0, axis=1), 
            entries=entries_df.droplevel(0, axis=1), 
            exits=exits_df.droplevel(0, axis=1),
            fees=0.003, slippage=0.002, freq='1D', init_cash=100000
        )
        stats_list = [ind_pf[ticker].stats().rename(ticker) for ticker in ind_pf.wrapper.columns]
        ind_perf_df = pd.concat(stats_list, axis=1).T.reset_index().rename(columns={'index': 'Ticker'})

        # 寫入檔案
        with pd.ExcelWriter("backtest_summary_random.xlsx", engine='openpyxl') as writer:
            summary_df.to_excel(writer, sheet_name="Overall_Performance", index=False)
            mc_summary.to_excel(writer, sheet_name="Monte_Carlo_Benchmark", index=False)
            ind_perf_df.to_excel(writer, sheet_name="Individual_Tickers", index=False)
            
        print("Excel 報表產出成功：backtest_summary_random.xlsx")
        
    except Exception as e:
        print(f"產出報表時發生錯誤: {e}")

    print(f"\n資料運算總時間: {time.time() - start_time:.2f} 秒")

    # ==========================================
    # 5. 使用 Plotly 繪製蒙地卡羅黑底模擬圖 (修正版)
    # ==========================================
    print("\n正在繪製蒙地卡羅模擬資金曲線圖...")
    
    # 【關鍵修正】：使用 pd.concat 組合，並強制將欄位重新命名為唯一值 (sim_0 ~ sim_999)
    # 這樣能避免 vectorbt 預設的 'group' 名稱重複 1000 次，解決 Narwhals/Plotly 的 DuplicateError
    sim_equities_df = pd.concat(sim_equities, axis=1)
    sim_equities_df.columns = [f"sim_{i}" for i in range(len(sim_equities))]
    
    fig = go.Figure()

    # 5.1 繪製所有隨機模擬路徑 (極低透明度灰色，關閉 hover 以順暢渲染 1,000 條線)
    for col in sim_equities_df.columns:
        fig.add_trace(
            go.Scatter(
                x=sim_equities_df.index,
                y=sim_equities_df[col],
                mode='lines',
                line=dict(color='rgba(150, 150, 150, 0.04)', width=1), # 0.04 透明度適合黑底高密度
                showlegend=False,
                hoverinfo='skip' 
            )
        )

    # 5.2 繪製隨機模擬的平均路徑 (橘紅色虛線)
    sim_mean_equity = sim_equities_df.mean(axis=1)
    fig.add_trace(
        go.Scatter(
            x=sim_mean_equity.index,
            y=sim_mean_equity,
            mode='lines',
            name='隨機模擬平均值',
            line=dict(color='#FF851B', width=2, dash='dash')
        )
    )

    # 5.3 繪製原始策略資金曲線 (亮綠色粗線)
    fig.add_trace(
        go.Scatter(
            x=total_equity.index,
            y=total_equity,
            mode='lines',
            name='原始策略資金曲線',
            line=dict(color='#01FF70', width=3.5) # 螢光綠
        )
    )

    # 5.4 設定黑底與排版
    fig.update_layout(
        title=dict(
            text='蒙地卡羅隨機模擬 vs 原始策略資金曲線',
            font=dict(size=20, color='white')
        ),
        xaxis_title='日期',
        yaxis_title='投資組合總價值 ($)',
        template='plotly_dark',       # 官方暗色主題
        paper_bgcolor='#000000',      # 外框全黑
        plot_bgcolor='#000000',       # 繪圖區全黑
        hovermode='x unified',        # 對齊游標數據
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )

    fig.show()

if __name__ == "__main__":
    run_backtest()