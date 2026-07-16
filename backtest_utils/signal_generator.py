import pandas as pd
import concurrent.futures
import time
import random
from backtest_utils.indicatorsbt import Indicators
import core_utils.yfinance_fetcher as yfinance_fetcher
import core_utils.Quadrant as Quadrant
from core_utils.strategy_opt import QuadrantStrategy

class SignalGenerator:
    def __init__(self, ticker, start=None, end=None, period='3y', max_workers=5):
        self.ticker = ticker
        self.start = start
        self.end = end
        self.period = period
        self.max_workers = max_workers

    def quadrant_analysis(self, ticker): #傳入ticker，回傳DataFrame
        ind = Indicators()
        fetcher = yfinance_fetcher.YfinanceFetcher()
        ana = Quadrant.MarketQuadrantAnalyzer()
        
        is_cached = fetcher.check_cache(
            ticker, 
            start=self.start, 
            end=self.end, 
            period=self.period, 
            max_age_days=1
        )

        df = fetcher.fetch(ticker, start=self.start, end=self.end, period=self.period)
        df_ind = ind.get_indicators(df)
        df_final = ana.analyze_dataframe(df_ind)
        df_final = ana.attach_descriptions(df_final)

        return df_final, is_cached


    def fetch_signals(self, ticker): 
        '''
        Fetches the data for a single ticker and generates signals.
        '''
        try:
            df, is_cached = self.quadrant_analysis(ticker)
            
            if not is_cached:
                time.sleep(random.uniform(0.5, 1.5)) 
            
            entries, exits = QuadrantStrategy.generate_signals(df)
            return ticker, df['close'], entries, exits, None
        
        except Exception as e:
            return ticker, None, None, None, str(e)
        
    def generate_signals(self):
        '''
        Generates signals for all tickers in the list.
        '''

        start_time = time.time()    # 記錄開始時間
        
        try:
            with open('Mystocks.txt', encoding='utf-16') as f:
                ticker_list = [line.strip() for line in f if line.strip()]

                if not ticker_list:
                    print("錯誤：'Mystocks.txt' 檔案為空。")
                    return {}, {}, {}
                
                print(f"開始平行獲取 {len(ticker_list)} 檔標的資料與計算訊號...")

                dict_close = {}
                dict_entries = {}
                dict_exits = {}

            with concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(self.fetch_signals, t): t for t in ticker_list}  # 任務給多進程執行器
                
                for future in concurrent.futures.as_completed(futures):
                    ticker, close, entries, exits, error_msg = future.result()
                    if error_msg:
                        print(f"獲取 {ticker} 失敗: {error_msg}")
                    else:
                        dict_close[ticker] = close
                        dict_entries[ticker] = entries
                        dict_exits[ticker] = exits

            elsapsed_time = time.time() - start_time
            print(f"資料準備完成，耗時: {elsapsed_time:.2f} 秒")

            if not dict_close:
                print("未成功取得任何數據。")
                return {}, {}, {}
            
            return dict_close, dict_entries, dict_exits

        except FileNotFoundError:
            print("錯誤：找不到 'Mystocks_s.txt' 檔案。")
            return {}, {}, {}
        
        except Exception as e:
            print(f"發生錯誤: {e}")
            return {}, {}, {}

    def merge_dataframes(self, dict_close, dict_entries, dict_exits):
        '''
        Merges the close prices, entry signals, and exit signals into 2D DataFrames.
        '''

        start_time = time.time()    # 記錄開始時間
        elsapsed_time = time.time() - start_time
        print(f"合併資料為 2D DataFrame({elsapsed_time:.2f}秒)...")

        close_df = pd.DataFrame(dict_close)
        entries_df = pd.DataFrame(dict_entries)
        exits_df = pd.DataFrame(dict_exits)

        close_df = close_df.astype(float)   #轉換為 float，避免後續計算出現問題
        entries_df = entries_df.astype(bool)  #轉換為布林值，避免後續計算出現問題
        exits_df = exits_df.astype(bool)      #轉換為布林值，避免後續計算出現問題

        warmup_period = 225
        entries_df = entries_df.iloc[warmup_period:]
        exits_df = exits_df.iloc[warmup_period:]
        close_df = close_df.iloc[warmup_period:] # 確保價格資料也從暖機期結束後開始對齊

        return close_df, entries_df, exits_df
    
    def benchmark(self, start=None, end=None, period='3y'):
        '''
        Calculates the benchmark performance based on TWII.
        '''
        print("抓取 TWII (大盤) 資料作為 Benchmark...")
        try:
            fetcher = yfinance_fetcher.YfinanceFetcher()
            twii_df = fetcher.fetch("^TWII", start=start, end=end, period=period)
            twii_close = twii_df['close'].astype(float)
            benchmark_rets = twii_close.pct_change().dropna()
        except Exception as e:
            print(f"獲取 TWII 失敗: {e}")
            benchmark_rets = None

        return benchmark_rets
    
    # =========================================================================
    # 以下為新增：專門用於「參數高原優化」的快取與高速運算函數
    # =========================================================================

    def fetch_base_data(self, ticker): 
        '''
        只負責抓取資料與計算指標象限，不生成進出場訊號（供優化器預先抓資料使用）
        '''
        try:
            df, is_cached = self.quadrant_analysis(ticker)
            if not is_cached:
                time.sleep(random.uniform(0.5, 1.5)) 
            return ticker, df, None
        except Exception as e:
            return ticker, None, str(e)
            
    def prepare_all_data(self):
        '''
        一次性準備好所有標的的基礎資料（進參數優化迴圈前只會執行一次！）
        '''
        print("開始一次性預先計算所有標的的技術指標與象限資料...")
        dict_data = {}
        try:
            with open('Mystocks.txt', encoding='utf-16') as f:
                ticker_list = [line.strip() for line in f if line.strip()]

            if not ticker_list:
                print("錯誤：'Mystocks.txt' 檔案為空。")
                return {}

            with concurrent.futures.ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {executor.submit(self.fetch_base_data, t): t for t in ticker_list}
                for future in concurrent.futures.as_completed(futures):
                    ticker, df, error_msg = future.result()
                    if error_msg:
                        print(f"獲取 {ticker} 基礎資料失敗: {error_msg}")
                    elif df is not None:
                        dict_data[ticker] = df
                        
            print(f"成功將 {len(dict_data)} 檔標的的資料載入記憶體快取中！")
            return dict_data
            
        except Exception as e:
            print(f"預先準備資料時發生錯誤: {e}")
            return {}

    def generate_signals_from_cache(self, dict_data, **strat_params):
        '''
        在優化迴圈中被重複呼叫：直接從記憶體快取的 DataFrame，帶入新參數極速計算訊號
        '''
        dict_close = {}
        dict_entries = {}
        dict_exits = {}
        
        for ticker, df in dict_data.items():
            # 1. 既然策略回傳的是 Tuple，直接宣告兩個變數 (entries, exits) 來接收！
            entries, exits = QuadrantStrategy.generate_signals(df.copy(), **strat_params)
            
            # 2. close 價格直接從快取的 df 中提取，訊號則用剛剛接到的變數
            dict_close[ticker] = df['close']
            dict_entries[ticker] = entries
            dict_exits[ticker] = exits
            
        return self.merge_dataframes(dict_close, dict_entries, dict_exits)

if __name__ == "__main__":
    sg = SignalGenerator(ticker=None)
    dict_close, dict_entries, dict_exits = sg.generate_signals()
    close_df, entries_df, exits_df = sg.merge_dataframes(dict_close, dict_entries, dict_exits)
    print("Close DataFrame:")
    print(close_df.head())
    print("Entries DataFrame:")
    print(entries_df.head())
    print("Exits DataFrame:")
    print(exits_df.head())