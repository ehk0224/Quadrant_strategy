import pandas as pd
import time
from backtest_utils.indicatorsbt import Indicators
import core_utils.yfinance_fetcher as yfinance_fetcher
import core_utils.Quadrant as Quadrant
from core_utils.strategy_opt import QuadrantStrategy
import traceback

class SignalGenerator:
    def __init__(self, ticker=None, start=None, end=None, period='3y', max_workers=5):
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
       

    def generate_signals(self):
        """
        全向量化架構：一次傳入所有股票標的，整批抓取、整批運算
        """
        start_time = time.time()
        
        try:
            # 1. 讀取股票清單
            with open('Mystocks.txt', encoding='utf-16') as f:
                ticker_list = [line.strip() for line in f if line.strip()]

            if not ticker_list:
                print("錯誤：'Mystocks.txt' 檔案為空。")
                return None, None, None
                
            print(f"開始批量獲取 {len(ticker_list)} 檔標的資料與執行全矩陣運算...")

            # 2. 整批抓取 (假設你的 fetcher 底層是用 yfinance.download(ticker_list))
            # 抓下來直接就會是 [feature, ticker] 的 MultiIndex DataFrame
            fetcher = yfinance_fetcher.YfinanceFetcher()
            df_raw = fetcher.fetch(ticker_list, start=self.start, end=self.end, period=self.period)
            
            if df_raw is None or df_raw.empty:
                print("未成功取得任何數據。")
                return None, None, None

            # 3. 整批計算技術指標 (一次算完所有標的)
            ind = Indicators()
            df_ind = ind.get_indicators(df_raw)

            # 4. 整批執行象限分析與文字綁定 (一次算完所有標的)
            ana = Quadrant.MarketQuadrantAnalyzer()
            df_final = ana.analyze_dataframe(df_ind)
            df_final = ana.attach_descriptions(df_final)

            # 5. 整批產出進出場訊號 (一次算完所有標的)
            # 假設 Strategy 也能接收 MultiIndex DataFrame 並回傳同樣寬度的矩陣
            entries_df, exits_df = QuadrantStrategy.generate_signals(df_final)

            # 6. 提取價格矩陣並切除 Warmup 暖機期 (例如前 225 天)
            warmup_period = 225
            
            # 優先抓取 adj_price，若無則抓 close
            if 'adj_price' in df_final.columns.get_level_values(0):
                close_df = df_final.xs('adj_price', axis=1, level=0)
            else:
                close_df = df_final.xs('close', axis=1, level=0)

            # 加上第一層標籤，標準化為 MultiIndex 輸出
            close_df = close_df.iloc[warmup_period:]
            entries_df = entries_df.iloc[warmup_period:]
            exits_df = exits_df.iloc[warmup_period:]

            close_df.columns = pd.MultiIndex.from_product([['adj_price'], close_df.columns], names=['feature', 'ticker'])
            entries_df.columns = pd.MultiIndex.from_product([['entries'], entries_df.columns], names=['feature', 'ticker'])
            exits_df.columns = pd.MultiIndex.from_product([['exits'], exits_df.columns], names=['feature', 'ticker'])

            elapsed_time = time.time() - start_time
            print(f"全矩陣運算與訊號產生完成！總耗時: {elapsed_time:.2f} 秒")

            return close_df, entries_df, exits_df
        
        except Exception as e:
            # 💡 強制印出「完整追蹤行號」，不要只印 e！
            print("❌ 程式在 try 區塊內部發生致命錯誤，報錯行號與細節如下：")
            print(traceback.format_exc())  
            return None, None, None

        except FileNotFoundError:
            print("錯誤：找不到 'Mystocks.txt' 檔案。")
            return None, None, None
        except Exception as e:
            print(f"發生錯誤: {e}")
            return None, None, None

    
    def benchmark(self):
        '''
        Calculates the benchmark performance based on TWII.
        '''
        print("抓取 TWII (大盤) 資料作為 Benchmark...")
        try:
            fetcher = yfinance_fetcher.YfinanceFetcher()
            twii_df = fetcher.fetch("^TWII", start=self.start, end=self.end, period=self.period)
            twii_close = twii_df['close'].astype(float)
            benchmark_rets = twii_close.pct_change().dropna()
            benchmark_rets.columns = pd.MultiIndex.from_tuples([('return', '^TWII')])

            return benchmark_rets
        
        except Exception as e:
            print(f"獲取 TWII 失敗: {e}")
        return None
    

    def pure_for_signal(self, use_parquet=True):
        start_time = time.time()
        
        try:
            with open('Mystocks.txt', encoding='utf-16') as f:
                ticker_list = [line.strip() for line in f if line.strip()]

            if not ticker_list:
                print("錯誤：'Mystocks.txt' 檔案為空。")
                return None, None, None
                
            print(f"開始批量獲取 {len(ticker_list)} 檔標的資料與執行全矩陣運算...")

            fetcher = yfinance_fetcher.YfinanceFetcher()
            df_raw = fetcher.fetch(ticker_list, start=self.start, end=self.end, period=self.period)
            
            if df_raw is None or df_raw.empty:
                print("未成功取得任何數據。")
                return None, None, None

            ind = Indicators()
            df_ind = ind.get_indicators(df_raw)
            ana = Quadrant.MarketQuadrantAnalyzer()
            df_final = ana.analyze_dataframe(df_ind)

            elapsed_time = time.time() - start_time
            print(f"評分計算完成！總耗時: {elapsed_time:.2f} 秒")

            ext = 'parquet' if use_parquet else 'csv'
            cache_path = f"data_cache_matrix.{ext}"
            
            self.save_to_cache(df_final, cache_path, use_parquet)

            return df_final

        except Exception as e:
            # 💡 強制印出「完整追蹤行號」，不要只印 e！
            print("❌ 程式在 try 區塊內部發生致命錯誤，報錯行號與細節如下：")
            print(traceback.format_exc())  
            return None, None, None

        except FileNotFoundError:
            print("錯誤：找不到 'Mystocks.txt' 檔案。")
            return None, None, None
        except Exception as e:
            print(f"發生錯誤: {e}")
            return None, None, None
        
    def save_to_cache(self, df, cache_path, use_parquet=True):
        '''
        Save the DataFrame to cache in either Parquet or CSV format.
        '''
        try:
            if use_parquet:
                df.to_parquet(cache_path, index=True)
            else:
                df.to_csv(cache_path, encoding='utf-8-sig', index=True)

        except Exception as e:
            print(f"⚠️ 儲存快取失敗: {e}")


if __name__ == "__main__":
    sg = SignalGenerator(start='2023-05-15', end='2026-05-15')
    df = sg.pure_for_signal()
    print(df.head())
    