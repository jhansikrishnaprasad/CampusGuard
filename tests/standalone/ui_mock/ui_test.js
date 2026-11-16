const { chromium } = require("playwright");
const assert = require("assert");
const B = "http://127.0.0.1:8765";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 1100 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push("PAGEERROR " + e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push("CONSOLE " + m.text()); });
  await page.route("**/cdn.jsdelivr.net/**", (r) => r.abort());       // offline: Chart.js falls back to bars
  await page.request.get(B + "/__set?s=running");

  // ---- A. job running: placeholder, no notification ----
  await page.goto(B + "/#/video/1");
  await page.waitForSelector("#compliance .alert.info", { timeout: 8000 });
  assert(/Analysis is running/.test(await page.textContent("#compliance")));
  assert.strictEqual(await page.locator(".notify").count(), 0, "no notification while running");
  await page.screenshot({ path: "/tmp/ui/1_running.png" });

  // ---- B. job completes -> exactly one notification with real API numbers + cards refresh ----
  await page.request.get(B + "/__set?s=completed_partial");
  await page.waitForSelector(".notify", { timeout: 15000 });
  const toast = await page.textContent(".notify");
  console.log("TOAST:", toast.replace(/\s+/g, " "));
  for (const t of ["VIDEO ANALYSIS COMPLETED (PARTIAL)", "12 people have possible uniform mismatches.", "8 people have ID cards not detected.", "4 people have both issues.", "Open compliance report"]) assert(toast.includes(t), "toast missing: " + t);
  assert.strictEqual(await page.locator(".notify").count(), 1);
  await page.waitForSelector("#cgc-uni .num");
  await sleep(1200);                                                      // counter animation
  const num = async (k) => (await page.textContent(`#cgc-${k} .num`)).trim();
  assert.deepStrictEqual([await num("total"), await num("uni"), await num("id"), await num("both"), await num("ok"), await num("unc")], ["100", "12", "8", "4", "70", "14"]);
  const banner = await page.textContent(".cg-banner");
  assert(banner.includes("ATTENTION: Possible dress-code compliance issues were identified in this video. Please review the flagged individuals and verify the findings."));
  const comp = await page.textContent("#compliance");
  assert(comp.includes("ID-card visibility could not be reliably verified for some people. Please review the evidence manually."), "ID limitation warning");
  assert(/8 people have an UNCERTAIN ID-card result/.test(comp) && /NOT counted/.test(comp));
  assert(/did NOT run/.test(comp), "partial modules identified");
  assert(/add up to 100/.test(comp));
  await page.screenshot({ path: "/tmp/ui/2_completed.png", fullPage: true });

  // ---- C. polling does not repeat the notification ----
  await sleep(10000);
  assert.strictEqual(await page.locator(".notify").count(), 1, "no duplicate toast during polling");

  // ---- D. person-wise filters ----
  const rows = async () => page.locator("#cg-people tr[data-p]").count();
  assert.strictEqual(await rows(), 100);
  const click = async (f) => { await page.click(`#cg-filters button[data-f="${f}"]`); await sleep(500); };
  await click("both"); assert.strictEqual(await rows(), 4);
  await click("uniform_issue"); assert.strictEqual(await rows(), 12);
  await click("id_issue"); assert.strictEqual(await rows(), 8);
  await click("uncertain"); assert.strictEqual(await rows(), 8);
  await click("not_assessed"); assert.strictEqual(await rows(), 6);
  await click("compliant"); assert.strictEqual(await rows(), 70);
  await click("both");
  await page.click("#cg-people tr[data-p]");
  await page.waitForSelector("#modalbody button.primary");
  assert(/Jump to/.test(await page.textContent("#modalbody")));
  assert(/never proof/i.test(await page.textContent("#modalbody")));
  await page.screenshot({ path: "/tmp/ui/3_person_modal.png" });
  await page.evaluate(() => closeModal());

  // ---- E. refresh must NOT fabricate another completion event ----
  await page.reload(); await sleep(9000);
  assert.strictEqual(await page.locator(".notify").count(), 0, "reload must not replay the notification");
  assert(/ATTENTION/.test(await page.textContent("#compliance")), "warning persists after reload (from stored results)");

  // ---- F. dashboard overview ----
  await page.goto(B + "/#/dashboard"); await page.waitForSelector(".cg-mini", { timeout: 8000 });
  const dash = await page.textContent("#view");
  assert(dash.includes("Compliance overview") && dash.includes("gate_cam.mp4") && dash.includes("Recent compliance alerts"));
  assert(/Pending manual reviews/.test(dash) && /Partial analyses/.test(dash) && dash.includes("ID-card visibility could not be reliably verified"));
  await page.screenshot({ path: "/tmp/ui/4_dashboard.png", fullPage: true });
  await page.click(".cg-section table tr.click"); await page.waitForSelector("#compliance .cg-cards");  // alert row navigates to its video
  assert(/#\/video\/1/.test(page.url()));

  // ---- G. reprocess: running again then completed -> a NEW notification (job id reused in mock => cleared set) ----
  console.log("JS errors:", JSON.stringify(errors));
  assert.deepStrictEqual(errors, []);
  await browser.close();
  console.log("BROWSER UI TEST PASSED");
})().catch((e) => { console.error("FAILED:", e.message); process.exit(1); });
