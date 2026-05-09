#!/usr/bin/env python3
"""
汇率查询工具 — 查询中国人民银行公布的中间价

用法:
    python fx_rates.py <日期> [<币种>...]
    python fx_rates.py 2025-12-31 USD HKD
"""

import urllib.request
import json
import sys
import re
from datetime import datetime


def query_pboc_rate(date_str, currency):
    """
    从中国人民银行网站查询指定日期的汇率中间价。

    Returns: (currency, rate) or None if not found
    """
    try:
        url = f'https://www.pbc.gov.cn/portal/site/sjml/newfxdj/?date={date_str}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode('utf-8')

        # 查找指定币种的汇率
        pattern = rf'<td[^>]*>{re.escape(currency)}</td>.*?<td[^>]*>([\d.]+)</td>'
        m = re.search(pattern, html, re.DOTALL)
        if m:
            return (currency, float(m.group(1)))
    except Exception:
        pass
    return None


def get_fallback_rates(tax_year):
    """
    如果查询失败，返回常见年度末汇率（仅供参考）。
    这些值需要用户自行核实。
    """
    fallback = {
        2025: {'USD': '[需核实]', 'HKD': '[需核实]'},
        2024: {'USD': '[需核实]', 'HKD': '[需核实]'},
        2023: {'USD': '[需核实]', 'HKD': '[需核实]'},
    }
    return fallback.get(tax_year, {})


def main():
    if len(sys.argv) < 2:
        print('用法: fx_rates.py <日期 YYYY-MM-DD> [<币种>...]')
        print('示例: fx_rates.py 2025-12-31 USD HKD')
        sys.exit(1)

    date_str = sys.argv[1]
    currencies = sys.argv[2:] if len(sys.argv) > 2 else ['USD', 'HKD']

    results = {}
    for curr in currencies:
        rate = query_pboc_rate(date_str, curr)
        if rate:
            results[curr] = rate[1]
            print(f'{curr}: {rate[1]}')
        else:
            print(f'{curr}: 未找到（请手动查询中国人民银行官网）')

    if results:
        print(f'\n{{"fx_rates": {json.dumps(results)}}}')
    else:
        year = int(date_str[:4])
        fb = get_fallback_rates(year)
        print(f'\n备用参考值（需核实）: {json.dumps(fb)}')


if __name__ == '__main__':
    main()
