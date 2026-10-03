import sys
sys.path.insert(0, '.')

import main

_extract = main._extract_conclusion
_strip = main._strip_conclusion_block
SENTINEL = main._CONCLUSION_SENTINEL

passed = 0
failed = 0

def check(name, got, expect):
    global passed, failed
    ok = got == expect
    if ok:
        passed += 1
        print(f'  PASS  {name}')
    else:
        failed += 1
        print(f'  FAIL  {name}')
        print(f'    期望: {expect}')
        print(f'    实际: {got}')

print('=== 离线单元测试：投资结论速览解析 ===\n')

print('[用例1] 标准格式（带 ## 投资结论速览 标题）')
report1 = """## 华东医药（000963）价值分析报告

华东医药是一家领先的医药企业，核心业务涵盖医药工业和医药商业。

## 投资结论速览

【投资结论】
合理市值区间：450 ~ 550 亿元
性价比评分：7.5
投资结论：低估
置信度：4
建议持有：24m
核心依据：PE处历史底部，现金流稳定，护城河深厚
"""
c1 = _extract(report1)
s1 = _strip(report1)
check('区间下限', c1.get('valuation_low'), 450.0)
check('区间上限', c1.get('valuation_high'), 550.0)
check('中枢', c1.get('valuation_mid'), 500.0)
check('评分', c1.get('score'), 7.5)
check('结论', c1.get('verdict'), '低估')
check('置信度', c1.get('confidence'), 4)
check('持有期', c1.get('horizon'), '24m')
check('核心依据', c1.get('key_reason'), 'PE处历史底部，现金流稳定，护城河深厚')
check('剥离后不含哨兵', SENTINEL in s1, False)
check('剥离后不含标题', '投资结论速览' in s1, False)
check('剥离后保留正文', '华东医药是一家领先的医药企业' in s1, True)

print('\n[用例2] 无标题行（模型直接写哨兵）')
report2 = """## 汇川技术分析

汇川技术是工业自动化龙头。

【投资结论】
合理市值区间：1123 ~ 1650 亿元
性价比评分：4.5
投资结论：高估
置信度：4
建议持有：24m
核心依据：增收不增利且自由现金流为负，当前股价透支乐观预期
"""
c2 = _extract(report2)
s2 = _strip(report2)
check('区间下限', c2.get('valuation_low'), 1123.0)
check('区间上限', c2.get('valuation_high'), 1650.0)
check('评分', c2.get('score'), 4.5)
check('结论', c2.get('verdict'), '高估')
check('剥离后不含哨兵', SENTINEL in s2, False)
check('剥离后保留正文', '汇川技术是工业自动化龙头' in s2, True)

print('\n[用例3] 宽容格式（全角冒号／无空格~／12个月／千分位逗号）')
report3 = """分析正文……

【投资结论】
合理市值区间：1,200～1,800亿元
性价比评分：8.0
投资结论：低估
置信度：5
建议持有：12个月
核心依据：垄断地位稳固，高分红率，净现金充裕
"""
c3 = _extract(report3)
check('千分位下限', c3.get('valuation_low'), 1200.0)
check('千分位上限', c3.get('valuation_high'), 1800.0)
check('12个月转12m', c3.get('horizon'), '12m')
check('评分', c3.get('score'), 8.0)
check('置信度', c3.get('confidence'), 5)

print('\n[用例4] 无结论速览（模型忽略契约）')
report4 = """## 分析报告

正文只有这些，模型没写结论速览。
"""
c4 = _extract(report4)
s4 = _strip(report4)
check('空dict无区间', c4.get('valuation_low'), None)
check('空dict无评分', c4.get('score'), None)
check('无哨兵时strip原样返回', s4, report4)

print('\n[用例5] 哨兵跨 chunk 边界（hold 机制）')
full5 = """正文部分。

【投资结论】
合理市值区间：300 ~ 400 亿元
性价比评分：6.0
投资结论：合理
置信度：3
建议持有：12m
核心依据：估值合理，业绩稳健
"""
c5 = _extract(full5)
check('跨chunk下限', c5.get('valuation_low'), 300.0)
check('跨chunk上限', c5.get('valuation_high'), 400.0)
check('跨chunk评分', c5.get('score'), 6.0)

print('\n[用例6] 区间顺序颠倒（自动交换 low/high）')
report6 = """正文。

【投资结论】
合理市值区间：550 ~ 450 亿元
性价比评分：5.0
投资结论：合理
置信度：3
建议持有：6m
核心依据：测试区间交换
"""
c6 = _extract(report6)
check('颠倒后下限=较小值', c6.get('valuation_low'), 450.0)
check('颠倒后上限=较大值', c6.get('valuation_high'), 550.0)
check('颠倒后中枢', c6.get('valuation_mid'), 500.0)

print('\n[用例7] 评分/置信度越界（丢弃非法值）')
report7 = """正文。

【投资结论】
合理市值区间：100 ~ 200 亿元
性价比评分：15.0
投资结论：低估
置信度：9
建议持有：12m
核心依据：测试越界
"""
c7 = _extract(report7)
check('评分>10丢弃', c7.get('score'), None)
check('置信度>5丢弃', c7.get('confidence'), None)
check('区间仍解析', c7.get('valuation_low'), 100.0)

print('\n[用例8] verdict 非法值（丢弃）')
report8 = """正文。

【投资结论】
合理市值区间：100 ~ 200 亿元
性价比评分：5.0
投资结论：强烈推荐
置信度：3
建议持有：12m
核心依据：测试verdict
"""
c8 = _extract(report8)
check('verdict非法丢弃', c8.get('verdict'), None)
check('评分仍解析', c8.get('score'), 5.0)

print('\n[用例9] 剥离后正文末尾干净')
report9 = """## 报告标题

正文段落一。

正文段落二。

## 投资结论速览

【投资结论】
合理市值区间：100 ~ 200 亿元
性价比评分：5.0
投资结论：合理
置信度：3
建议持有：12m
核心依据：测试
"""
s9 = _strip(report9)
check('剥离后不含合理市值区间键', '合理市值区间' in s9, False)
check('剥离后不含性价比评分键', '性价比评分' in s9, False)
check('剥离后以正文结尾', s9.rstrip().endswith('正文段落二。'), True)

print('\n[用例10] 面板指标提取（客观数据）')
panel = """
当前价格：27.13
PE (TTM)：13.92
PB (市净率)：1.89
总市值：481.58
"""
m = main._extract_panel_metrics(panel)
check('面板price', m.get('price_now'), 27.13)
check('面板pe', m.get('pe_ttm_now'), 13.92)
check('面板pb', m.get('pb_now'), 1.89)
check('面板mc', m.get('mc_now'), 481.58)

print('\n[用例11] 宽容降级（带「约」「亿」等修饰）')
variants = [
    ("约字+亿字",  "合理市值区间：约450亿~550亿"),
    ("亿字挡分隔", "合理市值区间：450亿 ~ 550亿"),
    ("到字连接",   "合理市值区间：450亿到550亿元"),
    ("括号注释",   "合理市值区间（2026E）：450 ~ 550 亿元"),
]
for name, line in variants:
    rpt = f"正文。\n\n【投资结论】\n{line}\n性价比评分：6.0\n投资结论：合理\n置信度：3\n建议持有：12m\n核心依据：降级测试\n"
    c = _extract(rpt)
    check(f'{name}-下限', c.get('valuation_low'), 450.0)
    check(f'{name}-上限', c.get('valuation_high'), 550.0)
    check(f'{name}-中枢', c.get('valuation_mid'), 500.0)

print('\n[用例12] _raw_block 原文存档')
rpt12 = "正文。\n\n【投资结论】\n合理市值区间：450 ~ 550 亿元\n性价比评分：7.5\n投资结论：低估\n置信度：4\n建议持有：24m\n核心依据：测试存档\n"
c12 = _extract(rpt12)
raw_block = c12.get('_raw_block') or ''
check('raw_block含区间行', '合理市值区间' in raw_block, True)
check('raw_block含评分行', '性价比评分：7.5' in raw_block, True)
check('raw_block不含哨兵', '【投资结论】' in raw_block, False)

print('\n[用例13] 降级护栏')
rpt13 = "正文。\n\n【投资结论】\n合理市值：约500亿元\n性价比评分：6.0\n投资结论：合理\n置信度：3\n建议持有：12m\n核心依据：单数字\n"
c13 = _extract(rpt13)
check('单数字不误判区间', c13.get('valuation_low'), None)

print(f'\n=== 结果：{passed} PASS / {failed} FAIL ===')
sys.exit(0 if failed == 0 else 1)
