console.log('样本：' + rows.length + ' 根 K 线，指标 ' + Object.keys(ind).length + ' 组');

// ---------------------------- 用例 1：默认（成交量 + MACD） ----------------------------
console.log('\n[1] 默认状态：副图 = 成交量 + MACD');
buildSubIndButtons();
restoreIndState();
renderKline(rows, ind, false);
check('生成了 option', !!LAST_OPT);
check('副图按钮数量 == SUB_INDS', SUB_INDS.length === 12, SUB_INDS.length);
check('默认勾选 2 个副图', currentSubKeys().length === 2, currentSubKeys());
check('grid 数 == 主图1 + 副图2', LAST_OPT.grid.length === 3, LAST_OPT.grid.length);
check('xAxis / yAxis 数 == grid 数',
      LAST_OPT.xAxis.length === 3 && LAST_OPT.yAxis.length === 3,
      [LAST_OPT.xAxis.length, LAST_OPT.yAxis.length]);
check('dataZoom 绑定全部 x 轴', JSON.stringify(LAST_OPT.dataZoom[0].xAxisIndex) === '[0,1,2]',
      LAST_OPT.dataZoom[0].xAxisIndex);
check('容器高度 = 520 + 2×96 = 712px', document.getElementById('klineChart').style.height === '712px',
      document.getElementById('klineChart').style.height);

// grid 不重叠、不越界（这是多子图布局最容易翻车的地方）
let prevBottom = 0, overlap = false, overflow = false;
const H = 712, SLIDER_BOTTOM = 6, SLIDER_H = 18;
LAST_OPT.grid.forEach(function (g, i) {
    if (g.top < prevBottom) overlap = true;
    if (g.top + g.height > H - (SLIDER_BOTTOM + SLIDER_H)) overflow = true;
    prevBottom = g.top + g.height;
});
check('grid 互不重叠', !overlap, LAST_OPT.grid.map(function (g) { return [g.top, g.height]; }));
check('grid 不越过底部缩放条', !overflow, LAST_OPT.grid.map(function (g) { return g.top + g.height; }));

// 每条 series 都必须挂在某个 grid 上，且 data 是数组
let badSeries = [];
LAST_OPT.series.forEach(function (s) {
    if (s.type === 'candlestick') return;
    if (typeof s.xAxisIndex !== 'number' || typeof s.yAxisIndex !== 'number') badSeries.push([s.name, 'no-axis']);
    if (!Array.isArray(s.data)) badSeries.push([s.name, 'data 非数组']);
    if (s.data.length !== rows.length) badSeries.push([s.name, '长度 ' + s.data.length]);
});
check('所有 series 都绑定了 axis 且 data 长度对齐', badSeries.length === 0, badSeries.slice(0, 5));
check('图例项与 series 名一一对应', (function () {
    const names = LAST_OPT.series.map(function (s) { return s.name; });
    return LAST_OPT.legend.data.every(function (n) { return names.indexOf(n) >= 0; });
})(), LAST_OPT.legend.data.filter(function (n) {
    return LAST_OPT.series.map(function (s) { return s.name; }).indexOf(n) < 0;
}));

// ---------------------------- 用例 2：每个副图单独渲染 ----------------------------
console.log('\n[2] 12 个副图逐个单独渲染');
SUB_INDS.forEach(function (it) {
    SUB_INDS.forEach(function (o) {
        document.getElementById('sub' + o.key).checked = (o.key === it.key);
    });
    renderKline(rows, ind, false);
    const ok = LAST_OPT.grid.length === 2 && LAST_OPT.series.length >= 2;
    const lines = LAST_OPT.series.filter(function (s) { return s.type === 'line' && s.xAxisIndex === 1; });
    const hasData = lines.every(function (s) {
        return s.data.some(function (v) { return v !== null && v !== undefined; });
    });
    check(it.name + '（' + it.key + '）：面板 + 有数据的曲线', ok && hasData && lines.length > 0,
          { grids: LAST_OPT.grid.length, lines: lines.length, hasData: hasData });
});

// ---------------------------- 用例 3：主图叠加开关 ----------------------------
console.log('\n[3] 主图叠加：MA / BOLL / 九转');
SUB_INDS.forEach(function (o) { document.getElementById('sub' + o.key).checked = false; });
[['全关', false, false, false], ['只 MA', true, false, false],
 ['只 BOLL', false, true, false], ['只九转', false, false, true], ['全开', true, true, true]].forEach(function (c) {
    document.getElementById('ovMa').checked = c[1];
    document.getElementById('ovBoll').checked = c[2];
    document.getElementById('ovTd9').checked = c[3];
    renderKline(rows, ind, false);
    const names = LAST_OPT.series.map(function (s) { return s.name; });
    const hasMa = names.indexOf('MA5') >= 0;
    const hasBoll = names.indexOf('UPPER') >= 0;
    const k = LAST_OPT.series.filter(function (s) { return s.name === 'K线'; })[0];
    const hasTd9 = !!(k && k.markPoint && k.markPoint.data.length);
    check(c[0] + ' → MA=' + hasMa + ' BOLL=' + hasBoll + ' 九转标注=' + hasTd9,
          hasMa === c[1] && hasBoll === c[2] && hasTd9 === c[3], names);
});

// 九转 markPoint 的坐标必须是「x 轴里真实存在的日期」，否则画不出来
const kS = LAST_OPT.series.filter(function (s) { return s.name === 'K线'; })[0];
const dates = LAST_OPT.xAxis[0].data;
const badCoord = (kS.markPoint.data || []).filter(function (p) {
    return dates.indexOf(p.coord[0]) < 0 || !isFinite(p.coord[1]);
});
check('九转 markPoint 坐标合法（日期存在 + y 为有限数）', badCoord.length === 0, badCoord.slice(0, 3));
check('九转只标注 6~9', kS.markPoint.data.every(function (p) { return p.value >= 6 && p.value <= 9; }));

// ---------------------------- 用例 4：副图上限 ----------------------------
console.log('\n[4] 副图上限 3 个');
// 直接把 5 个勾选上（绕过只能点选的事件），验证 renderKline 的布局兜底截断真的生效 ——
// 这模拟的是「localStorage 被写坏 / 未来版本放开上限」时极端状态不能把 grid 撑出容器。
SUB_INDS.slice(0, 5).forEach(function (o) { document.getElementById('sub' + o.key).checked = true; });
renderKline(rows, ind, false);
check('状态被写成 5 个时，布局截断到 ' + SUB_MAX + ' 个（grid=' + LAST_OPT.grid.length + '）',
      LAST_OPT.grid.length === SUB_MAX + 1, { grid: LAST_OPT.grid.length, raw: currentSubKeys() });

// ---------------------------- 用例 5：降级（旧缓存，只有 MA） ----------------------------
console.log('\n[5] 降级路径：indicators 只有前端算的 MA');
const fallback = { ma5: ma(rows, 5), ma10: ma(rows, 10), ma20: ma(rows, 20), ma60: ma(rows, 60) };
renderKline(rows, fallback, true);
check('降级时不画副图（只有主图 1 个 grid）', LAST_OPT.grid.length === 1, LAST_OPT.grid.length);
check('降级时容器高度回到 520px',
      document.getElementById('klineChart').style.height === '520px',
      document.getElementById('klineChart').style.height);
check('降级时 MA 仍然画出来',
      LAST_OPT.series.map(function (s) { return s.name; }).indexOf('MA5') >= 0);

// ---------------------------- 用例 6：tooltip ----------------------------
console.log('\n[6] tooltip 格式化');
const idx = rows.length - 1;
const fakePs = [
    { axisValue: rows[idx].date, seriesName: 'K线', data: [rows[idx].open, rows[idx].close, rows[idx].low, rows[idx].high] },
    { axisValue: rows[idx].date, seriesName: '成交量', marker: '', data: rows[idx].volume },
    { axisValue: rows[idx].date, seriesName: 'MACD', marker: '', data: { value: ind.macd_bar[idx] } },
    { axisValue: rows[idx].date, seriesName: 'RSI6', marker: '', data: ind.rsi6[idx] },
    { axisValue: rows[idx].date, seriesName: '潮汐柱', marker: '', data: { value: null } }
];
const tip = klineTooltip(fakePs);
check('tooltip 含日期', tip.indexOf(rows[idx].date) >= 0);
check('开高低收顺序正确（开≠收 时不显示 undefined）', tip.indexOf('undefined') < 0, tip);
check('null 数据点被跳过（不显示 NaN）', tip.indexOf('NaN') < 0, tip);
console.log('  tooltip 样例: ' + tip.replace(/<br\/>/g, ' | ').replace(/<[^>]+>/g, ''));

console.log('\n' + '='.repeat(60));
if (FAIL) { console.log('FAIL ' + FAIL + ' 项'); process.exit(1); }
console.log('PASS  ECharts 配置结构全部校验通过');
