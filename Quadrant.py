import pandas as pd
import numpy as np

class MarketQuadrantAnalyzer:
    def __init__(self):
        # 定義各象限的輸出文案
        self.quadrant_info = {
            1: {
                "title": "第一象限 (右上)：擴張 (+) + 高波動 (+) ——「狂熱末升段」",
                "features": "市場特徵： 景氣很好，價格不便宜，多空分歧大，洗盤頻繁。",
                "targets": "代表標的： 題材最熱、成交量暴增的強勢股。",
                "strategy": "策略： 動能策略。只要趨勢沒斷就追，嚴格執行移動止損。"
            },
            2: {
                "title": "第二象限 (左上)：收縮 (-) + 高波動 (+) ——「危機恐慌期」",
                "features": "市場特徵： 基本面轉壞，伴隨市場恐慌拋售。",
                "targets": "代表標的： 遭遇黑天鵝事件的大盤，或是產業崩跌期。",
                "strategy": "策略： 均值回歸或放空。利用超跌後的反彈獲利。"
            },
            3: {
                "title": "第三象限 (左下)：收縮 (-) + 低波動 (-) ——「蕭條築底期」",
                "features": "市場特徵： 市場極度冷清，乏人問津。",
                "targets": "代表標的： 傳統產業、高股息、或谷底盤整的週期股。",
                "strategy": "策略： 價值投資。尋找 P/B < 1 且現金流穩定的公司。"
            },
            4: {
                "title": "第四象限 (右下)：擴張 (+) + 低波動 (-) ——「金髮女孩」",
                "features": "市場特徵： 經濟穩步復甦，通膨適中，最舒服的送分題區間。",
                "targets": "代表標的： 進入穩定成長期的權值股、獲利翻正的科技股。",
                "strategy": "策略： 趨勢追蹤。量化模型最應優先捕捉的區間。"
            }
        }

    def analyze_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """執行向量化運算，計算 X, Y 分數與所屬象限"""
        result_df = df.copy()
        
        # 確保欄位名稱為小寫以對齊 Indicators 模組
        result_df.columns = [col.lower() for col in result_df.columns]
        
        # --- 計算 X 軸 (Expansion vs Contraction) --- [7,-6]
        x_score = pd.Series(0, index=result_df.index)
        
        # 價格與均線關係
        x_score += np.select([result_df['adj_price'] > result_df['ma200'], 
                              result_df['adj_price'] < result_df['ma200']], [2, -2], default=0)
        
        # 趨勢強度 ADX
        x_score += np.select([result_df['adx'] > 25, result_df['adx'] < 20], [1, -1], default=0)
        
        # 營收成長 YoY (優化：處理 NaN，加速成長 +2, 連續衰退 -2, 其餘 0)
        cond_yoy_up = (result_df['yoy_now'] > result_df['yoy_t1']) & (result_df['yoy_t1'] > result_df['yoy_t2'])
        cond_yoy_down = (result_df['yoy_now'] < result_df['yoy_t1']) & (result_df['yoy_t1'] < result_df['yoy_t2'])
        x_score += np.select([cond_yoy_up, cond_yoy_down], [2, -2], default=0)
        
        # 強弱指標 RSI
        x_score += np.select([result_df['rsi'] > 70, result_df['rsi'] > 50, result_df['rsi'] < 50], [2, 1, -1], default=0)
        
        result_df['x_score'] = x_score

        # --- 計算 Y 軸 (High Vol vs Low Vol) --- [6,-6]
        y_score = pd.Series(0, index=result_df.index)
        
        # 短期 ATR vs 長期平均
        y_score += np.where(result_df['atr'] > result_df['atr_60d_avg'], 2, -2)
        
        # 布林頻寬百分位
        y_score += np.select([result_df['bbw_percentile'] > 0.8, result_df['bbw_percentile'] < 0.2], [2, -2], default=0)
        
        # VIX 與 歷史波動率 (使用 0.75 作為高波動閾值)
        y_score += np.where(result_df['vix_percentile'] >= 0.75, 1, -1)
        y_score += np.where(result_df['hv_percentile'] >= 0.75, 1, -1)
        
        result_df['y_score'] = y_score

        # --- 判斷象限 ---
        cond_quadrant = [
            (result_df['x_score'] > 0) & (result_df['y_score'] > 0), # Q1
            (result_df['x_score'] < 0) & (result_df['y_score'] > 0), # Q2
            (result_df['x_score'] < 0) & (result_df['y_score'] < 0), # Q3
            (result_df['x_score'] > 0) & (result_df['y_score'] < 0)  # Q4
        ]
        result_df['quadrant'] = np.select(cond_quadrant, [1, 2, 3, 4], default=0)

        return result_df

    def attach_descriptions(self, df: pd.DataFrame) -> pd.DataFrame:
        """將象限代號轉換為文字描述的擴充方法"""
        # 統一檢查小寫欄位
        target_col = 'quadrant' if 'quadrant' in df.columns else 'Quadrant'
        if target_col not in df.columns:
            raise ValueError("請先執行 analyze_dataframe() 產生 quadrant 欄位")
            
        result_df = df.copy()
        default_text = "位於原點或座標軸上(0)，代表象限不明，不予操作。"
        
        # 批量映射文字
        for key in ['title', 'features', 'targets', 'strategy']:
            result_df[f'quadrant_{key}'] = result_df[target_col].map(
                lambda x: self.quadrant_info.get(x, {}).get(key, default_text)
            )
        return result_df