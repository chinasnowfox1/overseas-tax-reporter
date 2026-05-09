#!/usr/bin/env python3
"""
Excel导出器 — 生成7-sheet律师模板格式报税Excel

Sheet列表:
1. 股票基本信息
2. 股票交易明细
3. 股息
4. 利息收入
5. 基金交易
6. 税款计算表
7. 透视表

列名严格匹配律师模板（包括空格和换行符）。

所有示例数据使用占位符，不暴露真实数据。
"""

import pandas as pd
import json
import argparse
import os
import sys


def generate_excel(tax_result, stock_info, fund_trades, fx_rates, tax_year, output_path):
    """
    生成7-sheet报税Excel。

    Args:
        tax_result: calculator.py 的输出
        stock_info: list of {code, name, region}
        fund_trades: list of {name, region, currency, type, shares, price, amount, order_date, settle_date}
        fx_rates: {currency: rate}
        tax_year: int
        output_path: str
    """
    rate_date = pd.Timestamp(tax_year, 12, 31)

    with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
        _sheet_stock_info(writer, stock_info)
        _sheet_stock_trades(writer, tax_result['stock']['individual'], stock_info)
        _sheet_dividends(writer, tax_result['dividend']['individual'])
        _sheet_interest(writer, tax_result['interest']['individual'])
        _sheet_fund_trades(writer, fund_trades, tax_year)
        _sheet_tax_calc(writer, tax_result, fx_rates, rate_date, tax_year)
        _sheet_pivot(writer, tax_result, fx_rates)


def _sheet_stock_info(writer, stock_info):
    """Sheet 1: 股票基本信息"""
    rows = []
    for s in stock_info:
        rows.append({
            '证券代码': s['code'],
            '证券名称': s['name'],
            '注册地': s.get('region', ''),
            '是否H股': '否',
            '纳税年度是否有错配': '否',
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_excel(writer, sheet_name='股票基本信息', index=False)


def _sheet_stock_trades(writer, trades, stock_info):
    """Sheet 2: 股票交易明细"""
    info_map = {s['code']: s for s in stock_info}
    rows = []
    for t in trades:
        info = info_map.get(t['code'], {})
        rows.append({
            '证券代码': t['code'],
            '证券名称': info.get('name', ''),
            '注册地址': info.get('region', ''),
            '资金收付日期': '',
            '币种': t['currency'],
            '本次买入股数': None,
            '本次支出': None,
            '本次卖出股数': None,
            '本次收入': round(t['profit_original'], 2) if t['profit_original'] > 0 else None,
            '累计股数': 0,
            '累计支出': 0,
            '本次交易后加权平均持股成本': None,
            '本次卖出盈利': round(t['profit_cny'], 2),
            '手续费': 0,
            '纳税年度是否错配': '否',
            '境外纳税年度': None,
            '对应内地纳税年度': None,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_excel(writer, sheet_name='股票交易明细', index=False)


def _sheet_dividends(writer, dividends):
    """Sheet 3: 股息"""
    rows = []
    for d in dividends:
        gross_cny = d.get('gross_cny', 0)
        wh_cny = d.get('withholding_cny', 0)
        tax = gross_cny * 0.20
        actual = max(0, tax - wh_cny)
        wh_rate = wh_cny / gross_cny if gross_cny > 0 else 0

        rows.append({
            '证券代码': d['code'],
            '证券名称': '',
            '注册地': '',
            '是否H股': '否',
            '分红日期': d['date'],
            '分红币种': d['currency'],
            '实际到账分红金额': round(gross_cny - wh_cny, 2),
            '已代扣代缴税款币种': d['currency'],
            '手续费': 0,
            '已代扣代缴税款金额': round(wh_cny, 2),
            '还原税前分红金额': round(gross_cny, 2),
            '纳税年度是否错配': '否',
            '境外纳税年度': None,
            '对应内地纳税年度': None,
            '已扣税税率': round(wh_rate, 6),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_excel(writer, sheet_name='股息', index=False)


def _sheet_interest(writer, interests):
    """Sheet 4: 利息收入"""
    rows = []
    for i in interests:
        rows.append({
            '利息收取日期': '',
            '币种': i['currency'],
            '利息金额': i['amount_original'],
            '纳税年度是否错配': '否',
            '境外纳税年度': None,
            '对应内地纳税年度': None,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_excel(writer, sheet_name='利息收入', index=False)


def _sheet_fund_trades(writer, fund_trades, tax_year):
    """Sheet 5: 基金交易"""
    rows = []
    for t in fund_trades:
        is_buy = t['type'] == 'buy'
        rows.append({
            '名称': t['name'],
            '注册地址': t.get('region', ''),
            '币种': t['currency'],
            '资金收付日期': t.get('settle_date') or t.get('order_date'),
            '本次买入数量': t['shares'] if is_buy else None,
            ' 本次支出 ': t['amount'] if is_buy else None,
            '本次卖出数量': t['shares'] if not is_buy else None,
            '本次收入': t['amount'] if not is_buy else None,
            ' 累计份额 ': 0,
            ' 累计支出 ': 0,
            ' 本次交易后\n加权平均成本 ': t['price'] if is_buy else 0,
            '本次赎回盈利': 0,
            '纳税年度是否错配': '否',
            '境外纳税年度': tax_year,
            '对应内地纳税年度': tax_year,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_excel(writer, sheet_name='基金交易', index=False)


def _sheet_tax_calc(writer, tax_result, fx_rates, rate_date, tax_year):
    """Sheet 6: 税款计算表"""
    stock = tax_result['stock']
    div = tax_result['dividend']
    interest = tax_result['interest']
    total = tax_result['total_tax_cny']

    # 找到 USD/HKD rate
    usd_rate = fx_rates.get('USD', 0)
    hkd_rate = fx_rates.get('HKD', 0)

    rows = [
        ['', '汇率日', rate_date],
        ['', 'HKD', hkd_rate],
        ['', 'USD', usd_rate],
        ['', '', ''],
        ['', '内地纳税年度', tax_year],
        # 股息
        ['', '股息', '原始币种', 'HKD', 'USD'],
        ['', '', '原始金额', '', div['gross_cny'] / usd_rate if usd_rate else 0],
        ['', '', '人民币金额', '', div['gross_cny']],
        ['', '', '应纳个人所得税', '', div['tax_cny']],
        ['', '', '已代扣代缴个人所得税', '', div['withholding_cny']],
        ['', '', '实际应纳个人所得税', '', div['actual_cny']],
        ['', '', ''],
        # 利息
        ['', '利息', '原始币种', 'HKD', 'USD'],
        ['', '', '原始金额', interest['gross_cny'] / hkd_rate if hkd_rate else 0, ''],
        ['', '', '人民币金额', interest['gross_cny'], ''],
        ['', '', '应纳个人所得税', interest['tax_cny'], ''],
        ['', '', ''],
        # 财产转让
        ['', '财产转让（同年度盈亏互抵）', '原始币种', 'HKD', 'USD'],
        ['', '', '原始金额', '', stock['net_profit_cny'] / usd_rate if usd_rate else 0],
        ['', '', '人民币金额', '', stock['net_profit_cny']],
        ['', '', '应纳个人所得税', '', stock['tax_cny']],
        ['', '', ''],
        # 合计
        ['', '税款合计', '', '', total],
    ]

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='税款计算表', index=False, header=False)


def _sheet_pivot(writer, tax_result, fx_rates):
    """Sheet 7: 透视表"""
    stock = tax_result['stock']
    div = tax_result['dividend']
    interest = tax_result['interest']

    rows = [
        ['股息', '', '', '', '', '利息', '', ''],
        ['对应内地纳税年度', '已代扣代缴税款币种', '求和项:还原税前分红金额', '求和项:已代扣代缴税款金额',
         '', '对应内地纳税年度', '币种', '求和项:利息金额'],
        [None, '', div['gross_cny'], div['withholding_cny'], '', None, 'CNY', interest['gross_cny']],
        ['', 'USD', div['gross_cny'], div['withholding_cny'], '', '', '', ''],
        ['股票交易', '', '', '', '', '', '', ''],
        ['对应内地纳税年度', '币种', '求和项:本次卖出盈利', '求和项:手续费', '', '', '', ''],
        [None, 'CNY', stock['net_profit_cny'], 0, '', '', '', ''],
        ['', 'CNY', stock['net_profit_cny'], 0, '', '', '', ''],
        ['总计', '', stock['net_profit_cny'], 0, '', '', '', ''],
        ['基金交易', '', '', '', '', '', '', ''],
        ['对应内地纳税年度', '币种', '求和项:本次赎回盈利', '', '', '', '', ''],
        [None, '', 0, '', '', '', '', ''],
    ]

    df = pd.DataFrame(rows)
    df.to_excel(writer, sheet_name='透视表', index=False, header=False)


def main():
    parser = argparse.ArgumentParser(description='生成报税Excel')
    parser.add_argument('data_file', help='结构化交易数据JSON文件')
    parser.add_argument('-o', '--output', default='报税数据.xlsx', help='输出路径')
    args = parser.parse_args()

    with open(args.data_file, 'r') as f:
        data = json.load(f)

    # 从 calculator 的结果中提取
    calc = data.get('calculation', {})
    stock_info = data.get('stock_info', [])
    fund_trades = data.get('fund_trades', [])
    fx_rates = data.get('fx_rates', {})
    tax_year = data.get('tax_year', 2025)

    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    generate_excel(calc, stock_info, fund_trades, fx_rates, tax_year, output_path)
    print(f'已输出: {output_path}')


if __name__ == '__main__':
    main()
