import pandas as pd
import concurrent.futures
import time
import random
from dailysignal_utils.indicators import Indicators
import core_utils.yfinance_fetcher as yfinance_fetcher
import core_utils.Quadrant as Quadrant
from core_utils.strategy2 import QuadrantStrategy
import yfinance as yf
import numpy as np

def get_today_signal(ticker, global_vix):
    """獲取單一標的的最新信號與觸發原因 (加入強化防呆機制)

    計算相應指標，並產生信號。如果index格式異常，嘗試從DataFrame欄位中提取日期，確保不會因為日期格式問題導致整個流程崩潰。
    """
    try:
        time.sleep(random.uniform(0.5, 1.5)) 
        
        ind = Indicators(global_vix=global_vix)
        fetcher = yfinance_fetcher.YfinanceFetcher()
        ana = Quadrant.MarketQuadrantAnalyzer()
        
        df = fetcher.fetch(ticker, period="3y") 
        if df is None or df.empty:
            return None, f"{ticker}: yfinance 無法獲取資料 (DataFrame 為空)"

        df_ind = ind.get_indicators(df)
        df_final = ana.analyze_dataframe(df_ind)
        df_final = ana.attach_descriptions(df_final)
        
        if df_final.empty:
            return None, f"{ticker}: 指標計算後資料為空"

        entries, exits = QuadrantStrategy.generate_signals(df_final)     
        latest_idx = df_final.index[-1]

        if hasattr(latest_idx, 'strftime'):
            date_str = latest_idx.strftime('%Y-%m-%d')
        else:
            if 'Date' in df_final.columns:
                date_str = pd.to_datetime(df_final['Date'].iloc[-1]).strftime('%Y-%m-%d')
            elif 'date' in df_final.columns:
                date_str = pd.to_datetime(df_final['date'].iloc[-1]).strftime('%Y-%m-%d')
            else:
                date_str = str(latest_idx) 
                
        is_entry = entries.iloc[-1]
        is_exit = exits.iloc[-1]

        reason = df_final['description'].iloc[-1] if 'description' in df_final.columns else "無詳細描述"
        
        signal_type = "無信號"
        if is_entry:
            signal_type = "買進 (Buy)"
        elif is_exit:
            signal_type = "賣出 (Sell)"
            
        return {
            "Ticker": ticker,
            "Date": date_str,
            "Close": round(float(df_final['close'].iloc[-1]), 2),
            "Signal": signal_type,
            "Reason": reason
        }, None
        
    except Exception as e:
        return None, f"{ticker}: {str(e)}"

def main():
    '''篩選信號，並轉成 DataFrame 輸出'''
    try:
        with open('Mystocks_150.txt', encoding='utf-16') as f:
            ticker_list = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print("錯誤：找不到 'Mystocks_150.txt' 檔案。")
        return
    print("正在獲取大盤 VIX 數據...")

    try:
        vix_raw = yf.download("^VIX", period="3y", progress=False, auto_adjust=True)['Close']
        if isinstance(vix_raw, pd.DataFrame): # 處理新版 yfinance 可能回傳 DataFrame 的狀況
             vix_raw = vix_raw.squeeze()
             
        vix_p = vix_raw.rolling(252).rank(pct=True)
        if not vix_p.empty:
            global_vix = float(vix_p.dropna().iloc[-1])
            print(f"VIX 百分位數獲取成功: {global_vix:.2%}")
        else:
            global_vix = np.nan
            print("警告: VIX 資料為空。")

    except Exception as e:
        global_vix = np.nan
        print(f"警告: 獲取 VIX 失敗 ({e})，指標將以空值計算。")

    start_time = time.time()
    print(f"開始掃描 {len(ticker_list)} 檔標的之每日信號...")
    results = []
    errors = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=5) as executor:
        future_to_ticker = {executor.submit(get_today_signal, t, global_vix): t for t in ticker_list}
        
        for future in concurrent.futures.as_completed(future_to_ticker):
            res, err = future.result()
            if err:
                errors.append(err)
            else:
                results.append(res)
    
    if not results:
        print("\n[警告] 未能成功獲取任何標的的信號資料。")
    else:
        signal_report = pd.DataFrame(results)
        
        if 'Signal' in signal_report.columns:
            active_signals = signal_report[signal_report['Signal'] != "無信號"]

            print("\n--- 今日信號掃描結果 ---")
            if not active_signals.empty:
                print(active_signals.to_string(index=False))
                active_signals.to_excel("daily_signals_report.xlsx", index=False)
                print(f"\n已將 {len(active_signals)} 筆信號輸出至 daily_signals_report.xlsx")
            else:
                print("今日所有成功獲取資料的標的，均未觸發買進或賣出信號。")
        else:
            print("\n[錯誤] 獲取到的資料格式異常，缺少 'Signal' 欄位。")

    if errors:
        print("\n--- 執行過程中發生錯誤 (請檢查這裡的原因) ---")
        for error in errors:
            print(error)

    print(f"\n總執行時間: {time.time() - start_time:.2f} 秒")

    active_signals = signal_report[signal_report['Signal'] != "無信號"]

    print("\n--- 今日信號掃描結果 ---")
    import os

    if not active_signals.empty:
        print(active_signals.to_string(index=False))
        
        file_path = "daily_signals_report.xlsx"

        if os.path.exists(file_path):
            try:
                existing_df = pd.read_excel(file_path)
                final_df = pd.concat([existing_df, active_signals], ignore_index=True)
            except Exception as e:
                print(f"讀取舊檔案時發生錯誤（可能檔案損毀或格式不符），將直接覆蓋。錯誤資訊: {e}")
                final_df = active_signals
        else:
            final_df = active_signals
        final_df.to_excel(file_path, index=False)
        print(f"\n已將 {len(active_signals)} 筆信號新增至 {file_path}")
    else:
        print("今日所有標的均未觸發買進或賣出信號。")

    if errors:
        print("\n--- 執行過程中發生錯誤 ---")
        for error in errors:
            print(error)

    print(f"\n總執行時間: {time.time() - start_time:.2f} 秒")

if __name__ == "__main__":
    main()