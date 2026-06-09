#!/usr/bin/env python3
"""科技财经新闻采集器 - Claw1 - 纯大模型智能筛选"""

import json
import os
import hashlib
import re
from datetime import datetime
from typing import List, Dict
import requests

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

def call_deepseek(prompt: str, max_tokens: int = 50) -> str:
    if not DEEPSEEK_API_KEY:
        return ""
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0.1}
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        else:
            print(f"API 错误: {resp.status_code}")
            return ""
    except Exception as e:
        print(f"API 异常: {e}")
        return ""

def llm_classify_news(title: str, content: str) -> tuple:
    if not DEEPSEEK_API_KEY:
        return False, "", "neutral"
    prompt = f"""判断以下新闻是否与科技股（AI、芯片、半导体、机器人、新能源、自动驾驶）相关。
如果相关，输出 JSON：{{"is_tech": true, "category": "具体板块", "sentiment": "positive/negative/neutral"}}
否则输出 {{"is_tech": false}}
新闻标题：{title}
新闻内容：{content[:300]}"""
    result = call_deepseek(prompt, max_tokens=80)
    try:
        data = json.loads(result)
        return data.get("is_tech", False), data.get("category", ""), data.get("sentiment", "neutral")
    except:
        return "true" in result.lower(), "", "neutral"

class TechNewsCollector:
    def __init__(self, use_mock: bool = False, **kwargs):
        # 接受额外参数（如 use_llm_filter）并忽略，保持兼容
        self.use_mock = use_mock
        self.tech_stocks = ['000977', '002230', '300750', '002475', '300308', '688981', '002415', '000063']

    def fetch_stock_news(self, symbol: str) -> List[Dict]:
        if self.use_mock:
            return []
        try:
            import akshare as ak
            df = ak.stock_news_em(symbol=symbol)
            return df.to_dict('records') if df is not None and not df.empty else []
        except Exception as e:
            print(f"采集 {symbol} 失败: {e}")
            return []

    def clean_news(self, news: Dict, category: str = "", sentiment: str = "neutral") -> Dict:
        title = news.get('title', '')
        content = news.get('content', '')
        uid = hashlib.md5(f"{title}{news.get('publish_time', '')}".encode()).hexdigest()[:16]
        return {
            "id": uid,
            "timestamp": news.get('publish_time', datetime.now().isoformat()),
            "source": news.get('source', 'akshare'),
            "title": title,
            "content": content[:500],
            "url": news.get('url', ''),
            "stock_mentioned": self._extract_stocks(title + content),
            "is_fact": self._is_factual(title + content),
            "predictive_sentences": self._extract_predictive(title + content),
            "tech_category": category,
            "tech_sentiment": sentiment
        }

    def _extract_stocks(self, text: str) -> List[str]:
        codes = re.findall(r'\b[0-9]{6}\b', text)
        names = ['英伟达', 'AMD', '英特尔', '华为', '腾讯', '阿里', '中芯国际']
        found = [n for n in names if n in text]
        return list(set(codes + found))

    def _is_factual(self, text: str) -> bool:
        return bool(re.search(r'\d+%|\d+亿|同比增长|公告|合同|中标', text))

    def _extract_predictive(self, text: str) -> List[str]:
        keywords = ['预计', '有望', '可能', '将', '预期']
        sents = re.split(r'[。；！]', text)
        return [s.strip() for s in sents if any(k in s for k in keywords) and len(s) > 5]

    def get_mock_news(self) -> List[Dict]:
        now = datetime.now().isoformat()
        return [
            {"id": "mock1", "timestamp": now, "source": "模拟", "title": "英伟达发布新一代AI芯片，算力提升3倍", "content": "英伟达今日宣布推出新一代AI加速卡，预计将带动全球AI算力需求大幅增长。", "stock_mentioned": ["英伟达"], "is_fact": True, "predictive_sentences": ["预计将带动..."]},
            {"id": "mock2", "timestamp": now, "source": "模拟", "title": "中芯国际季度营收超预期", "content": "中芯国际营收同比增长34%，半导体行业回暖。", "stock_mentioned": ["中芯国际"], "is_fact": True, "predictive_sentences": []},
            {"id": "mock3", "timestamp": now, "source": "模拟", "title": "工信部加快推动AI与实体经济融合", "content": "将出台更多政策支持AI产业发展。", "stock_mentioned": ["AI"], "is_fact": True, "predictive_sentences": []}
        ]

    def collect(self) -> List[Dict]:
        if self.use_mock:
            print("使用模拟数据模式")
            return self.get_mock_news()
        print("开始采集真实新闻...")
        all_news = []
        for code in self.tech_stocks:
            news = self.fetch_stock_news(code)
            print(f"{code}: {len(news)} 条")
            all_news.extend(news)
        print(f"总新闻数: {len(all_news)}")
        tech_news = []
        for i, news in enumerate(all_news):
            print(f"LLM 筛选进度: {i+1}/{len(all_news)}")
            title = news.get('title', '')
            content = news.get('content', '')[:300]
            is_tech, cat, sent = llm_classify_news(title, content)
            if is_tech:
                tech_news.append(self.clean_news(news, cat, sent))
        # 去重
        seen = set()
        unique = []
        for n in tech_news:
            if n['id'] not in seen:
                seen.add(n['id'])
                unique.append(n)
        print(f"最终科技新闻: {len(unique)} 条")
        return unique

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='data/news.json')
    parser.add_argument('--mock', action='store_true')
    args = parser.parse_args()
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    collector = TechNewsCollector(use_mock=args.mock)
    news_list = collector.collect()
    output = {"date": datetime.now().strftime("%Y-%m-%d"), "timestamp": datetime.now().isoformat(), "total": len(news_list), "news": news_list}
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"✅ 保存至 {args.output}")

if __name__ == "__main__":
    main()