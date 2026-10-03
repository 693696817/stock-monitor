// 机会捕捉页内联 JS 的 DOM / fetch 打桩。
// 与 test_market_chart_stubs.js 同一思路：让页面真实渲染出来的 <script> 在 Node 里
// **执行一遍**，而不是只 grep 字符串。区别在于本页没有 Chart.js，
// 但多了一处 DOM 事件（题材榜排序 tab）和一个 fetch 调用（大盘投票），都要能模拟。

const CREATED = [];   // 本页不建图表，留空仅为保持与大盘页桩一致的结构

function _mkEl(id) {
        const el = {
            id: id,
            style: {},
            innerHTML: "",
            innerText: "",
            disabled: false,
            dataset: {},
            _classes: new Set(),
        classList: {
            add(c) { this._o._classes.add(c); },
            remove(c) { this._o._classes.delete(c); },
            contains(c) { return this._o._classes.has(c); },
            toggle(c, f) { if (f) { this._o._classes.add(c); } else { this._o._classes.delete(c); } },
        },
        addEventListener(evt, fn) { this["_on_" + evt] = fn; },
        // tab 点击要能冒泡：模拟 e.target.closest(...)
        querySelectorAll() { return []; },
        getAttribute() { return null; },
        closest() { return null; },
    };
    // ⚠️ 真实 DOM 的 textContent 赋值会强制转成字符串（`el.textContent = 13` 读回来是 "13"）。
    //    桩里不做这层转换，断言 `textContent === String(n)` 就会假失败（13 !== "13"）。
    let _text = "";
    Object.defineProperty(el, "textContent", {
        get() { return _text; },
        set(v) { _text = String(v == null ? "" : v); },
        enumerable: true,
    });
    return el;
}

const _els = {};
function _get(id) {
    if (!_els[id]) {
        const el = _mkEl(id);
        el.classList._o = el;
        _els[id] = el;
    }
    return _els[id];
}

global.__el = _get;
global.__els = _els;
global.__CREATED = CREATED;

global.document = {
    getElementById: _get,
    querySelectorAll() { return []; },
    addEventListener() {},
};

// base.html 提供的转义函数：页面脚本依赖它，桩里按原实现补一份
global.esc = function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
};

// 大盘投票接口：返回「0 票」的真实空态，避免测试被真实票数影响
global.__VOTE_RESP = {
    status: "success", total: 0, up: 0, down: 0,
    up_pct: 0, down_pct: 0, mine: null, logged_in: false,
};
global.fetch = function () {
    return Promise.resolve({
        ok: true,
        json() { return Promise.resolve(global.__VOTE_RESP); },
    });
};

global.location = { pathname: "/opportunities", href: "" };
global.setTimeout = function (fn) { fn(); return 0; };   // 指针动画立即执行
global.window = global;
