import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')

import ai_service as A

PASS = FAIL = 0

def check(name, cond, got=None):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + ("  → got=%r" % (got,) if got is not None else ""))

print("[A] 未配置温度时的默认阶梯")
d = A._build_temp_ladder(None)
check("None → 0.6 优先", d[0] == 0.6, d)
check("None → 含 1.0 兜底", 1.0 in d, d)
check("None → 含 0.3 兜底", 0.3 in d, d)
check("0 → 0.6 优先（0 视为未配）", A._build_temp_ladder(0)[0] == 0.6, A._build_temp_ladder(0))
check("负数 → 0.6 优先", A._build_temp_ladder(-1)[0] == 0.6)
check("超范围 2.5 → 0.6 优先", A._build_temp_ladder(2.5)[0] == 0.6)
check("非法字符串 → 0.6 优先", A._build_temp_ladder("abc")[0] == 0.6, A._build_temp_ladder("abc"))
check("字符串 '0.6' → 0.6 优先", A._build_temp_ladder("0.6")[0] == 0.6)

print("\n[B] 配置首选温度时必须带兜底（单值 = 无退路，曾会整条挂死）")
for t in (0.6, 1.0, 0.3, 0.2, 0.8):
    r = A._build_temp_ladder(t)
    check(f"首选 {t} 排在第一位", r[0] == t, r)
    check(f"首选 {t} 至少有 2 档兜底", len(r) >= 2, r)
check("首选 0.6 → [0.6,1.0,0.3] 去重无重复",
      A._build_temp_ladder(0.6) == [0.6, 1.0, 0.3], A._build_temp_ladder(0.6))
check("首选 1.0 → 去重后 1.0 不重复出现",
      A._build_temp_ladder(1.0).count(1.0) == 1, A._build_temp_ladder(1.0))
check("首选 0.4 → 阶梯为 [0.4,1.0,0.6,0.3]",
      A._build_temp_ladder(0.4) == [0.4, 1.0, 0.6, 0.3], A._build_temp_ladder(0.4))
check("首选值四舍五入到两位", A._build_temp_ladder(0.666666)[0] == 0.67,
      A._build_temp_ladder(0.666666))

print("\n[C] _profile_temp：探活与真实调用共用同一口径")
check("profile 缺失 → 0.0", A._profile_temp({}) == 0.0)
check("profile 非 dict → 0.0", A._profile_temp({"profile": "x"}) == 0.0)
check("temperature 缺失 → 0.0", A._profile_temp({"profile": {"kind": "reasoning"}}) == 0.0)
check("temperature=1.0 → 1.0", A._profile_temp({"profile": {"temperature": 1.0}}) == 1.0)
check("temperature='0.6' 字符串 → 0.6", A._profile_temp({"profile": {"temperature": "0.6"}}) == 0.6)
check("temperature='xx' 非法 → 0.0", A._profile_temp({"profile": {"temperature": "xx"}}) == 0.0)
check("temperature=None → 0.0", A._profile_temp({"profile": {"temperature": None}}) == 0.0)

print("\n[D] 端到端语义：DB 里每个模型都已配温度，且阶梯合法")
import settings
settings.SETTINGS.pop("AI_MODEL_CHANNELS", None)
missing = []
for c in settings.get_ai_model_channels():
    for m in c["models"]:
        p = m.get("profile") or {}
        if not isinstance(p, dict) or not p.get("temperature"):
            missing.append(m.get("alias"))
        else:
            lad = A._build_temp_ladder(p.get("temperature"))
            assert lad[0] == p["temperature"] and len(lad) >= 2
check("所有模型条目均已配置温度（无遗漏）", not missing, missing)

print("\n[E] 官方口径固化：厂商文档明确给出的温度，不得被无声改回")
OFFICIAL = {
    "kimi-k2.6": 1.0, "Kimi-K2.6": 1.0,
    "mimo-v2.5-pro": 1.0,
    "glm-5.2": 1.0, "GLM-5.2": 1.0, "glm-5.3": 1.0, "glm-5.3-flash": 1.0,
    "minimax-m2.7": 1.0, "MiniMax-M2.7": 1.0,
    "hy4-preview": 0.9,
    "DeepSeek-V4-pro": 0.6, "DeepseekV4Pro": 0.6,
    "qwen3.7-max": 0.6, "qwen3.8-flash-next": 0.6, "Qwen3.5-9B": 0.6,
    "kimi-k3": 1.0,
}
cur = {}
for c in settings.get_ai_model_channels():
    for m in c["models"]:
        p = m.get("profile") or {}
        cur[m.get("alias")] = p.get("temperature")
for alias, want in OFFICIAL.items():
    check(f"{alias} = {want}", cur.get(alias) == want, cur.get(alias))

print("\n[F] max_out 语义：必须是「最大输出」而不是上下文长度")
MODEL_P = {}
for _c in settings.get_ai_model_channels():
    for _m in _c["models"]:
        MODEL_P[_m.get("alias")] = _m.get("profile") or {}
MAXOUT = {
    "qwen3.7-max": 131072,
}
for alias, want in MAXOUT.items():
    got = MODEL_P.get(alias, {}).get("max_out")
    check(f"{alias} max_out = {want}（None=留空）", got == want, got)

print("\n----")
print(f"PASS={PASS} FAIL={FAIL}")
sys.exit(1 if FAIL else 0)
