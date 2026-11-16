const fs = require("fs"), vm = require("vm"), assert = require("assert");
const src = fs.readFileSync(require("path").join(__dirname, "..", "..", "app", "static", "js", "app.js"), "utf8");
// extract the REAL shipped functions (no copies)
const grab = (name) => { const i = src.indexOf("function " + name); let d = 0, j = src.indexOf("{", i); for (let k = j; k < src.length; k++) { if (src[k] === "{") d++; if (src[k] === "}" && --d === 0) return src.slice(i, k + 1); } };
const ctx = { TERMINAL: ["completed", "completed_partial", "failed", "cancelled"], Map, Set, Math };
vm.createContext(ctx);
vm.runInContext(grab("detectTransitions"), ctx);
const st = () => ({ seen: null, baseMax: 0, notified: new Set() });
const J = (id, status) => ({ id, status, video_id: 1 });
let s = st(), out;
// 1. page load while a job is running and an old job is done: baseline is silent
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s, [J(5, "running"), J(4, "completed")])), JSON.stringify([]));
// 2. polling while still running: nothing
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s, [J(5, "running"), J(4, "completed")])), JSON.stringify([]));
// 3. running -> completed: exactly ONE notification
out = ctx.detectTransitions(s, [J(5, "completed_partial"), J(4, "completed")]); assert.strictEqual(JSON.stringify(out.map((j) => j.id)), JSON.stringify([5]));
// 4. keeps polling after completion: NO repeat
for (let i = 0; i < 5; i++) assert.strictEqual(JSON.stringify(ctx.detectTransitions(s, [J(5, "completed_partial"), J(4, "completed")])), JSON.stringify([]));
// 5. page refresh (new state, but sessionStorage-backed notified set survives): baseline silent, no fabricated event
let s2 = { seen: null, baseMax: 0, notified: new Set(s.notified) };
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s2, [J(5, "completed_partial"), J(4, "completed")])), JSON.stringify([]));
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s2, [J(5, "completed_partial"), J(4, "completed")])), JSON.stringify([]));
// 6. reprocess: new job 6 queued -> running -> completed => one notification for job 6 only
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s2, [J(6, "queued"), J(5, "completed_partial")])), JSON.stringify([]));
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s2, [J(6, "running"), J(5, "completed_partial")])), JSON.stringify([]));
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s2, [J(6, "completed"), J(5, "completed_partial")]).map((j) => j.id)), JSON.stringify([6]));
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s2, [J(6, "completed"), J(5, "completed_partial")])), JSON.stringify([]));
// 7. job created AND finished between two polls (never seen active) -> still one notification
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s2, [J(7, "failed"), J(6, "completed")]).map((j) => j.id)), JSON.stringify([7]));
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s2, [J(7, "failed"), J(6, "completed")])), JSON.stringify([]));
// 8. cancelled while queued -> one notification; old finished jobs created before load never notify
let s3 = st(); ctx.detectTransitions(s3, [J(3, "queued"), J(2, "completed")]);
assert.strictEqual(JSON.stringify(ctx.detectTransitions(s3, [J(3, "cancelled"), J(2, "completed")]).map((j) => j.id)), JSON.stringify([3]));
// 9. empty database at load, first job later
let s4 = st(); ctx.detectTransitions(s4, []); assert.strictEqual(JSON.stringify(ctx.detectTransitions(s4, [J(1, "completed")]).map((j) => j.id)), JSON.stringify([1]));
// 10. navigation between pages does not touch watcher state (state lives in WATCH, route() never resets it)
assert(!/function route\(\)[\s\S]*?WATCH/.test(src.slice(src.indexOf("function route()"), src.indexOf("const setTitle"))), "route() must not reset watcher state");
console.log("NOTIFICATION STATE MACHINE: all 10 scenarios passed");
