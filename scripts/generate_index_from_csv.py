#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate Stock Index from CSV File

Input: logs/stock_basic_*.csv (AkShare format)
Output: apps/dsa-web/public/stocks.index.json

Usage:
    python3 scripts/generate_index_from_csv.py
"""

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import List, Dict, Any

# Add the project root to sys.path.
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from pypinyin import lazy_pinyin, Style
    PYPINYIN_AVAILABLE = True
except ImportError:
    PYPINYIN_AVAILABLE = False
    print("[Warning] pypinyin not available, pinyin fields will be empty")
    print("[Info] Install with: pip install pypinyin")


def load_csv_data(csv_path: Path) -> List[Dict[str, Any]]:
    """
    Load stock data from CSV file

    Args:
        csv_path: CSV file path

    Returns:
        List of stock data
    """
    stocks = []

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        for row in reader:
            ts_code = row['ts_code'].strip()
            symbol = row['symbol'].strip()
            name = row['name'].strip()

            # Skip invalid rows.
            if not ts_code or not symbol or not name:
                continue

            stocks.append({
                'ts_code': ts_code,
                'symbol': symbol,
                'name': name,
                'area': row.get('area', ''),
                'industry': row.get('industry', ''),
                'list_date': row.get('list_date', ''),
            })

    return stocks


def generate_pinyin(name: str) -> tuple:
    """
    Generate pinyin for stock name

    Args:
        name: Stock name

    Returns:
        Tuple of (pinyin_full, pinyin_abbr)
    """
    if not PYPINYIN_AVAILABLE:
        return (None, None)

    try:
        normalized_name = normalize_name_for_pinyin(name)

        # Full pinyin spelling.
        py_full = lazy_pinyin(normalized_name, style=Style.NORMAL)
        pinyin_full = ''.join(py_full)

        # Pinyin abbreviation.
        py_abbr = lazy_pinyin(normalized_name, style=Style.FIRST_LETTER)
        pinyin_abbr = ''.join(py_abbr)

        return (pinyin_full, pinyin_abbr)
    except Exception as e:
        print(f"[Warning] Failed to generate pinyin for {name}: {e}")
        return (None, None)


def normalize_name_for_pinyin(name: str) -> str:
    """
    Normalize stock name to avoid special prefixes and full-width characters polluting pinyin index

    Args:
        name: Original stock name

    Returns:
        Normalized name for pinyin generation
    """
    normalized = unicodedata.normalize('NFKC', name).strip()

    # Strip common A-share prefixes while preserving the core name.
    normalized = re.sub(r'^(?:\*?ST|N)+', '', normalized, flags=re.IGNORECASE)

    return normalized.strip() or unicodedata.normalize('NFKC', name).strip()


def determine_market(ts_code: str) -> str:
    """
    Determine market based on code

    Args:
        ts_code: Trading code (e.g., 000001.SZ)

    Returns:
        Market code
    """
    if '.' in ts_code:
        suffix = ts_code.split('.')[1]

        if suffix in ['SH', 'SZ']:
            return 'CN'
        elif suffix == 'HK':
            return 'HK'
        elif suffix == 'BJ':
            return 'BSE'

    # Default to the A-share market.
    return 'CN'


def generate_aliases(name: str) -> List[str]:
    """
    Generate stock aliases

    Args:
        name: Stock name

    Returns:
        List of aliases
    """
    aliases = []

    # Common alias mappings.
    alias_map = {
        '贵州茅台': ['茅台'],
        '中国平安': ['平安'],
        '平安银行': ['平银'],
        '招商银行': ['招行'],
        '五粮液': ['五粮'],
        '宁德时代': ['宁德'],
        '比亚迪': ['比亚'],
        '工商银行': ['工行'],
        '建设银行': ['建行'],
        '农业银行': ['农行'],
        '中国银行': ['中行'],
        '交通银行': ['交行'],
        '兴业银行': ['兴业'],
        '浦发银行': ['浦发'],
        '民生银行': ['民生'],
        '中信证券': ['中信'],
        '东方财富': ['东财'],
        '海康威视': ['海康'],
        '隆基绿能': ['隆基'],
        '中国神华': ['神华'],
        '长江电力': ['长电'],
        '中国石化': ['石化'],
        '中国石油': ['石油'],
    }

    if name in alias_map:
        aliases.extend(alias_map[name])

    return aliases


def build_stock_index(stocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Build the stock index.

    Args:
        stocks: Raw stock rows

    Returns:
        Stock index entries
    """
    index = []

    for stock in stocks:
        ts_code = stock['ts_code']
        symbol = stock['symbol']
        name = stock['name']

        # Generate pinyin fields.
        pinyin_full, pinyin_abbr = generate_pinyin(name)

        # Determine the market.
        market = determine_market(ts_code)

        # Generate aliases.
        aliases = generate_aliases(name)

        index.append({
            "canonicalCode": ts_code,    # Example: 000001.SZ
            "displayCode": symbol,       # Example: 000001
            "nameZh": name,
            "pinyinFull": pinyin_full,
            "pinyinAbbr": pinyin_abbr,
            "aliases": aliases,
            "market": market,
            "assetType": "stock",
            "active": True,
            "popularity": 100,
        })

    return index


def compress_index(index: List[Dict[str, Any]]) -> List[List]:
    """
    压缩索引为数组格式以减少文件大小

    Args:
        index: 原始索引

    Returns:
        压缩后的索引
    """
    compressed = []
    for item in index:
        compressed.append([
            item["canonicalCode"],
            item["displayCode"],
            item["nameZh"],
            item.get("pinyinFull"),
            item.get("pinyinAbbr"),
            item.get("aliases", []),
            item["market"],
            item["assetType"],
            item["active"],
            item.get("popularity", 0),
        ])
    return compressed


def main():
    """主函数"""
    print("=" * 60)
    print("股票索引生成工具（从 CSV）")
    print("=" * 60)

    # 查找 CSV 文件
    logs_dir = Path(__file__).parent.parent / "logs"
    csv_files = list(logs_dir.glob("stock_basic_*.csv"))

    if not csv_files:
        print("[Error] 未找到 CSV 文件：logs/stock_basic_*.csv")
        return 1

    # 使用最新的 CSV 文件
    csv_file = sorted(csv_files)[-1]
    print(f"\n[1/5] 读取 CSV 文件：{csv_file.name}")

    # 加载数据
    stocks = load_csv_data(csv_file)
    print(f"      共读取 {len(stocks)} 只股票")

    # 生成拼音提示
    if not PYPINYIN_AVAILABLE:
        print("\n[提示] 安装 pypinyin 可获得拼音搜索功能：")
        print("       pip install pypinyin")

    print(f"\n[2/5] 生成索引数据...")
    index = build_stock_index(stocks)

    # 输出路径
    output_path = (
        Path(__file__).parent.parent / "apps" / "dsa-web" / "public" / "stocks.index.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n[3/5] 压缩索引数据...")
    compressed = compress_index(index)

    print(f"\n[4/5] 写入文件：{output_path}")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(compressed, f, ensure_ascii=False, separators=(',', ':'))

    file_size = output_path.stat().st_size
    print(f"      文件大小：{file_size / 1024:.2f} KB")

    # 验证文件
    print(f"\n[5/5] 验证文件...")
    with open(output_path, 'r', encoding='utf-8') as f:
        test_data = json.load(f)
        print(f"      验证通过：{len(test_data)} 条记录")

    # 统计信息
    market_stats = {}
    for item in index:
        market = item['market']
        market_stats[market] = market_stats.get(market, 0) + 1

    print(f"\n{'=' * 60}")
    print("生成完成！市场分布：")
    for market, count in sorted(market_stats.items()):
        print(f"  - {market}: {count} 只")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
