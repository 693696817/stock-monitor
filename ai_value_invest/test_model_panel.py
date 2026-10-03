import sys
import json
import re
import urllib.request
import urllib.error
import auth
import settings

BASE = "http://127.0.0.1:8015"
PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + "  " + str(detail))

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def get(path, cookie=None):
    req = urllib.request.Request(BASE + path)
    if cookie:
        req.add_header("Cookie", cookie)
    return _opener.open(req, timeout=60).read().decode("utf-8", "ignore")

def post(path, body, cookie=None):
    req = urllib.request.Request(BASE + path, method="POST",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with _opener.open(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")

def main():
    admin_cookie = "geek_session=" + auth._sign({"uid": 1})

    def fresh_channels():
        settings.SETTINGS.pop("AI_MODEL_CHANNELS", None)
        return settings.get_ai_model_channels()

    print("[A] /api/analysis-options 透传 featured / tagline / logo")
    raw = get("/api/analysis-options", admin_cookie)
    j = json.loads(raw)
    models = j.get("models", [])
    check("models 不为空", len(models) > 0, "0 个模型")
    if models:
        m = models[0]
        check("每条模型都带 featured 字段（bool）", "featured" in m and isinstance(m["featured"], bool))
        check("每条模型都带 tagline 字段（str）", "tagline" in m and isinstance(m["tagline"], str))
        check("每条模型都带 logo 字段（str）", "logo" in m and isinstance(m["logo"], str))

    print("[B] 旧配置自动补默认空值，不会失踪")
    acs = fresh_channels()
    dirty = False
    for c in acs:
        for m in c.get("models", []):
            if m.get("featured") or m.get("tagline") or m.get("logo"):
                m["featured"] = False
                m["tagline"] = ""
                m["logo"] = ""
                dirty = True
    if dirty:
        post("/api/admin/settings",
             {"settings": {"AI_MODEL_CHANNELS": json.dumps(acs, ensure_ascii=False)}},
             admin_cookie)
        acs = fresh_channels()

    raw = get("/api/analysis-options", admin_cookie)
    j = json.loads(raw)
    models = j.get("models", [])
    featured_list = [m for m in models if m["featured"]]
    check("重置后默认所有模型 featured=False", len(featured_list) == 0,
          "仍有 %d 个 featured" % len(featured_list))
    tagged_list = [m for m in models if m["tagline"]]
    check("重置后默认所有模型 tagline=空", len(tagged_list) == 0,
          "仍有 %d 个非空 tagline" % len(tagged_list))

    print("[C] 后台写入 featured + tagline + logo 立刻生效")
    acs = fresh_channels()
    target = acs[0]["models"][0]
    target["featured"] = True
    target["tagline"] = "测试特色文案-A"
    target["logo"] = "🚀"
    payload = {"settings": {"AI_MODEL_CHANNELS": json.dumps(acs, ensure_ascii=False)}}
    code, _ = post("/api/admin/settings", payload, admin_cookie)
    check("后台保存 AI_MODEL_CHANNELS 返回 success", code == 200, code)

    raw2 = get("/api/analysis-options", admin_cookie)
    j2 = json.loads(raw2)
    target_id = target["id"]
    hit = next((m for m in j2["models"] if m["id"] == target_id), None)
    check("保存后的模型出现在列表", hit is not None, target_id)
    if hit:
        check("featured=True 已透传", hit["featured"] is True, hit["featured"])
        check("tagline 已透传", hit["tagline"] == "测试特色文案-A", hit["tagline"])
        check("logo 已透传", hit["logo"] == "🚀", hit["logo"])

    print("[D] 至少一个 featured 模型，验证排序逻辑")
    featured_ids = [m["id"] for m in j2["models"] if m["featured"]]
    check("有 featured 模型（用于置顶验证）", len(featured_ids) >= 1,
          "%d 个" % len(featured_ids))

    print("[E] 分析页 HTML 含新版 CSS hook（avatar / tagline / 推荐组 / 普通标签）")
    html = get("/analysis", admin_cookie)
    check("存在 .mavatar 头像样式", ".mavatar" in html)
    check("存在 .mpanel-rec-title 推荐组标题样式", ".mpanel-rec-title" in html)
    check("存在 .mpanel-tagline 一句话特色样式", ".mpanel-tagline" in html)
    check("存在「推荐模型」分组文案", "推荐模型" in html)
    html_body_only = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    html_body_only = re.sub(r"//.*?$", "", html_body_only, flags=re.MULTILINE)
    check("不再出现「免费模型」分組文案（旧版）", "免费模型" not in html_body_only)
    check("存在「普通模型」分组文案", "普通模型" in html)
    check("存在 badge-model.norm 样式（普通标签）", "badge-model norm" in html)
    check("头像支持站内 /static/ 上传图", r"\/static\/" in html)

    print("[F] Logo 上传接口（管理员 + 图片白名单 + uuid 落盘 + 静态可访问）")
    import struct, zlib, os
    cookie = admin_cookie
    B = "----wbUploadBoundary"
    def req_body(fname, ctype, payload):
        return (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                 % (B, fname, ctype)).encode() + payload + ("\r\n--%s--\r\n" % B).encode())
    def make_png():
        def chunk(t, d):
            c = struct.pack(">I", len(d)) + t + d
            return c + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        idat = zlib.compress(b"\x00\xff\x00\x00")
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b""))
    def post_upload(fname, ctype, payload, use_cookie=True):
        req = urllib.request.Request(BASE + "/api/admin/models/upload-logo", method="POST",
                                     data=req_body(fname, ctype, payload),
                                     headers={"Content-Type": "multipart/form-data; boundary=" + B})
        if use_cookie:
            req.add_header("Cookie", cookie)
        try:
            with _opener.open(req, timeout=60) as r:
                return r.status, json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())
    code, d = post_upload("t.png", "image/png", make_png())
    check("上传 PNG 返回 success + URL", code == 200 and d.get("status") == "success" and d.get("url"), (code, d))
    up_url = (d or {}).get("url") or ""
    if up_url:
        try:
            with _opener.open(BASE + up_url, timeout=30) as r:
                check("上传文件可静态访问", r.status == 200 and r.headers.get("Content-Type", "").startswith("image/"),
                      (r.status, r.headers.get("Content-Type")))
        except Exception as e:
            check("上传文件可静态访问", False, str(e))
        p = os.path.join("static", "uploads", "models", up_url.rsplit("/", 1)[-1])
        if os.path.exists(p):
            os.remove(p)
    code, d = post_upload("evil.exe", "application/octet-stream", b"hello")
    check("非图片扩展名被拒绝（400）", code == 400, (code, d))
    code, _ = post_upload("t.png", "image/png", make_png(), use_cookie=False)
    check("匿名上传被拒（401/403）", code in (401, 403), code)

    acs = fresh_channels()
    target = next((m for c in acs for m in c.get("models", []) if m["id"] == target_id), None)
    if target:
        target["featured"] = False
        target["tagline"] = ""
        target["logo"] = ""
        payload = {"settings": {"AI_MODEL_CHANNELS": json.dumps(acs, ensure_ascii=False)}}
        post("/api/admin/settings", payload, admin_cookie)

    print("[G] 后台页面加载归一化 normalizeAiChannels 不透传丢字段（node 级回归）")
    import os as _os
    import subprocess as _sp
    html_path = _os.path.abspath(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                               "templates", "admin_settings.html"))
    node_js = r"""
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
let FAIL = 0;
function check(name, cond, detail) {
    if (cond) { console.log('  OK   ' + name); }
    else { FAIL++; console.log('  FAIL ' + name + '  ' + JSON.stringify(detail === undefined ? '' : detail)); }
}
// 抽函数体：normalizeAiChannels 引用了紧邻上方的 parseProfileJson / normProfile
//（2026-09-07 模型差异化 profile 透传），所以从 parseProfileJson 切到 normalize 收尾，
// 用 IIFE 包起来避免「return 多段函数声明」语法错。
const marker = 'function normalizeAiChannels(list) {';
const i0 = html.indexOf(marker);
if (i0 < 0) { console.log('  FAIL marker normalizeAiChannels 未找到'); process.exit(1); }
const h0 = html.indexOf('function parseProfileJson(s) {');
if (h0 < 0 || h0 >= i0) { console.log('  FAIL marker parseProfileJson 未找到'); process.exit(1); }
let i = html.indexOf('{', i0), depth = 0;
for (; i < html.length; i++) {
    if (html[i] === '{') depth++;
    else if (html[i] === '}') { depth--; if (depth === 0) break; }
}
const fnSrc = html.slice(h0, i + 1);
const fn = new Function('return (function(){' + fnSrc + '; return normalizeAiChannels; })()')();

// 1) 新结构渠道：三个新字段必须原样透传；缺失字段的旧模型补默认且不炸
const r1 = fn([{ id: 'c1', name: '渠道A', models: [
    { id: 'm1', alias: 'qwen3.7-max', model_id: 'qwen3.7-max', enabled: true,
      vip_only: true, featured: true, tagline: '深度推理标杆', logo: '\uD83D\uDCA0' },
    { id: 'm2', alias: '旧模型', model_id: 'x', enabled: false }
]}]);
const a = r1[0].models[0];
check('featured=true 透传', a.featured === true);
check('tagline 透传', a.tagline === '深度推理标杆');
check('logo 透传', a.logo === '\uD83D\uDCA0');
const b = r1[0].models[1];
check('缺新字段补默认 featured=false', b.featured === false, b.featured);
check('缺新字段补默认 tagline=""', b.tagline === '', b.tagline);
check('缺新字段补默认 logo=""', b.logo === '', b.logo);
check('原有键不被破坏', b.id === 'm2' && b.enabled === false && b.vip_only === false);

// 1b) 2026-09-07 模型差异化：profile 透传 + 白名单清洗 + 缺省补 {}
const r3 = fn([{ id: 'c9', name: '渠道九', models: [
    { id: 'p1', alias: 'm1', model_id: 'm1', enabled: true, vip_only: false,
      profile: { kind: 'reasoning', temperature: '1.0', max_out: 131072,
                 tokens: { deep: 32000 }, instruction: '全程中文', spec: 'x',
                 junk: '应被丢', badtemp: 99 } },
    { id: 'p2', alias: 'm2', model_id: 'm2', enabled: true }
]}]);
const pp = r3[0].models[0].profile;
check('profile kind 透传', pp.kind === 'reasoning', pp.kind);
check('profile temperature 归一为数字', pp.temperature === 1, pp.temperature);
check('profile max_out 透传', pp.max_out === 131072, pp.max_out);
// ⚠️ 曾有 ctx 键（本地 Ollama num_ctx），已移除：实测 /v1/chat/completions 不认该参数，
//    配了不生效，只会让后台显示假象。相关配置改在 Ollama 侧 Modelfile 固化。
check('profile tokens.deep 透传', pp.tokens && pp.tokens.deep === 32000, JSON.stringify(pp.tokens));
check('profile 未知键被清洗', !('junk' in pp) && pp.badtemp === undefined, JSON.stringify(pp));
check('profile 缺省补 {}', JSON.stringify(r3[0].models[1].profile) === '{}', JSON.stringify(r3[0].models[1].profile));

// 2) 旧结构渠道（无 models 数组）→ 补默认模型且三字段为空默认值
const r2 = fn([{ id: 'volcano', name: '火山', model: 'ep-x', enabled: true }]);
const d = r2[0].models[0];
check('旧结构补默认模型', Array.isArray(r2[0].models) && r2[0].models.length === 1);
check('旧结构三字段默认空值', d.featured === false && d.tagline === '' && d.logo === '');

// 3) 空数组 / 空输入不崩
check('空数组输入返回空', JSON.stringify(fn([])) === '[]');
check('null 输入返回空', JSON.stringify(fn(null)) === '[]');

process.exit(FAIL ? 1 : 0);
"""
    tmp_js = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "_model_norm_test.js")
    try:
        with open(tmp_js, "w", encoding="utf-8") as f:
            f.write(node_js)
        NODE = _os.environ.get("NODE_BIN", "node")
        try:
            p = _sp.run([NODE, tmp_js, html_path], capture_output=True, text=True,
                        timeout=60, encoding="utf-8", errors="replace")
        except Exception as e:
            check("node 可执行（可用 NODE_BIN 指定）", False, str(e))
            p = None
        if p is not None:
            sys.stdout.write(p.stdout)
            sys.stdout.write(p.stderr[-500:] if p.returncode != 0 and p.stderr else "")
            check("normalizeAiChannels 回归全绿", p.returncode == 0,
                  "node 退出码 %s" % p.returncode)
    finally:
        if _os.path.exists(tmp_js):
            _os.remove(tmp_js)

    print("\n----\nPASS=%d FAIL=%d" % (PASS, FAIL))
    return 1 if FAIL else 0

if __name__ == "__main__":
    sys.exit(main())
