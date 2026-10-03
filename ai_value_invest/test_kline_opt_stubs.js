/* ECharts 配置生成的结构性自检（Node 端，无需浏览器）。
   目的：catch「代码不报错但图画不出来」这类静默失效——
   series 少了、grid 数量不对、data 数组 undefined、markPoint 坐标非法，
   这些在浏览器里表现为「图是空的/只有一半」，日志里却什么都看不到。

   由 test_kline_chart_option.py 驱动：它会把「打桩 + 模板 K 线代码 + 断言」
   拼成一个完整脚本再交给 node（不能 eval，const/let 泄漏不出来）。
   数据取自真实接口（_kline_opt_gen_data.json，跑完自动删除）。 */
const fs = require('fs');
const path = require('path');

const data = JSON.parse(fs.readFileSync(path.join(__dirname, '_kline_opt_gen_data.json'), 'utf8'));
const rows = data.data;
const ind = data.indicators;
let FAIL = 0;
function check(name, cond, detail) {
    if (cond) { console.log('  OK   ' + name); }
    else { FAIL++; console.log('  FAIL ' + name + '  ' + JSON.stringify(detail === undefined ? '' : detail)); }
}

// ------------------------- DOM / 库打桩 -------------------------
const els = {};
function mkEl(id) {
    return { id: id, style: {}, innerHTML: '', checked: false, offsetWidth: 0,
             classList: { add: function () {}, remove: function () {} },
             addEventListener: function () {} };
}
global.document = {
    getElementById: function (id) { if (!els[id]) els[id] = mkEl(id); return els[id]; },
    querySelector: function () { return { value: '120' }; },
    querySelectorAll: function () { return []; }
};
global.window = { innerWidth: 1440 };
global.localStorage = { getItem: function () { return null; }, setItem: function () {} };
let LAST_OPT = null;
// ⚠️ 假 chart 必须带 on/off：模板 attachReadoutReset() 会调 klineChart.off('globalout')
//    + klineChart.on('globalout', ...)，缺了会在 node 里 TypeError 直接崩掉整个测试。
const _chartHandlers = {};
global.echarts = {
    init: function () {
        return {
            setOption: function (o) { LAST_OPT = o; },
            resize: function () {},
            dispose: function () {},
            on: function (ev, fn) { (_chartHandlers[ev] = _chartHandlers[ev] || []).push(fn); },
            off: function (ev) { if (ev) { _chartHandlers[ev] = []; } }
        };
    }
};
function empty(m) { return String(m); }
function esc(m) { return String(m); }
let klineChart = null;

