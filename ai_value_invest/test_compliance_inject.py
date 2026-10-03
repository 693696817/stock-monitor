import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, '.')

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

def ok(name, cond):
    check(name, bool(cond), True)

REPORT = """# 华东医药（000963）投资价值分析

## 一、生意与护城河

公司是医药商业与工业双轮驱动的综合性药企，核心看点在于创新药管线兑现。

## 二、财务质量

近三年经营性现金流均高于净利润，利润含金量较好。应收与存货周转稳定。

## 三、估值与结论

当前 PE-TTM 处于近五年 30% 分位，安全边际尚可，但集采扰动仍在。
"""

print('\n[1] 基本注入')
out = rp.postprocess_report(REPORT)
ok('头部有 AI 生成标识', rp._FLAG_MARK in out)
ok('尾部有免责声明', rp._DISCLAIM_MARK in out)
ok('标识在正文之前', out.index(rp._FLAG_MARK) < out.index('华东医药'))
ok('免责在正文之后', out.index(rp._DISCLAIM_MARK) > out.index('安全边际'))
ok('正文未被吞掉', '创新药管线兑现' in out)

print('\n[2] 幂等（重跑结果不变）')
out2 = rp.postprocess_report(out)
check('二次后处理内容一致', out2, out)
out3 = rp.postprocess_report(out2)
check('三次后处理内容一致', out3, out)
check('标识只出现一次', out.count('AI 生成内容'), 1)
check('免责标题只出现一次', out.count('**免责声明**'), 1)

print('\n[3] 模型自己写了免责/标识时不重复添加')
own = REPORT + "\n\n> **免责声明**\n>\n> 本文仅供参考。\n"
o = rp.postprocess_report(own)
check('不追加第二份免责', o.count('**免责声明**'), 1)
check('仍补上 AI 标识', o.count('AI 生成内容'), 1)

flagged = "> ⚠️ **AI 生成内容｜本报告由人工智能模型自动生成**\n> 说明。\n\n" + REPORT
o = rp.postprocess_report(flagged)
check('不追加第二份标识', o.count('AI 生成内容'), 1)
check('仍补上免责', o.count('**免责声明**'), 1)

print('\n[4] 截断标注与免责共存（顺序：正文 → 截断提示 → 免责）')
trunc = REPORT + "\n\n1."
o = rp.postprocess_report(trunc)
ok('截断提示已加', '生成过程中被截断' in o)
ok('免责也已加', rp._DISCLAIM_MARK in o)
ok('截断提示在免责之前', o.index('生成过程中被截断') < o.index(rp._DISCLAIM_MARK))
o2 = rp.postprocess_report(o)
check('含截断标注时仍幂等', o2, o)

print('\n[5] 历史样本：末行已是提示文本，不再误判截断')
hist = REPORT.rstrip() + "\n\n" + rp._TRUNC_NOTE + "\n"
o = rp.postprocess_report(hist)
check('不重复加截断提示', o.count('生成过程中被截断'), 1)
ok('仍补免责', rp._DISCLAIM_MARK in o)

print('\n[6] 边界')
check('空文本原样返回', rp.postprocess_report(""), "")
check('纯空白原样返回', rp.postprocess_report("   "), "   ")
check('未注入函数对空串安全', rp.inject_compliance(""), "")
short = "# 标题\n一句话。"
o = rp.postprocess_report(short)
ok('极短报告也有标识', rp._FLAG_MARK in o)

print('\n[7] 站点名可配置')
o = rp.postprocess_report(REPORT, site_name="测试站")
ok('标识用传入站点名', "「测试站」" in o)
ok('默认样本不被污染', "「A股棱镜」" in rp.postprocess_report(REPORT))

print('\n[8] 报告头署名称谓（消除「分析师」持牌暗示 + 旧品牌）')
byline = "# X 公司研报\n> 报告日期：2026年09月03日 | 分析框架：深度价值 | 分析师：A股棱镜\n\n## 一、正文\n"
o = rp.postprocess_report(byline)
ok('署名为 AI 生成引擎', '生成引擎：A股棱镜 AI 模型' in o)
check('不再出现「分析师：A股棱镜」', '分析师：A股棱镜' in o, False)
o2 = rp.postprocess_report(o)
check('署名改写幂等', o2, o)
body_talk = "# 标题\n" + ("正文字" * 300) + "\n参见卖方分析师：中信证券预期。\n"
o = rp.postprocess_report(body_talk)
ok('正文里的分析师表述不动', '卖方分析师：中信证券' in o)
check('正文署名未被误替换', '生成引擎' in o[600:], False)

print(f'\n结果: {passed} 通过 / {failed} 失败')
sys.exit(1 if failed else 0)
