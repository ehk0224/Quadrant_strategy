import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import os
from yfinance_fetcher import Yfinance_fetcher
from indicators import Indicators
from Quadrant import MarketQuadrantAnalyzer


def process_single_stock(ticker, Yfinance_fetcher, indicators_tool, analyzer_tool):
    """
    使用你自定義的 Fetcher 抓取資料
    """
    try:
        # 1. 使用你的 Fetcher 抓取資料 (它應該已經幫你對齊了名稱：ticker, open, close, adj_price 等)
        # 這裡假設你的 fetcher 有一個 fetch 方法
        df = Yfinance_fetcher.fetch(ticker, start="2024-01-01") 
        
        if df is None or df.empty:
            return None
        
        # 2. 計算指標 (這裡會用到我們上次改好的，會自動處理 adj_price 的 Indicators)
        df = indicators_tool.get_indicators(df)
        
        # 3. 象限分析
        df = analyzer_tool.analyze_dataframe(df)
        df = analyzer_tool.attach_descriptions(df)
        
        # 4. 只回傳最新的一筆數據
        return df.iloc[[-1]] 
    except Exception as e:
        print(f"處理 {ticker} 時發生錯誤: {e}")
        return None

def main():
    # 初始化你的 Fetcher 與分析工具
    # fetcher = FinanceFetcher() # 初始化你的抓取器
    ind = Indicators()
    ana = MarketQuadrantAnalyzer()
    
    # 讀取股票清單
    if not os.path.exists('Mystocks.txt'):
        print("錯誤：找不到 Mystocks.txt")
        return
        
    with open('Mystocks.txt', 'r') as f:
        tickers = [line.strip() for line in f.readlines() if line.strip()]

    # 預先抓取一次 VIX (這部分仍建議保留，因為它是全域指標)
    print("正在獲取總體經濟數據 (VIX)...")
    dummy_df = pd.DataFrame({'close': [0], 'high': [0], 'low': [0]})
    ind.get_vix_percentile(dummy_df)

    final_results = []

    print(f"開始處理 {len(tickers)} 檔標的 (使用自定義 Fetcher)...")

    # 多執行緒執行
    with ThreadPoolExecutor(max_workers=8) as executor:
        # 將 fetcher 傳入處理函數
        future_to_ticker = {executor.submit(process_single_stock, t, Yfinance_fetcher(), ind, ana): t for t in tickers}
        
        for future in tqdm(as_completed(future_to_ticker), total=len(tickers), desc="分析中"):
            res = future.result()
            if res is not None:
                final_results.append(res)

    if not final_results:
        print("沒有結果產出。")
        return

    # 儲存 Excel 與 TXT (邏輯同前)
    report_df = pd.concat(final_results, ignore_index=True)
    report_df.to_excel("Market_Quadrant_Report.xlsx", index=False)
    
    # 儲存 Q1 與 Q4 清單
    for q in [1, 4]:
        q_list = report_df[report_df['quadrant'] == q]['ticker'].tolist()
        with open(f'Mystocks_Q{q}.txt', 'w') as f:
            f.write('\n'.join(q_list))

    print("✅ 任務完成！Excel 與分類清單已儲存。")

if __name__ == "__main__":
    main()