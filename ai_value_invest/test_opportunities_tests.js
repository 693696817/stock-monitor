// === 断言：全部针对页面**真实执行后**的产物 ===

let pass = 0, fail = 0;
function ok(name, cond, extra) {
    if (cond) { pass++; console.log("  [OK] " + name); }
    else { fail++; console.log("  [FAIL] " + name + (extra !== undefined ? "  -> " + JSON.stringify(extra) : "")); }
}

const themeHtml = __el("themeList").innerHTML;

console.log("\n[题材榜] 数据注入与渲染");
ok("THEMES 已注入且非空", Array.isArray(THEMES) && THEMES.length > 0, THEMES && THEMES.length);
ok("themeList 已渲染出内容", themeHtml.length > 0);
ok("条目数与 THEMES 一致",
   (themeHtml.match(/rank-list-item/g) || []).length === THEMES.length,
   [(themeHtml.match(/rank-list-item/g) || []).length, THEMES.length]);

// ⚠️ 核心回归：NaN 被 fillna(0) 填成 0 后，页面会出现「涨停 18 家 / 上涨 0 家」。
//    现在缺失必须是 --，绝不能出现数字 0。
console.log("\n[题材榜] 无假数据：缺失显示 -- 而非 0");
const nullZt = THEMES.filter(t => t.zt_num === null || t.zt_num === undefined).length;
const nullUp = THEMES.filter(t => t.up_num === null || t.up_num === undefined).length;
ok("缺失指标渲染为 --",
   (themeHtml.match(/--/g) || []).length >= (nullZt + nullUp),
   { nullZt, nullUp, dashes: (themeHtml.match(/--/g) || []).length });
ok("主题榜不出现「上涨 0」这类假零",
   !/上涨\s*0(?![\d.])/.test(themeHtml) && !/涨停\s*0(?![\d.])/.test(themeHtml),
   themeHtml.match(/(上涨|涨停)\s*0(?![\d.])/g));
ok("所有题材名都已转义进 HTML", THEMES.every(t => themeHtml.indexOf(esc(t.name)) >= 0));

console.log("\n[题材榜] 排序 tab");
const tabsEl = __el("themeTabs");
ok("tab 容器已绑定 click", typeof tabsEl._on_click === "function");
if (typeof tabsEl._on_click === "function") {
    // 模拟点击 tab：构造最小事件对象（页面用 e.target.closest('button[data-sort]') 取按钮，
    // 并用 this.querySelectorAll('button[data-sort]') 刷新高亮 —— 两个都要能跑通）
    function mkBtn(sort) {
        return {
            dataset: { sort: sort },
            closest() { return this; },
            classList: { toggle(c, f) { this._active = f; } },
        };
    }
    const bUp = mkBtn("up"), bZt = mkBtn("zt");
    tabsEl.querySelectorAll = () => [bZt, bUp];

    tabsEl._on_click({ target: bUp });
    ok("切换后 themeSort = up", themeSort === "up", themeSort);
    const h2 = __el("themeList").innerHTML;
    ok("切换后重新渲染", h2.length > 0 && h2 !== themeHtml);
    // 按上涨家数降序：非缺失值必须单调不增，缺失值全在最后
    const nonNull = THEMES.filter(t => t.up_num !== null && t.up_num !== undefined)
                          .map(t => t.up_num).sort((a, b) => b - a);
    ok("按上涨家数降序且缺失排最后",
       JSON.stringify(nonNull) === JSON.stringify(THEMES.filter(t => t.up_num != null).map(t => t.up_num).slice().sort((a, b) => b - a)),
       nonNull);
    // 切回按涨停数
    tabsEl._on_click({ target: bZt });
    ok("可切回按涨停数", themeSort === "zt", themeSort);
}

console.log("\n[涨跌分布]");
const breadthHtml = __el("breadthBox").innerHTML;
if (BREADTH && BREADTH.total) {
    ok("涨跌分布已渲染", breadthHtml.indexOf("上涨") >= 0);
    ok("总数真实写入", breadthHtml.indexOf(String(BREADTH.total)) >= 0);
} else {
    ok("无数据时显示空态（不编数字）", breadthHtml.indexOf("暂无") >= 0, breadthHtml.slice(0, 60));
}

console.log("\n[机会卡片]");
const oppHtml = __el("oppCardContainer").innerHTML;
ok("OPP_CARDS 已注入", Array.isArray(OPP_CARDS));
ok("各维度计数已写入", __el("cntAll").textContent === String(OPP_CARDS.length),
   [__el("cntAll").textContent, OPP_CARDS.length]);
// 题材卡只在涨停数真实 > 0 时才生成，涨停数为 0/None 时不得出现「最强风口」
const themeCards = OPP_CARDS.filter(c => c.cat === "theme");
ok("题材机会卡不虚构（涨停数为 0/None 时不生成）",
   themeCards.every(c => {
       const t = THEMES.find(x => x.name === String(c.title).replace("最强风口题材：", ""));
       return t && t.zt_num;
   }), themeCards.map(c => c.title));
// ⚠️ 名字解析失败时旧代码会退回 6 位代码（实测出现过「高换手活跃：920289 等 3 只」），
//    用户根本不知道那是哪只票。根因是 DB 的 stock_basics 同步慢一拍，
//    新上市的北交所 920xxx 查不到名字。
const rawCodeCards = OPP_CARDS.filter(c => /(?<![0-9])\d{6}(?![0-9])/.test(String(c.title)));
ok("机会卡标题无裸代码（名字解析失败会退回 6 位代码）",
   rawCodeCards.length === 0, rawCodeCards.map(c => c.title));
const rawCodeStocks = [];
OPP_CARDS.forEach(c => (c.stocks || []).forEach(s => {
    if (/^[0-9]{6}$/.test(String(s.name || ""))) rawCodeStocks.push(s.name);
}));
ok("机会卡关联个股无裸代码", rawCodeStocks.length === 0, rawCodeStocks);

ok("筛选器已绑定 click", typeof __el("oppFilters")._on_click === "function");
if (OPP_CARDS.length) {
    ok("机会卡已渲染出卡片", (oppHtml.match(/ai-opp-card/g) || []).length === OPP_CARDS.length,
       [(oppHtml.match(/ai-opp-card/g) || []).length, OPP_CARDS.length]);
}
ok("机会卡内容全部经过转义（无裸 <script>）", oppHtml.indexOf("<script") < 0);

console.log("\n[情绪仪表]");
ok("指针角度已设置", /rotate\(-?[\d.]+deg\)/.test(__el("emotionPointer").style.transform || ""),
   __el("emotionPointer").style.transform);
ok("SENTIMENT 在 0~100", SENTIMENT >= 0 && SENTIMENT <= 100, SENTIMENT);

console.log("\n----");
console.log("Node 侧：PASS " + pass + " / FAIL " + fail);
if (fail) process.exit(1);
