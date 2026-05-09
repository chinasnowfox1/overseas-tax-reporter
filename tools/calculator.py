#!/usr/bin/env python3
"""
税务计算器 — 根据结构化交易数据计算应纳个人所得税

税法规则:
- 财产转让所得（股票/基金）: 20%，同年度盈亏互抵，不跨年结转
- 股息/红利所得: 20%，境外预扣可抵免
- 利息所得: 20%，境外银行利息不免税

所有示例和输出使用占位符，不暴露真实数据。
"""

import json
import argparse
import sys


TAX_RATE = 0.20  # 统一20%税率


def calculate_tax(stock_sales, dividends, interest_income, fx_rates):
    """
    计算各类收入的应纳个人所得税。

    Args:
        stock_sales: list of {code, currency, sell_net, total_cost, profit, fee}
        dividends: list of {code, currency, gross_amount, withholding, date}
        interest_income: list of {currency, amount}
        fx_rates: dict of {currency: rate_to_cny}，如 {'USD': 7.0288, 'HKD': 0.90322}

    Returns:
        {
            'stock': {
                'individual': [...],  # 每笔交易的盈亏
                'net_profit_cny': [AMOUNT],  # 互抵后的净额(CNY)
                'tax_cny': [AMOUNT],
            },
            'dividend': {
                'individual': [...],
                'gross_cny': [AMOUNT],
                'withholding_cny': [AMOUNT],
                'tax_cny': [AMOUNT],
                'actual_cny': [AMOUNT],  # 应纳-预扣
            },
            'interest': {
                'individual': [...],
                'gross_cny': [AMOUNT],
                'tax_cny': [AMOUNT],
            },
            'total_tax_cny': [AMOUNT],
        }
    """
    result = {}

    # ---- 财产转让（股票+基金，同年度盈亏互抵） ----
    individual_stocks = []
    total_profit_cny = 0
    for s in stock_sales:
        profit_cny = s['profit'] * fx_rates.get(s['currency'], 1)
        individual_stocks.append({
            'code': s['code'],
            'currency': s['currency'],
            'profit_original': s['profit'],
            'profit_cny': profit_cny,
        })
        total_profit_cny += profit_cny

    result['stock'] = {
        'individual': individual_stocks,
        'net_profit_cny': total_profit_cny,
        'tax_cny': max(0, total_profit_cny * TAX_RATE),
    }

    # ---- 股息 ----
    individual_divs = []
    total_gross_cny = 0
    total_withholding_cny = 0
    for d in dividends:
        gross_cny = d['gross_amount'] * fx_rates.get(d['currency'], 1)
        wh_cny = d['withholding'] * fx_rates.get(d['currency'], 1)
        individual_divs.append({
            'code': d['code'],
            'date': d['date'],
            'currency': d['currency'],
            'gross_original': d['gross_amount'],
            'gross_cny': gross_cny,
            'withholding_cny': wh_cny,
        })
        total_gross_cny += gross_cny
        total_withholding_cny += wh_cny

    div_tax = total_gross_cny * TAX_RATE
    div_actual = div_tax - total_withholding_cny

    result['dividend'] = {
        'individual': individual_divs,
        'gross_cny': total_gross_cny,
        'withholding_cny': total_withholding_cny,
        'tax_cny': div_tax,
        'actual_cny': max(0, div_actual),
    }

    # ---- 利息 ----
    individual_interests = []
    total_interest_cny = 0
    for i in interest_income:
        interest_cny = i['amount'] * fx_rates.get(i['currency'], 1)
        individual_interests.append({
            'currency': i['currency'],
            'amount_original': i['amount'],
            'amount_cny': interest_cny,
        })
        total_interest_cny += interest_cny

    result['interest'] = {
        'individual': individual_interests,
        'gross_cny': total_interest_cny,
        'tax_cny': total_interest_cny * TAX_RATE,
    }

    # ---- 总计 ----
    result['total_tax_cny'] = (
        result['stock']['tax_cny']
        + result['dividend']['actual_cny']
        + result['interest']['tax_cny']
    )

    return result


def main():
    parser = argparse.ArgumentParser(description='境外投资税务计算器')
    parser.add_argument('data_file', help='结构化交易数据JSON文件')
    parser.add_argument('--format', choices=['text', 'json'], default='text')
    args = parser.parse_args()

    with open(args.data_file, 'r') as f:
        data = json.load(f)

    stock_sales = data.get('stock_sales', [])
    dividends = data.get('dividends', [])
    interest = data.get('interest', [])
    fx_rates = data.get('fx_rates', {})

    result = calculate_tax(stock_sales, dividends, interest, fx_rates)

    if args.format == 'json':
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print('=== 税务计算结果 ===')
        print()
        print(f'财产转让净盈亏: ¥{result["stock"]["net_profit_cny"]:.2f} CNY')
        print(f'财产转让应纳税: ¥{result["stock"]["tax_cny"]:.2f} CNY')
        print()
        print(f'股息税前总额: ¥{result["dividend"]["gross_cny"]:.2f} CNY')
        print(f'已代扣代缴: ¥{result["dividend"]["withholding_cny"]:.2f} CNY')
        print(f'股息实际应纳: ¥{result["dividend"]["actual_cny"]:.2f} CNY')
        print()
        print(f'利息总额: ¥{result["interest"]["gross_cny"]:.2f} CNY')
        print(f'利息应纳: ¥{result["interest"]["tax_cny"]:.2f} CNY')
        print()
        print(f'=== 税款合计: ¥{result["total_tax_cny"]:.2f} CNY ===')


if __name__ == '__main__':
    main()
