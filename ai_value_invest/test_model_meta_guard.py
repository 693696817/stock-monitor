import sys
import io
import json
import copy

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')

PASS = [0, 0]

def ck(name, cond, extra=""):
    PASS[0] += 1
    PASS[1] += 1 if cond else 0
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (("  -> " + str(extra)) if extra else ""))

def _mk(alias, tagline, logo, mid=None):
    return {"id": mid or ("id_" + alias), "alias": alias, "model_id": alias,
            "enabled": True, "vip_only": False, "featured": False,
            "tagline": tagline, "logo": logo, "profile": {}}

OLD = [{"id": "ch1", "name": "渠道A", "models": [
    _mk("ma", "文案A", "logoA"), _mk("mb", "文案B", "logoB"), _mk("mc", "文案C", "logoC")]}]

def run(new_chans):
    guard.settings.get_ai_model_channels = lambda: copy.deepcopy(OLD)
    return guard._model_meta_wipe_check(json.dumps(new_chans, ensure_ascii=False))

print("=" * 78)
print("[A] 纯函数判定")
print("=" * 78)

same = copy.deepcopy(OLD)
ck("A1 原样保存放行", run(same) is None)

stale = copy.deepcopy(OLD)
for m in stale[0]["models"]:
    m["tagline"] = ""
r = run(stale)
ck("A2 全量抹空 tagline → 拦截", r is not None and "一句话特色" in r and "3" in r, r)

stale_logo = copy.deepcopy(OLD)
for m in stale_logo[0]["models"]:
    m["logo"] = ""
r = run(stale_logo)
ck("A3 全量抹空 logo → 拦截", r is not None and "Logo" in r, r)

one = copy.deepcopy(OLD)
one[0]["models"][0]["tagline"] = ""
ck("A4 只清 1 条 → 放行（用户有意删除）", run(one) is None)

two = copy.deepcopy(OLD)
two[0]["models"][0]["tagline"] = ""
two[0]["models"][1]["tagline"] = ""
ck("A5 清 2 条 / 共 3 条有值 → 放行", run(two) is None)

new_entry = copy.deepcopy(OLD)
new_entry[0]["models"].append(_mk("md", "", "", mid="id_md"))
ck("A6 新增空条目 → 放行", run(new_entry) is None)

ck("A7 非法 JSON → 放行（交给正规流程报错）",
   guard._model_meta_wipe_check("这不是JSON") is None)
ck("A8 非列表 → 放行", guard._model_meta_wipe_check('{"a":1}') is None)
ck("A9 空串 → 放行", guard._model_meta_wipe_check("") is None)

guard.settings.get_ai_model_channels = lambda: [
    {"id": "ch1", "models": [_mk("ma", "文案A", "logoA"), _mk("mb", "", "logoB")]}]
solo = [{"id": "ch1", "models": [_mk("ma", "", "logoA"), _mk("mb", "", "logoB")]}]
ck("A10 仅 1 条有值被清 → 放行（≥2 才拦）",
   guard._model_meta_wipe_check(json.dumps(solo, ensure_ascii=False)) is None)

guard.settings.get_ai_model_channels = lambda: [
    {"id": "ch1", "models": [{"alias": "ma", "tagline": "文案A", "logo": "l"},
                             {"alias": "mb", "tagline": "文案B", "logo": "l"}]}]
noid = [{"id": "ch1", "models": [{"alias": "ma", "tagline": "", "logo": "l"},
                                 {"alias": "mb", "tagline": "", "logo": "l"}]}]
ck("A11 无 id 时按 alias 匹配 → 仍能拦截",
   guard._model_meta_wipe_check(json.dumps(noid, ensure_ascii=False)) is not None)

print()
print("=" * 78)
print("[B] HTTP 层（需 8015 在跑）")
print("=" * 78)
try:
    import auth
    import urllib.request
    import urllib.error

    BASE = "http://127.0.0.1:8015"
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    hdr = {"Cookie": "geek_session=" + auth._sign({"uid": 1})}

    with op.open(urllib.request.Request(BASE + "/api/admin/settings", headers=hdr), timeout=60) as r:
        cur = json.loads(json.loads(r.read().decode("utf-8", "ignore"))["settings"]["AI_MODEL_CHANNELS"])
    rows = [m for c in cur for m in c["models"]]
    ck("B1 基线 tagline 齐全", sum(1 for m in rows if (m.get("tagline") or "").strip()) == len(rows),
       f"{sum(1 for m in rows if (m.get('tagline') or '').strip())}/{len(rows)}")

    def post(payload):
        req = urllib.request.Request(BASE + "/api/admin/settings", method="POST",
                                     data=json.dumps({"settings": payload}).encode(),
                                     headers={"Content-Type": "application/json", **hdr})
        try:
            with op.open(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8", "ignore"))

    stale = copy.deepcopy(cur)
    for c in stale:
        for m in c["models"]:
            m["tagline"] = ""
    code, body = post({"AI_MODEL_CHANNELS": json.dumps(stale, ensure_ascii=False)})
    ck("B2 旧快照全量抹空 → 409", code == 409 and "已阻止本次保存" in (body.get("detail") or ""), code)

    code2, body2 = post({"AI_MODEL_CHANNELS": json.dumps(cur, ensure_ascii=False)})
    ck("B3 原样重发 → 200 放行", code2 == 200 and body2.get("status") == "success", code2)

    with op.open(urllib.request.Request(BASE + "/api/analysis-options"), timeout=60) as r:
        j = json.loads(r.read().decode("utf-8", "ignore"))
    models = j.get("models", [])
    ck("B4 前台可见模型 tagline 全透传",
       sum(1 for m in models if (m.get("tagline") or "").strip()) == len(models),
       f"{sum(1 for m in models if (m.get('tagline') or '').strip())}/{len(models)}")
except Exception as e:
    print("  [SKIP] HTTP 层跳过：%s: %s" % (type(e).__name__, e))

print()
print("=" * 78)
print("结果：%d/%d 通过" % (PASS[1], PASS[0]))
print("=" * 78)
sys.exit(0 if PASS[1] == PASS[0] else 1)
