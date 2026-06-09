#!/usr/bin/env python3
"""科技财经新闻采集器 - Claw1 核心代码"""

import json
import sys
import hashlib
import argparse
from datetime import datetime
from typing import List, Dict, Any

import akshare as ak
import pandas as pd


class TechNewsCollector:
    """采集科技板块新闻"""
    
    def __init__(self, keywords: List[str] = None):
        self.keywords = keywords or [
            "AI", "人工智能", "芯片", "半导体", "机器人", "算力",
            "数据中心", "云计算", "新能源车", "自动驾驶", "AI芯片"
        ]
    
    def fetch_stock_news(self, symbol: str) -> List[Dict]:
        """获取单个股票的财经新闻"""
        try:
            news_df = ak.stock_news_em(symbol=symbol)
            if news_df is not None and not news_df.empty:
                return news_df.to_dict('records')
        except Exception as e:
            print(f"获取 {symbol} 新闻失败: {e}")
        return []
    
    def filter_tech_news(self, all_news: List[Dict]) -> List[Dict]:
        """筛选科技相关新闻"""
        filtered = []
        for news in all_news:
            title = news.get('title', '') + news.get('content', '')
            if any(kw.lower() in title.lower() for kw in self.keywords):
                filtered.append(news)
        return filtered
    
    def extract_predictive_sentences(self, text: str) -> List[str]:
        """提取预测类语句"""
        prediction_keywords = ['预计', '有望', '可能', '将', '预期', '预测', '展望']
        sentences = text.split('。')
        result = []
        for sent in sentences:
            if any(kw in sent for kw in prediction_keywords):
                result.append(sent.strip())
        return result
    
    def clean_news(self, news: Dict) -> Dict:
        """清洗单条新闻，添加元数据"""
        title = news.get('title', '')
        content = news.get('content', '')
        
        cleaned = {
            "id": hashlib.md5(
                f"{title}{news.get('publish_time', '')}".encode()
            ).hexdigest()[:16],
            "timestamp": news.get('publish_time', datetime.now().isoformat()),
            "source": news.get('source', 'akshare'),
            "title": title,
            "content": content[:500],
            "url": news.get('url', ''),
            "stock_mentioned": self._extract_stocks(content + title),
            "is_fact": self._is_factual(content + title),
            "predictive_sentences": self.extract_predictive_sentences(content + title)
        }
        return cleaned
    
    def _extract_stocks(self, text: str) -> List[str]:
        """提取股票代码/名称"""
        import re
        # 6位数字的股票代码
        codes = re.findall(r'\d{6}', text)
        return list(set(codes))
    
    def _is_factual(self, text: str) -> bool:
        """判断是否事实性新闻"""
        fact_patterns = [
            r'\d+%', r'\d+亿', r'\d+万元', r'同比增长', r'环比增长',
            r'公告', r'签署', r'合同', r'中标', r'预增', r'预亏'
        ]
        import re
        return any(re.search(p, text) for p in fact_patterns)
    
    def collect(self) -> List[Dict]:
        """主采集流程"""
        print(f"[{datetime.now()}] 开始采集科技新闻...")
        
        # 获取热门科技股票列表
        tech_stocks = [
            '000977',  # 浪潮信息
            '002230',  # 科大讯飞
            '300750',  # 宁德时代
            '002475',  # 立讯精密
            '300308',  # 中际旭创
        ]
        
        all_news = []
        for code in tech_stocks:
            news = self.fetch_stock_news(code)
            all_news.extend(news)
            print(f"采集 {code}: {len(news)} 条")
        
        # 筛选科技新闻
        tech_news = self.filter_tech_news(all_news)
        print(f"筛选后科技新闻: {len(tech_news)} 条")
        
        # 清洗并添加元数据
        cleaned_news = [self.clean_news(news) for news in tech_news]
        
        # 去重
        seen_ids = set()
        unique_news = []
        for news in cleaned_news:
            if news['id'] not in seen_ids:
                seen_ids.add(news['id'])
                unique_news.append(news)
        
        print(f"去重后: {len(unique_news)} 条")
        return unique_news


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='data/news.json')
    parser.add_argument('--keywords', nargs='+')
    args = parser.parse_args()
    
    collector = TechNewsCollector(keywords=args.keywords)
    news_list = collector.collect()
    
    # 保存 JSON 文件
    output_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "total": len(news_list),
        "news": news_list
    }
    
    import os
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 采集完成，保存至 {args.output}")
    
    # 支持 Skill 调用：输出 JSON 到标准输出
    if not args.output:
        print(json.dumps(output_data, ensure_ascii=False))
    

if __name__ == "__main__":
    main()