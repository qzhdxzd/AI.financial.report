#!/usr/bin/env python3
"""
科技财经新闻采集器 - Claw1
支持多数据源 + 关键词初筛 + 大模型精筛 + 相似度去重
"""

import json
import os
import hashlib
import re
import time
from datetime import datetime
from typing import List, Dict, Optional
from difflib import SequenceMatcher

import requests
from bs4 import BeautifulSoup

# 尝试导入 akshare
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("Warning: akshare 未安装")

# DeepSeek API 配置
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"

# ==================== 科技关键词库（用于初筛） ====================
TECH_KEYWORDS = [
    # 核心技术
    "AI", "人工智能", "大模型", "深度学习", "机器学习", "神经网络", "自然语言",
    "芯片", "半导体", "集成电路", "CPU", "GPU", "NPU", "FPGA", "ASIC",
    "算力", "云计算", "边缘计算", "数据中心", "服务器", "光模块",
    # 细分领域
    "自动驾驶", "无人驾驶", "智能驾驶", "机器人", "具身智能", "工业机器人",
    "新能源车", "电动车", "动力电池", "固态电池", "燃料电池", "储能",
    "5G", "6G", "通信", "物联网", "车联网",
    # 企业动态
    "英伟达", "NVIDIA", "AMD", "Intel", "英特尔", "华为", "中芯国际",
    "台积电", "腾讯", "阿里", "百度", "字节跳动", "OpenAI", "ChatGPT",
    "Copilot", "Gemini", "Claude", "DeepSeek"
]

# ==================== 辅助函数 ====================
def is_similar(title1: str, title2: str, threshold: float = 0.85) -> bool:
    """计算两个标题的相似度"""
    return SequenceMatcher(None, title1, title2).ratio() > threshold

def call_deepseek(prompt: str, max_tokens: int = 80) -> Optional[str]:
    """调用 DeepSeek API，返回文本或 None"""
    if not DEEPSEEK_API_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "response_format": {"type": "json_object"}
    }
    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=10)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        else:
            print(f"API 错误 {resp.status_code}: {resp.text[:200]}")
            return None
    except Exception as e:
        print(f"API 异常: {e}")
        return None

def llm_classify_news(title: str, content: str) -> tuple:
    """
    使用大模型判断新闻是否科技相关
    返回 (is_tech: bool, category: str, sentiment: str)
    """
    if not DEEPSEEK_API_KEY:
        return (False, "", "neutral")
    prompt = f"""判断以下新闻是否与科技相关（包括但不限于：AI、芯片、半导体、机器人、新能源、自动驾驶、科技公司财报、技术突破、行业政策）。
严格按JSON格式输出，只输出一个对象，不要有其他文字。
输出示例：{{"is_tech": true, "category": "AI", "sentiment": "positive"}}
新闻标题：{title}
新闻内容：{content[:300]}"""
    result = call_deepseek(prompt, max_tokens=80)
    if not result:
        return (False, "", "neutral")
    try:
        data = json.loads(result)
        is_tech = data.get("is_tech", False)
        category = data.get("category", "")
        sentiment = data.get("sentiment", "neutral")
        return (is_tech, category, sentiment)
    except json.JSONDecodeError:
        return (False, "", "neutral")

def keyword_filter(news: Dict) -> bool:
    """关键词预筛选（标题或内容包含任一科技关键词）"""
    title = news.get('title', '')
    content = news.get('content', '')
    full_text = f"{title} {content}".lower()
    return any(kw.lower() in full_text for kw in TECH_KEYWORDS)

def clean_text(text: str) -> str:
    """清洗文本，去除多余空白和特殊字符"""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# ==================== 数据源采集函数 ====================
def fetch_akshare_news(stock_codes: List[str]) -> List[Dict]:
    """从 AKShare 获取个股新闻"""
    if not AKSHARE_AVAILABLE:
        return []
    all_news = []
    for code in stock_codes:
        try:
            df = ak.stock_news_em(symbol=code)
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    news = {
                        "title": clean_text(row.get('title', '')),
                        "content": clean_text(row.get('content', ''))[:500],
                        "timestamp": row.get('publish_time', datetime.now().isoformat()),
                        "source": "AKShare",
                        "url": row.get('url', ''),
                    }
                    all_news.append(news)
            time.sleep(0.5)  # 避免请求过快
        except Exception as e:
            print(f"AKShare 采集 {code} 失败: {e}")
    return all_news

def fetch_cls_telegraph() -> List[Dict]:
    """从财联社电报页面获取快讯（备用方案）"""
    url = "https://www.cls.cn/telegraph"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        items = soup.select('.telegraph-item')
        news_list = []
        for item in items[:30]:  # 限制数量
            title_elem = item.select_one('.title')
            time_elem = item.select_one('.time')
            if title_elem:
                title = clean_text(title_elem.get_text())
                timestamp = time_elem.get_text() if time_elem else datetime.now().isoformat()
                news_list.append({
                    "title": title,
                    "content": title,
                    "timestamp": timestamp,
                    "source": "财联社",
                    "url": ""
                })
        return news_list
    except Exception as e:
        print(f"财联社采集失败: {e}")
        return []

def fetch_wallstreetcn_live() -> List[Dict]:
    """从华尔街见闻获取24小时快讯"""
    url = "https://api-prod.wallstreetcn.com/apiv1/content/lives?channel=global&limit=30"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://wallstreetcn.com/"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        items = data.get('data', {}).get('items', [])
        news_list = []
        for item in items:
            content = item.get('content_text', '')
            if content:
                news_list.append({
                    "title": clean_text(content[:100]),
                    "content": clean_text(content),
                    "timestamp": item.get('created_at', datetime.now().isoformat()),
                    "source": "华尔街见闻",
                    "url": f"https://wallstreetcn.com/live/{item.get('id', '')}"
                })
        return news_list
    except Exception as e:
        print(f"华尔街见闻采集失败: {e}")
        return []

def fetch_sina_news() -> List[Dict]:
    """从新浪财经获取科技新闻（可选）"""
    url = "https://finance.sina.com.cn/tech/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        news_list = []
        for link in soup.select('a[href*="/tech/"]')[:20]:
            title = clean_text(link.get_text())
            if title and len(title) > 5:
                news_list.append({
                    "title": title,
                    "content": title,
                    "timestamp": datetime.now().isoformat(),
                    "source": "新浪科技",
                    "url": link.get('href', '')
                })
        return news_list
    except Exception as e:
        print(f"新浪科技采集失败: {e}")
        return []

# ==================== 主采集器类 ====================
class TechNewsCollector:
    def __init__(self, use_mock: bool = False, use_llm_filter: bool = True, **kwargs):
        """
        use_mock: 强制使用模拟数据
        use_llm_filter: 是否启用大模型精筛（默认启用，若 API 无效则自动降级）
        """
        self.use_mock = use_mock
        self.use_llm_filter = use_llm_filter
        self.tech_stocks = [
            '000977', '002230', '300750', '002475', '300308',
            '688981', '002415', '000063'
        ]

    def get_mock_news(self) -> List[Dict]:
        """模拟科技新闻（用于演示或 API 不可用）"""
        now = datetime.now().isoformat()
        return [
            {
                "id": "mock1",
                "timestamp": now,
                "source": "模拟数据",
                "title": "英伟达发布新一代AI芯片H200，算力提升3倍",
                "content": "英伟达今日宣布推出新一代AI加速卡H200，预计将带动全球AI算力需求大幅增长。",
                "url": "",
                "stock_mentioned": ["英伟达", "AI芯片"],
                "is_fact": True,
                "predictive_sentences": ["预计将带动全球AI算力需求大幅增长"],
                "tech_category": "AI芯片",
                "tech_sentiment": "positive"
            },
            {
                "id": "mock2",
                "timestamp": now,
                "source": "模拟数据",
                "title": "中芯国际季度营收超预期，半导体行业回暖",
                "content": "中芯国际公告显示，三季度营收同比增长34%，超出市场预期。",
                "url": "",
                "stock_mentioned": ["中芯国际", "半导体"],
                "is_fact": True,
                "predictive_sentences": [],
                "tech_category": "半导体",
                "tech_sentiment": "positive"
            },
            {
                "id": "mock3",
                "timestamp": now,
                "source": "模拟数据",
                "title": "工信部：加快推动人工智能与实体经济深度融合",
                "content": "工信部相关负责人表示，下一步将出台更多政策支持AI产业发展。",
                "url": "",
                "stock_mentioned": ["AI", "人工智能"],
                "is_fact": True,
                "predictive_sentences": ["将出台更多政策支持AI产业发展"],
                "tech_category": "AI",
                "tech_sentiment": "positive"
            }
        ]

    def collect_from_all_sources(self) -> List[Dict]:
        """从所有配置的数据源采集原始新闻"""
        all_news = []

        # 1. AKShare 个股新闻
        print("采集 AKShare 个股新闻...")
        all_news.extend(fetch_akshare_news(self.tech_stocks))

        # 2. 财联社快讯
        print("采集财联社快讯...")
        all_news.extend(fetch_cls_telegraph())

        # 3. 华尔街见闻
        print("采集华尔街见闻...")
        all_news.extend(fetch_wallstreetcn_live())

        # 4. 新浪科技
        print("采集新浪科技...")
        all_news.extend(fetch_sina_news())

        print(f"原始采集总数: {len(all_news)}")
        return all_news

    def clean_news(self, news: Dict, category: str = "", sentiment: str = "neutral") -> Dict:
        """清洗单条新闻，添加元数据"""
        title = news.get('title', '')
        content = news.get('content', '')
        full_text = f"{title} {content}"
        unique_str = f"{title}{news.get('timestamp', '')}{news.get('source', '')}"
        news_id = hashlib.md5(unique_str.encode()).hexdigest()[:16]

        return {
            "id": news_id,
            "timestamp": news.get('timestamp', datetime.now().isoformat()),
            "source": news.get('source', '未知'),
            "title": title,
            "content": content[:500],
            "url": news.get('url', ''),
            "stock_mentioned": self._extract_stocks(full_text),
            "is_fact": self._is_factual(full_text),
            "predictive_sentences": self._extract_predictive(full_text),
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

    def collect(self) -> List[Dict]:
        """主采集流程：采集 → 初筛 → 精筛 → 去重 → 返回"""
        if self.use_mock:
            print("使用模拟数据模式")
            return self.get_mock_news()

        # 1. 多源采集
        raw_news = self.collect_from_all_sources()
        if not raw_news:
            print("未采集到任何新闻，回退模拟数据")
            return self.get_mock_news()

        # 2. 关键词预筛选
        tech_candidates = [n for n in raw_news if keyword_filter(n)]
        print(f"关键词预筛选后: {len(tech_candidates)} 条")

        if not tech_candidates:
            print("关键词预筛无结果，返回空")
            return []

        # 3. 大模型精筛（可选）
        if self.use_llm_filter and DEEPSEEK_API_KEY:
            print("开始大模型精筛...")
            llm_classified = []
            total = len(tech_candidates)
            for idx, news in enumerate(tech_candidates):
                print(f"LLM 筛选进度: {idx+1}/{total}")
                title = news.get('title', '')
                content = news.get('content', '')[:300]
                is_tech, cat, sent = llm_classify_news(title, content)
                if is_tech:
                    cleaned = self.clean_news(news, cat, sent)
                    llm_classified.append(cleaned)
            if llm_classified:
                tech_news = llm_classified
                print(f"大模型筛选得到 {len(tech_news)} 条")
            else:
                print("大模型未识别到科技新闻，使用关键词筛选结果")
                tech_news = [self.clean_news(n, "科技", "neutral") for n in tech_candidates]
        else:
            # 无 LLM 或 LLM 禁用，直接使用关键词结果
            tech_news = [self.clean_news(n, "科技", "neutral") for n in tech_candidates]

        # 4. 相似度去重（基于标题）
        unique_news = []
        for n in tech_news:
            if not any(is_similar(n['title'], ex['title']) for ex in unique_news):
                unique_news.append(n)
        print(f"去重后最终科技新闻: {len(unique_news)} 条")
        return unique_news


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='data/news.json')
    parser.add_argument('--mock', action='store_true', help='使用模拟数据')
    parser.add_argument('--no-llm', action='store_true', help='禁用大模型筛选')
    args = parser.parse_args()

    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    collector = TechNewsCollector(
        use_mock=args.mock,
        use_llm_filter=not args.no_llm
    )
    news_list = collector.collect()

    output_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "total": len(news_list),
        "news": news_list
    }
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"✅ 采集完成，保存至 {args.output}，共 {len(news_list)} 条")


if __name__ == "__main__":
    main()