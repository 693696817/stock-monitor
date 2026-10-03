// 大盘页图表渲染断言。执行顺序：stubs → 页面内联 JS → 本文件。

let PASS = 0, FAIL = 0;
function ok(name, cond, extra) {
    if (cond) { PASS++; console.log("  ✅ " + name); }
    else { FAIL++; console.log("  ❌ " + name + (extra !== undefined ? "  → " + JSON.stringify(extra) : "")); }
}

const C = global.__CREATED;
const byId = {};
C.forEach(c => { if (c.canvasId) { byId[c.canvasId] = c; } });

console.log("\n[渲染] 图表实例");
// ⭐ 最重要的一条：能走到这里，说明整段脚本**没有抛运行时异常**。
//    TDZ / TypeError 这类会让脚本第一行就死，结果是所有图表全空白。
ok("脚本执行完毕未抛异常（能拦住 TDZ 类错误）", true);

const ids = C.map(c => c.canvasId);
console.log("      创建了 %d 张图：%s", C.length, ids.join(", "));

ok("上证走势图已创建", !!byId["sentimentChart"], ids);
ok("主力资金流向图已创建", !!byId["moneyFlowChart"], ids);
ok("连板天梯图已创建", !!byId["ladderChart"], ids);
ok("三张指数 sparkline 已创建",
   !!byId["miniChart1"] && !!byId["miniChart2"] && !!byId["miniChart3"], ids);
ok("图表总数 6 张（走势+资金流+天梯+3 sparkline）", C.length === 6, C.length);

console.log("\n[配置] 每张图的类型与数据");
if (byId["sentimentChart"]) {
    const s = byId["sentimentChart"];
    ok("上证走势是 line", s.type === "line", s.type);
    const pts = s.data.datasets[0].data;
    ok("上证走势有数据点", Array.isArray(pts) && pts.length > 0, pts && pts.length);
    ok("上证走势数据无 null/undefined", pts.every(v => typeof v === "number" && isFinite(v)),
       pts.filter(v => typeof v !== "number" || !isFinite(v)));
    // ⚠️ 曾经写死 min:0/max:100，而数据是 3800~4000 的指数点位 → 整条线画在轴外
    const y = (s.options && s.options.scales && s.options.scales.y) || {};
    ok("上证走势 y 轴未写死 0~100", !(y.min === 0 && y.max === 100), y);
    ok("上证走势 y 轴自适应（beginAtZero:false）", y.beginAtZero === false, y);
    console.log("      y 轴：%s | 数据 %d 点，范围 %s ~ %s",
                JSON.stringify(y), pts.length, Math.min(...pts), Math.max(...pts));
}
if (byId["moneyFlowChart"]) {
    const m = byId["moneyFlowChart"];
    ok("资金流向是 bar", m.type === "bar", m.type);
    const v = m.data.datasets[0].data;
    ok("资金流向 3 个柱（沪股通/深股通/北向合计）", v.length === 3, v);
    ok("资金流向数值为有限数", v.every(x => typeof x === "number" && isFinite(x)), v);
}
if (byId["ladderChart"]) {
    const l = byId["ladderChart"];
    ok("连板天梯是 bar", l.type === "bar", l.type);
    const d = l.data.datasets[0].data;
    ok("连板天梯有数据点", d.length > 0, d.length);
    ok("连板天梯板数为非负整数", d.every(x => Number.isInteger(x) && x >= 0), d.slice(0, 5));
    ok("连板天梯标签与数据等长", l.data.labels.length === d.length,
       [l.data.labels.length, d.length]);
    console.log("      天梯 %d 点，最高 %d 板", d.length, Math.max(...d));
}
["miniChart1", "miniChart2", "miniChart3"].forEach(id => {
    if (byId[id]) {
        const p = byId[id].data.datasets[0].data;
        ok(id + " 有数据", p.length > 0, p.length);
    }
});

// 恐惧贪婪条的 marker/刻度是**静态 HTML**（内联 style），由 Jinja 渲染，
// JS 不参与 —— 所以不在这里断言，改由 Python 侧对 HTML 做检查。

console.log("\n---- PASS " + PASS + " / FAIL " + FAIL + " ----");
process.exit(FAIL ? 1 : 0);
