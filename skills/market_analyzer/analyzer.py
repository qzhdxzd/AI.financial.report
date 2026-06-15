#!/usr/bin/env python3
"""市场分析器 - 整合新闻与股票数据"""

import json
import os
from datetime import datetime
from typing import List, Dict

import akshare as ak
import numpy as np


class MarketAnalyzer:
    """市场数据与新闻整合分析"""
    
    def analyze(self, news_data: Dict) -> Dict:
        """分析新闻并生成板块情绪评分"""
        news_list = news_data.get('news', [])
        
        # 按股票/板块聚合情绪
        sector_scores = {}
        
        for news in news_list:
            is_fact = news.get('is_fact', False)
            # 兼容 collector 输出的 'predictions' 与旧版 'predictive_sentences' 字段名
            pred_sentences = news.get('predictions', news.get('predictive_sentences', []))
            
            # 基础分值
            base_score = 0
            if pred_sentences:
                base_score += 0.1 * min(len(pred_sentences), 3)
            if is_fact:
                base_score += 0.2
            
            # 获取股票代码
            stocks = news.get('stock_mentioned', [])
            for stock in stocks:
                sector = stock[:3]  # 按行业分类
                if sector not in sector_scores:
                    sector_scores[sector] = {'scores': [], 'news_count': 0}
                sector_scores[sector]['scores'].append(base_score)
                sector_scores[sector]['news_count'] += 1
        
        # 计算平均情绪分数
        sector_summary = {}
        for sector, data in sector_scores.items():
            sector_summary[sector] = {
                "score": np.mean(data['scores']) if data['scores'] else 0,
                "news_count": data['news_count'],
                "sentiment": "positive" if np.mean(data['scores']) > 0.15 else 
                            "negative" if np.mean(data['scores']) < 0.05 else "neutral"
            }
        
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_news": len(news_list),
            "sector_scores": sector_summary,
            "top_news": news_list[:5]
        }


def main():
    # 读取 Claw1 生成的新闻数据
    try:
        with open('data/news.json', 'r', encoding='utf-8') as f:
            news_data = json.load(f)
    except FileNotFoundError:
        news_data = {"news": []}
    
    analyzer = MarketAnalyzer()
    result = analyzer.analyze(news_data)
    
    # 保存分析结果
    with open('data/analysis.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"分析完成，情绪评分已保存")


if __name__ == "__main__":
    main()