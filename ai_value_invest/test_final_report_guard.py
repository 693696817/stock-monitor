import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')

import main

_problem = main._final_report_problem
_span = main._conclusion_span
_strip = main._strip_conclusion_block
_extract = main._extract_conclusion
SENTINEL = main._CONCLUSION_SENTINEL

passed = 0
failed = 0

def check(name, got, expect):
    global passed, failed
    if got == expect:
        passed += 1
        print(f'  PASS  {name}')
    else:
        failed += 1
        print(f'  FAIL  {name}')
        print(f'    期望: {expect}')
        print(f'    实际: {got}')

def ok(name, md):
    p = _problem(md, md)
    check(name + ' → 放行', p, None)

def bad(name, md, must):
    p = _problem(md, md)
    check(name + ' → 拦下', p is not None, True)
    if p:
        check(name + f' 原因含「{must}」', must in p, True)

def _mk(n_head, n_char, tail='。'):
    out = ['# 测试报告', '']
    for i in range(n_head):
        out.append(f'## {i + 1}、第{i + 1}章 基本面分析')
        out.append('')
        need = max(1, n_char // max(1, n_head))
        out.append('公司主营业务稳健，毛利率维持高位，现金流质量良好，' * (need // 28 + 1))
        out.append('')
    body = '\n'.join(out)
    body = body[:n_char] if len(body) > n_char else body
    return body.rstrip() + tail

GOOD_FULL = _mk(6, 4000, '。综上，给予「合理」评级。')
SHORT_BUT_OK = _mk(8, 1400, '。以上分析基于数据面板，仅供参考。')
OUTLINE_ONLY = ('## 一、生意本质\n## 二、财务质量\n## 三、估值锚定\n'
                '## 四、周期位置\n## 五、致命风险\n## 六、投资决策\n最后')
EN_DRAFT = ('We need to produce a deep value investment research report on 测试标的. '
            'We must follow strict rules. Then a blockquote line: ') + _mk(6, 3000, '。')
CN_NORMAL_OPEN = '## 1. 短线情绪与热点催化\n我需要梳理近期 5 个个股事件、热点概念、资金关注度。' + _mk(6, 3200, '。')
CN_NORMAL_OPEN2 = '## 一、生意本质\n1. 商业模式\n2. 护城河\n我将按照三档情景展开测算。' + _mk(6, 4200, '。')
TRUNC_TAIL = _mk(6, 4600, '') + '\n最后输出'
TRUNC_ENG = _mk(6, 6000, '') + '\nSo the market is pricing in continued growth for three years and the DCF'

print('=== 最终交付校验：应当放行 ===\n')
ok('完整深度报告（4000字/6标题）', GOOD_FULL)
ok('#164 型：1402字但8标题且结尾完整', SHORT_BUT_OK)
ok('#420 型：正文含「我需要梳理」', CN_NORMAL_OPEN)
ok('#324 型：正文含「我将按照」', CN_NORMAL_OPEN2)

print('\n=== 最终交付校验：应当拦下 ===\n')
bad('#463 型：只剩大纲标题', OUTLINE_ONLY, '正文过短')
bad('#288 型：英文规划草稿开头', EN_DRAFT, '规划草稿')
bad('#429 型：结尾停在「最后输出」', TRUNC_TAIL, '截断')
bad('#421 型：结尾是没标点的英文长句', TRUNC_ENG, '截断')
bad('空正文', '', '正文为空')
bad('纯占位符', '（此处待补充）', '正文过短')

print('\n=== 结论哨兵定位（P0-2）===\n')
TAIL_CONCL = _mk(6, 3000) + '\n\n' + SENTINEL + '\n合理市值区间：330 ~ 799 亿元\n性价比评分：7.5\n'
MID_CONCL = ('# 报告开头\n' + _mk(3, 1500) + '\n\n' + SENTINEL +
             '\n合理市值区间：330 ~ 799 亿元\n性价比评分：7.5\n\n## 七、补充章节\n' + _mk(3, 1500))

sp = _span(TAIL_CONCL)
check('文末结论：起点=哨兵位置', sp is not None and sp[0] == TAIL_CONCL.find(SENTINEL), True)
check('文末结论：终点=全文末尾', sp is not None and sp[1] == len(TAIL_CONCL), True)

sp2 = _span(MID_CONCL)
check('文中结论：定位到块', sp2 is not None, True)
if sp2:
    block = MID_CONCL[sp2[0]:sp2[1]]
    check('文中结论：块内含估值行', '合理市值区间' in block, True)
    check('文中结论：块不含后续章节', '七、补充章节' not in block, True)

body_mid = _strip(MID_CONCL)
check('文中结论：剥离后保留哨兵前的正文', '报告开头' in body_mid, True)
check('文中结论：剥离后保留哨兵后的正文', '七、补充章节' in body_mid, True)
check('文中结论：剥离后不含哨兵', SENTINEL not in body_mid, True)
_problem_mid = _problem(MID_CONCL, body_mid)
check('文中结论：不被误判为「切掉了 60% 正文」',
      _problem_mid is None or '结论块切掉' not in (_problem_mid or ''), True)

ext = _extract(MID_CONCL)
check('文中结论：仍能解析出估值', ext.get('valuation_low') is not None, True)

print(f'\n=== 结果：{passed} PASS / {failed} FAIL ===')
sys.exit(1 if failed else 0)
