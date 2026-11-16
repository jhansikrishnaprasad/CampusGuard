const { chromium } = require("playwright");
const OUT = "/home/claude/work/campus_safety/docs/screenshots/";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1400, height: 950 } });
  await p.route("**/cdn.jsdelivr.net/**", (r) => r.abort());
  await p.request.get("http://127.0.0.1:8765/__set?s=completed_partial");
  await p.goto("http://127.0.0.1:8765/#/dashboard"); await p.waitForSelector(".cg-mini"); await sleep(1800);
  await p.screenshot({ path: OUT + "01_dashboard_compliance_overview.png" });
  await p.goto("http://127.0.0.1:8765/#/video/1"); await p.waitForSelector("#cgc-uni .num"); await sleep(1800);
  await p.evaluate(() => document.querySelectorAll(".notify").forEach((n) => n.remove()));
  await p.screenshot({ path: OUT + "02_video_compliance_alerts.png" });
  await p.evaluate(() => document.querySelector("#cg-filters").scrollIntoView({ block: "start" })); await sleep(500);
  await p.screenshot({ path: OUT + "03_person_wise_review.png" });
  await p.click('#cg-filters button[data-f="both"]'); await sleep(500); await p.click("#cg-people tr[data-p]"); await p.waitForSelector("#modalbody button.primary"); await sleep(400);
  await p.screenshot({ path: OUT + "04_person_evidence_modal.png" });
  await b.close(); console.log("shots done");
})().catch((e) => { console.error(e.message); process.exit(1); });
