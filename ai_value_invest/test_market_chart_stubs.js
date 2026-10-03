// 大盘页内联 JS 的 DOM / Chart.js 打桩。
// 目的：让页面的 <script> 能在 Node 里**真正跑一遍**，
// 从而抓到 check_js.py（只做语法检查）查不到的运行时错误 —— 典型就是
// 「const 声明前访问」的 TDZ ReferenceError：语法完全合法，但整段脚本第一行就死，
// 页面上表现为「所有图表全空白」，控制台也只有一句报错。

const CREATED = [];   // 记录每一次 new Chart(...)

function _mkEl(id) {
    return {
        id: id,
        style: {},
        innerText: "",
        title: "",
        _classes: new Set(),
        classList: {
            add(c) { this._o._classes.add(c); },
            remove(c) { this._o._classes.delete(c); },
            contains(c) { return this._o._classes.has(c); },
            toggle(c, f) { if (f) { this._o._classes.add(c); } else { this._o._classes.delete(c); } },
        },
        addEventListener(evt, fn) { this["_on_" + evt] = fn; },
        querySelectorAll() { return []; },
        getAttribute() { return null; },
        getContext() {
            // 带上 __canvasId，断言里才能知道这张图挂在哪个 canvas 上
            return {
                __canvasId: id,
                createLinearGradient() { return { addColorStop() {} }; },
            };
        },
    };
}

const _els = {};
global.document = {
    getElementById(id) {
        if (!_els[id]) {
            const el = _mkEl(id);
            el.classList._o = el;
            _els[id] = el;
        }
        return _els[id];
    },
    querySelectorAll() { return []; },
    addEventListener() {},
};

global.Chart = class Chart {
    constructor(ctx, config) {
        CREATED.push({
            canvasId: (ctx && ctx.__canvasId) || null,
            type: config && config.type,
            data: config && config.data,
            options: config && config.options,
        });
    }
};
global.Chart.defaults = { color: "", borderColor: "", font: { family: "" } };

global.window = global;
global.__CREATED = CREATED;
