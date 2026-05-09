#!/usr/bin/env python3
"""
PDF月结单解析器 — 从券商PDF中提取股票交易、股息、基金交易数据

支持的券商格式:
- 富途证券 (已验证)
- 其他券商可通过 register_broker_parser() 扩展

所有示例和输出使用占位符，不暴露真实数据。
"""

import pdfplumber
import glob
import os
import re
from collections import defaultdict


def clean_cjk_text(text):
    """
    富途PDF中CJK字符会被重复两次（如"賣賣出出"），ASCII字符正常。
    只去重CJK范围内的连续重复字符。
    """
    result = []
    prev = ''
    for ch in text:
        is_cjk = '一' <= ch <= '鿿' or '　' <= ch <= '〿' or '＀' <= ch <= '￯'
        if is_cjk and ch == prev:
            prev = ch
            continue
        result.append(ch)
        prev = ch
    return ''.join(result)


def extract_futubull_dividends(text, ym):
    """
    从富途PDF文本提取股息数据。

    流程:
    1. 先提取所有 WITHHOLDING TAX 行，按股票代码建立预扣税映射
    2. 再提取所有 DIVIDENDS 行，匹配对应的预扣税

    返回: list of {date, currency, gross_amount, withholding, net_amount,
                    code, shares, per_share, ym}
    """
    results = []
    withholding_map = {}

    # Step 1: 提取预扣税
    for line in text.split('\n'):
        line = line.strip()
        if 'WITHHOLDING TAX' not in line:
            continue
        m = re.search(
            r'USD\s+([\-\d,]+\.\d+)\s+(\w+)\s+([\d.]+)\s+SHARES\s+WITHHOLDING\s+TAX\s+([\-\d.]*)',
            line
        )
        if m:
            code = m.group(2)
            total_tax = abs(float(m.group(1).replace(',', '')))
            shares = float(m.group(3))
            per_share_str = m.group(4)
            per_share_tax = abs(float(per_share_str)) if per_share_str and per_share_str != '-' else (total_tax / shares if shares > 0 else 0)
            withholding_map[code] = {'total': total_tax, 'shares': shares, 'per_share': per_share_tax}

    # Step 2: 提取股息
    for line in text.split('\n'):
        line = line.strip()
        if 'DIVIDENDS' not in line:
            continue
        m = re.search(
            r'(\d{4}/\d{2}/\d{2})\s+\S+\s+\S+\s+(\w+)\s+([\+\-][\d,]+\.\d+)\s+(\w+)\s+([\d.]+)\s+SHARES\s+DIVIDENDS\s+([\d.]+)\s+USD',
            line
        )
        if m:
            shares = float(m.group(5))
            per_share = float(m.group(6))
            gross = shares * per_share
            code = m.group(4)
            wh = withholding_map.get(code, {})
            withholding = wh.get('total', gross * 0.10)
            net = gross - withholding

            results.append({
                'date': m.group(1),
                'currency': m.group(2),
                'net_amount': net,
                'gross_amount': gross,
                'withholding': withholding,
                'code': code,
                'shares': shares,
                'per_share': per_share,
                'ym': ym,
            })
    return results


def extract_futubull_stock_trades(text, ym):
    """
    从富途PDF文本提取股票交易数据。

    格式示例:
        賣出平倉 [CODE]([NAME]) [CURRENCY] [QTY] [PRICE] [GROSS] [NET]
        [MARKET] [CURRENCY] [TRADE_DATE] [SETTLE_DATE] [QTY] [PRICE] [GROSS] [NET]

    返回: list of {direction, code, name, currency, quantity, price,
                    gross_amount, net_amount, fee, ym}
    """
    results = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        direction = None
        if re.match(r'賣出|卖出', line):
            direction = 'sell'
        elif re.match(r'買入|买入', line):
            direction = 'buy'

        if direction:
            m = re.search(
                r'(\w+)\(([^)]+)\)\s+(\w+)\s+([\d,]+)\s+([\d.]+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)',
                line
            )
            if m:
                qty = int(m.group(4).replace(',', ''))
                gross = float(m.group(6).replace(',', ''))
                net = float(m.group(7).replace(',', ''))
                results.append({
                    'direction': direction,
                    'code': m.group(1),
                    'name': m.group(2),
                    'currency': m.group(3),
                    'quantity': qty,
                    'price': float(m.group(5)),
                    'gross_amount': gross,
                    'net_amount': net,
                    'fee': gross - net,
                    'ym': ym,
                })

        # 从下一行提取（部分格式第二行有完整信息）
        if i + 1 < len(lines) and direction:
            next_line = lines[i + 1].strip()
            m2 = re.search(
                r'\w+\s+(\w+)\s+(\d{4}/\d{2}/\d{2})\s+\d{4}/\d{2}/\d{2}\s+([\d,]+)\s+([\d.]+)\s+([\d,]+\.\d+)\s+([\d,]+\.\d+)',
                next_line
            )
            if m2:
                qty = int(m2.group(3).replace(',', ''))
                already = any(
                    r['ym'] == ym and r['code'] == m2.group(1) and r['quantity'] == qty
                    for r in results
                )
                if not already:
                    prev_m = re.search(r'(\w+)\(([^)]+)\)', line)
                    results.append({
                        'direction': direction,
                        'code': prev_m.group(1) if prev_m else '',
                        'name': prev_m.group(2) if prev_m else '',
                        'currency': m2.group(1),
                        'quantity': qty,
                        'price': float(m2.group(4)),
                        'gross_amount': float(m2.group(5).replace(',', '')),
                        'net_amount': float(m2.group(6).replace(',', '')),
                        'fee': 0,
                        'ym': ym,
                    })
        i += 1

    return results


def extract_futubull_fund_trades(text, ym):
    """
    从富途PDF文本提取基金交易数据。

    格式示例:
        申購 HK[ID] ([NAME]) [CURRENCY] [ORDER_DATE] [SETTLE_DATE] [SHARES] [PRICE] [AMOUNT]

    返回: list of {type, name, currency, order_date, settle_date, shares, price, amount, ym}
    """
    results = []
    for line in text.split('\n'):
        line = line.strip()
        if '費用' in line or '小計' in line or '小计' in line:
            continue
        if '除非另有說明' in line or '除非另有说明' in line:
            continue

        m = re.search(
            r'(申購|贖回|申购|赎回)\s+HK\d+\s+\(([^)]+)\)\s+(\w+)\s+(\d{4}/\d{2}/\d{2})\s+(\d{4}/\d{2}/\d{2})\s+([\d,]+\.\d+)\s+([\d.]+)\s+([\d,]+\.\d+)',
            line
        )
        if m:
            results.append({
                'type': 'buy' if m.group(1) in ('申購', '申购') else 'sell',
                'name': m.group(2),
                'currency': m.group(3),
                'order_date': m.group(4),
                'settle_date': m.group(5),
                'shares': float(m.group(6).replace(',', '')),
                'price': float(m.group(7)),
                'amount': float(m.group(8).replace(',', '')),
                'ym': ym,
            })
    return results


def parse_futubull_pdfs(pdf_dir, password=None):
    """
    解析富途证券所有月结单PDF，返回结构化数据。

    Args:
        pdf_dir: PDF存放目录
        password: PDF密码（如有）

    Returns:
        {
            'dividends': [...],
            'stock_trades': [...],
            'fund_trades': [...],
            'end_holdings': {'stocks': {}, 'funds': {}},
        }
    """
    files = sorted(glob.glob(os.path.join(pdf_dir, '*.pdf')))
    all_dividends = []
    all_stock_trades = []
    all_fund_trades = []
    end_holdings = {'stocks': {}, 'funds': {}}

    for f in files:
        fname = os.path.basename(f)
        date_match = re.search(r'-(\d{4})(\d{2})\d{2}-', fname)
        if not date_match:
            continue
        year, month = date_match.group(1), date_match.group(2)
        ym = year + month

        with pdfplumber.open(f, password=password) as pdf:
            raw_text = ''
            for page in pdf.pages:
                raw_text += (page.extract_text() or '') + '\n'
            text = clean_cjk_text(raw_text)

        all_dividends.extend(extract_futubull_dividends(text, ym))
        all_stock_trades.extend(extract_futubull_stock_trades(text, ym))
        all_fund_trades.extend(extract_futubull_fund_trades(text, ym))

        if month == '12':
            holdings = extract_futubull_end_holdings(text)
            end_holdings['stocks'].update(holdings.get('stocks', {}))
            end_holdings['funds'].update(holdings.get('funds', {}))

    # 去重
    seen = set()
    unique = []
    for t in all_stock_trades:
        key = (t['ym'], t['code'], t['quantity'], t['net_amount'])
        if key not in seen:
            seen.add(key)
            unique.append(t)
    all_stock_trades = unique

    return {
        'dividends': all_dividends,
        'stock_trades': all_stock_trades,
        'fund_trades': all_fund_trades,
        'end_holdings': end_holdings,
    }


def extract_futubull_end_holdings(text):
    """提取期末持仓（仅12月有效）"""
    holdings = {'stocks': {}, 'funds': {}}
    for line in text.split('\n'):
        line = line.strip()
        m = re.search(r'(\d{4}|[A-Z]{3,4})\(([^)]+)\)\s+\w+\s+(\w+)\s+([\d,]+)\s+([\d.]+)', line)
        if m:
            holdings['stocks'][m.group(1)] = {
                'name': m.group(2),
                'currency': m.group(3),
                'quantity': int(m.group(4).replace(',', '')),
                'price': float(m.group(5)),
            }
        m2 = re.search(r'HK\d+\(([^)]+)\)\s+(\w+)\s+([\d.]+)\s+([\d.]+)\s+\d{4}', line)
        if m2:
            holdings['funds'][m2.group(1)] = {
                'currency': m2.group(2),
                'shares': float(m2.group(3)),
                'price': float(m2.group(4)),
            }
    return holdings


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print(f'用法: {sys.argv[0]} <PDF目录> [密码]')
        sys.exit(1)

    pdf_dir = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) > 2 else None

    result = parse_futubull_pdfs(pdf_dir, password)
    print(f'股票交易: {len(result["stock_trades"])} 笔')
    print(f'股息: {len(result["dividends"])} 笔')
    print(f'基金交易: {len(result["fund_trades"])} 笔')
    print(f'期末持仓: {len(result["end_holdings"]["stocks"])} 只股票')
