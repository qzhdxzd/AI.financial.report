#!/usr/bin/env python3
"""
科技财经新闻采集器 - Claw1 核心代码
支持真实 akshare 采集和模拟数据模式，可在 ModelScope 创空间中运行
"""

import json
import os
import hashlib
import argparse
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

# 尝试导入 akshare，若失败则使用模拟模式
try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except ImportError:
    AKSHARE_AVAILABLE = False
    print("Warning: akshare 未安装，将使用模拟数据模式")

class TechNewsCollector:
    """采集科技板块新闻，支持真实采集与模拟数据"""

    def __init__(self, keywords: List[str] = None, use_mock: bool = False):
        """
        :param keywords: 科技关键词列表，用于筛选新闻
        :param use_mock: 是否强制使用模拟数据（即使 akshare 可用）
        """
        self.keywords = keywords or [
            "AI", "人工智能", "芯片", "半导体", "机器人", "算力", "数据中心",
            "云计算", "新能源车", "自动驾驶", "AI芯片", "GPU", "大模型", "算法",
            "英伟达", "AMD", "英特尔", "华为", "腾讯", "阿里", "字节", "OpenAI"
        ]
        self.use_mock = use_mock or not AKSHARE_AVAILABLE

        # 重点关注科技股代码（A股）
        self.tech_stocks = [
            '000977',  # 浪潮信息
            '002230',  # 科大讯飞
            '300750',  # 宁德时代
            '002475',  # 立讯精密
            '300308',  # 中际旭创
            '688981',  # 中芯国际
            '002415',  # 海康威视
            '000063',  # 中兴通讯
        ]

    def fetch_stock_news(self, symbol: str) -> List[Dict]:
        """获取单个股票的财经新闻（兼容新版 akshare）"""
        if self.use_mock:
            return []

        try:
            # 新版 akshare 可能使用 stock_news_em 接口
            # 增加重试与超时
            news_df = ak.stock_news_em(symbol=symbol, retry_count=2, pause=0.5)
            if news_df is not None and not news_df.empty:
                return news_df.to_dict('records')
        except Exception as e:
            print(f"采集 {symbol} 新闻失败: {e}")
        return []

    def filter_tech_news(self, all_news: List[Dict]) -> List[Dict]:
        """筛选科技相关新闻（基于关键词）"""
        filtered = []
        for news in all_news:
            title = news.get('title', '')
            content = news.get('content', '')
            text = f"{title} {content}".lower()
            if any(kw.lower() in text for kw in self.keywords):
                filtered.append(news)
        return filtered

    def extract_predictive_sentences(self, text: str) -> List[str]:
        """提取预测类语句（含“预计/有望/可能/将/预期”等）"""
        prediction_keywords = ['预计', '有望', '可能', '将', '预期', '预测', '展望']
        # 按句号、分号、感叹号分割
        sentences = re.split(r'[。；！]', text)
        result = []
        for sent in sentences:
            sent = sent.strip()
            if any(kw in sent for kw in prediction_keywords) and len(sent) > 5:
                result.append(sent)
        return result

    def _is_factual(self, text: str) -> bool:
        """判断是否事实性新闻（包含具体数字、金额、合同等）"""
        fact_patterns = [
            r'\d+%', r'\d+亿', r'\d+万元', r'同比增长', r'环比增长',
            r'公告', r'签署', r'合同', r'中标', r'预增', r'预亏',
            r'\d+\.\d+', r'\d{4}-\d{2}-\d{2}'
        ]
        return any(re.search(p, text) for p in fact_patterns)

    def _extract_stocks(self, text: str) -> List[str]:
        """提取文本中可能的股票代码或简称（简易实现）"""
        codes = re.findall(r'\b[0-9]{6}\b', text)
        # 可扩展常见股票名称
        name_keywords = ['英伟达', 'AMD', '英特尔', '华为', '腾讯', '阿里', '字节']
        found_names = [name for name in name_keywords if name in text]
        return list(set(codes + found_names))

    def clean_news(self, news: Dict) -> Dict:
        """清洗单条新闻，添加元数据"""
        title = news.get('title', '')
        content = news.get('content', '')
        full_text = f"{title} {content}"

        # 生成唯一ID
        unique_str = f"{title}{news.get('publish_time', '')}{news.get('source', '')}"
        news_id = hashlib.md5(unique_str.encode()).hexdigest()[:16]

        cleaned = {
            "id": news_id,
            "timestamp": news.get('publish_time', datetime.now().isoformat()),
            "source": news.get('source', 'akshare'),
            "title": title,
            "content": content[:500],  # 限制长度
            "url": news.get('url', ''),
            "stock_mentioned": self._extract_stocks(full_text),
            "is_fact": self._is_factual(full_text),
            "predictive_sentences": self.extract_predictive_sentences(full_text)
        }
        return cleaned

    def get_mock_news(self) -> List[Dict]:
        """生成模拟新闻数据（用于演示或无网络环境）"""
        return [
            {
                "id": "mock1",
                "timestamp": datetime.now().isoformat(),
                "source": "模拟财经",
                "title": "英伟达发布新一代AI芯片，算力提升3倍",
                "content": "英伟达今日宣布推出新一代AI加速卡，预计将带动全球AI算力需求大幅增长。",
                "url": "",
                "stock_mentioned": ["英伟达", "AI"],
                "is_fact": True,
                "predictive_sentences": ["预计将带动全球AI算力需求大幅增长"]
            },
            {
                "id": "mock2",
                "timestamp": datetime.now().isoformat(),
                "source": "模拟财经",
                "title": "半导体行业传出利好，多家公司财报超预期",
                "content": "台积电、中芯国际等芯片代工厂季度营收同比增长超过20%，行业景气度回升。",
                "url": "",
                "stock_mentioned": ["中芯国际", "半导体"],
                "is_fact": True,
                "predictive_sentences": []
            },
            {
                "id": "mock3",
                "timestamp": datetime.now().isoformat(),
                "source": "模拟财经",
                "title": "工信部：加快推进人工智能与实体经济深度融合",
                "content": "工信部相关负责人表示，下一步将出台更多政策支持AI产业发展。",
                "url": "",
                "stock_mentioned": ["AI", "人工智能"],
                "is_fact": True,
                "predictive_sentences": ["将出台更多政策支持AI产业发展"]
            }
        ]

    def collect(self) -> List[Dict]:
        """主采集流程：返回清洗后的新闻列表"""
        if self.use_mock:
            print(f"[{datetime.now()}] 使用模拟数据模式")
            return self.get_mock_news()

        print(f"[{datetime.now()}] 开始采集科技新闻...")
        all_news = []

        for code in self.tech_stocks:
            news = self.fetch_stock_news(code)
            print(f"采集 {code}: {len(news)} 条")
            all_news.extend(news)

        print(f"总新闻数: {len(all_news)}")
        tech_news = self.filter_tech_news(all_news)
        print(f"筛选后科技新闻: {len(tech_news)} 条")

        cleaned_news = [self.clean_news(news) for news in tech_news]

        # 去重（基于 id）
        seen = set()
        unique_news = []
        for news in cleaned_news:
            if news['id'] not in seen:
                seen.add(news['id'])
                unique_news.append(news)

        print(f"去重后: {len(unique_news)} 条")
        return unique_news


def clean_old_data(data_dir: str = 'data', keep_days: int = 30):
    """清理旧数据文件（可选）"""
    if not os.path.exists(data_dir):
        return
    cutoff = datetime.now() - timedelta(days=keep_days)
    for f in glob.glob(os.path.join(data_dir, 'news_*.json')):
        try:
            date_str = f.split('_')[-1].replace('.json', '')
            file_date = datetime.strptime(date_str, '%Y-%m-%d')
            if file_date < cutoff:
                os.remove(f)
                print(f"Removed old file: {f}")
        except:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', '-o', default='data/news.json',
                        help='输出 JSON 文件路径')
    parser.add_argument('--mock', action='store_true',
                        help='强制使用模拟数据')
    parser.add_argument('--keywords', nargs='+',
                        help='自定义科技关键词')
    args = parser.parse_args()

    # 确保输出目录存在
    os.makedirs(os.path.dirname(args.output), exist_ok=True)

    collector = TechNewsCollector(keywords=args.keywords, use_mock=args.mock)
    news_list = collector.collect()

    # 构建输出数据
    output_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "total": len(news_list),
        "news": news_list
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    print(f"✅ 采集完成，保存至 {args.output}")

    # 如果直接调用，也输出到标准输出（方便调试）
    if not args.output:
        print(json.dumps(output_data, ensure_ascii=False))


if __name__ == "__main__":
    # 允许导入 timedelta 和 glob（用于清理旧数据，此处简化）
    from datetime import timedelta
    import glob
    main()