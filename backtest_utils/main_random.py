import pandas as pd
import vectorbt as vbt
import concurrent.futures
import time
import random
import numpy as np
from backtest_utils.indicatorsbt import Indicators
import core_utils.yfinance_fetcher as yfinance_fetcher
import core_utils.Quadrant as Quadrant
from core_utils.strategy import QuadrantStrategy
import plotly.graph_objects as go

start = '2023-05-15'
end = '2026-05-15'
period = None

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
    """供多執行緒呼叫的獨立任務，加入隨機延遲避免被封鎖"""
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
    warmup_period = 225
    entries_df = entries_df.iloc[warmup_period:]
    exits_df = exits_df.iloc[warmup_period:]
    close_df = close_df.iloc[warmup_period:] # 確保價格資料也從暖機期結束後開始對齊

    # --- 新增：強制轉換資料型態，解決 Numba 編譯錯誤 ---
    # 將價格強制轉為浮點數 (float)
    close_df = close_df.astype(float)
    
    # 將訊號中的空值 (NaN) 視為不動作 (False)，並強制轉為布林值 (bool)
    entries_df = entries_df.fillna(False).astype(bool)
    exits_df = exits_df.fillna(False).astype(bool)

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
    )

    # --- 防呆過濾 ---
    trade_counts = pf.trades.count()
    valid_tickers = trade_counts[trade_counts > 0].index

    if len(valid_tickers) == 0:
        print("所有標的皆未產生任何交易，無法計算績效。")
        return

    valid_pf = pf[list(valid_tickers)]

    # ==========================================
    # 新增：隨機模擬驗證 (Monte Carlo Benchmark)
    # ==========================================
    print("\n執行隨機模擬驗證中 (Monte Carlo Benchmark)...")
    n_sims = 1000  # 測試次數
    
    actual_sharpe = valid_pf.sharpe_ratio().fillna(0).mean()
    entry_prob = entries_df.mean().mean() 
    exit_prob = exits_df.mean().mean()
    
    if pd.isna(exit_prob) or exit_prob == 0: 
        exit_prob = 0.1
        
    print(f"基準參數 -> 每日進場機率: {entry_prob:.4f}, 每日出場機率: {exit_prob:.4f}")
    
    sim_sharpes = []
    sim_equities = []  # <--- 新增：用來儲存每次模擬的整體資金曲線
    
    for i in range(n_sims):
        rand_pf = vbt.Portfolio.from_random_signals(
            close=close_df, 
            entry_prob=entry_prob,
            exit_prob=exit_prob,
            fees=0.003,
            init_cash=100000,
            slippage=0.002,
            freq='1D'
        )
        
        # --- 記錄夏普值 ---
        rand_trade_counts = rand_pf.trades.count()
        rand_valid_tickers = rand_trade_counts[rand_trade_counts > 0].index
        
        if len(rand_valid_tickers) > 0:
            sharpes = rand_pf[list(rand_valid_tickers)].sharpe_ratio()
            clean_sharpes = sharpes.replace([np.inf, -np.inf], np.nan).fillna(0)
            sim_sharpes.append(clean_sharpes.mean())
        else:
            sim_sharpes.append(0.0)
            
        # --- 新增：記錄該次模擬的「整體投資組合總價值」 ---
        sim_equities.append(rand_pf.value().sum(axis=1))
        
    sim_sharpes = np.array(sim_sharpes)
    p_value = ((sim_sharpes >= actual_sharpe).sum() + 1) / (n_sims + 1)
    
    print(f"\n--- 隨機模擬統計結果 ---")
    print(f"原始策略平均夏普值: {actual_sharpe:.4f}")
    print(f"隨機模擬平均夏普值: {sim_sharpes.mean():.4f}")
    print(f"P-value: {p_value:.4f}")

    if p_value < 0.05:
        print(">>> 結論：統計顯著 (p < 0.05)！你的策略邏輯確實具備優勢，非隨機致勝。")
    else:
        print(">>> 結論：未達顯著標準，目前的績效分佈與隨機亂買差異不大。")
    # ==========================================

    # 4. 產出報告
    try:
        stats_list = []
        for ticker in valid_pf.wrapper.columns:
            s = valid_pf[ticker].stats()
            s.name = ticker
            stats_list.append(s)
            
        final_perf_df = pd.concat(stats_list, axis=1).T
        final_perf_df.index.name = 'Ticker'
        final_perf_df.reset_index(inplace=True)
        final_perf_df.to_excel("backtest_summary_random.xlsx", index=False)
        print("\n個別標的回測結果已輸出至 backtest_summary_random.xlsx")
        
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

    # ==========================================
    # 新增：使用 Plotly 繪製蒙地卡羅黑底模擬圖
    # ==========================================
    print("正在繪製蒙地卡羅模擬資金曲線圖...")
    
    # 將所有模擬資金曲線轉換為 DataFrame (欄位為模擬次數，列為日期)
    sim_equities_df = pd.DataFrame(sim_equities).T
    
    fig = go.Figure()

    # 1. 繪製所有隨機模擬路徑 (灰色、極高透明度、不顯示滑鼠懸停資訊以提升效能)
    for col in sim_equities_df.columns:
        fig.add_trace(
            go.Scatter(
                x=sim_equities_df.index,
                y=sim_equities_df[col],
                mode='lines',
                line=dict(color='rgba(150, 150, 150, 0.05)', width=1), # 0.05 透明度
                showlegend=False,
                hoverinfo='skip' 
            )
        )

    # 2. 繪製隨機模擬的平均路徑 (橘紅色虛線)
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

    # 3. 繪製原始策略資金曲線 (亮綠色粗線，突出顯示)
    fig.add_trace(
        go.Scatter(
            x=total_equity.index,
            y=total_equity,
            mode='lines',
            name='原始策略資金曲線',
            line=dict(color='#01FF70', width=3.5) # 螢光綠
        )
    )

    # 4. 設定黑底與排版
    fig.update_layout(
        title=dict(
            text='蒙地卡羅隨機模擬 vs 原始策略資金曲線',
            font=dict(size=20, color='white')
        ),
        xaxis_title='日期',
        yaxis_title='投資組合總價值',
        template='plotly_dark',       # 套用官方暗色主題
        paper_bgcolor='#000000',      # 強制圖表外框全黑
        plot_bgcolor='#000000',       # 強制繪圖區域全黑
        hovermode='x unified',        # 游標移動時對齊顯示數據
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
    main()