import { expect, test, type Page } from "@playwright/test";

/**
 * Replays the PRD 7.3 demo (docs/DEMO.md) with two browsers on one backend: a 360px driver phone
 * and a 1920x1080 operator screen. Step 1 (problem statement slides) and step 7 (roadmap talk)
 * are presentation only. Screenshots land in ../docs/screenshots.
 */

const SHOTS = "../docs/screenshots";
const MOBILE = { width: 360, height: 780 };
const OPS = { width: 1920, height: 1080 };

async function verticalOverflow(page: Page): Promise<number> {
  return page.evaluate(
    () => document.documentElement.scrollHeight - document.documentElement.clientHeight,
  );
}

async function numberIn(page: Page, testId: string): Promise<number> {
  const text = (await page.getByTestId(testId).textContent()) ?? "";
  return Number.parseFloat(text.replace(/[^0-9.\-]/g, ""));
}

test("PRD 7.3 demo: driver phone and operator screen share one live session", async ({ browser }) => {
  const opsCtx = await browser.newContext({ viewport: OPS, locale: "ko-KR" });
  const phoneCtx = await browser.newContext({ viewport: MOBILE, locale: "ko-KR", hasTouch: true });
  const ops = await opsCtx.newPage();
  const phone = await phoneCtx.newPage();
  const consoleErrors: string[] = [];
  for (const [name, page] of [["ops", ops], ["phone", phone]] as const) {
    page.on("console", (m) => {
      if (m.type() === "error") consoleErrors.push(`${name}: ${m.text()}`);
    });
    page.on("pageerror", (e) => consoleErrors.push(`${name}: ${e.message}`));
  }

  // --- before the demo: operator loads the demo scenario with the clock stopped ------------------
  await ops.goto("/ops");
  await expect(ops.getByText("실시간 연결")).toBeVisible();
  await ops.getByTestId("sim-reset").click();
  await ops.getByTestId("sim-reset").click(); // two-step confirm
  await expect(ops.getByTestId("sim-toggle")).toHaveText(/시작/);
  await expect(ops.getByTestId("kpi-turnover")).toContainText("집계 중");

  // --- step 2: driver enters Ioniq 5, 20 -> 90 %, charger 2 (100 kW) --------------------------------
  await phone.goto("/m");
  await phone.getByRole("link", { name: "내 차량 등록" }).click();
  await phone.getByRole("radio", { name: /아이오닉 5/ }).click();
  await phone.getByLabel("목표 충전량(%)").fill("90");
  await phone.getByRole("radio", { name: /2번 · 100 kW/ }).click();
  await phone.getByRole("button", { name: /계산 근거/ }).click();
  await expect(phone.getByText("36.7분").first()).toBeVisible(); // PRD 3.3 / E-01 verification case
  await expect(phone.getByText(/예상 37분/)).toBeVisible();
  await phone.screenshot({ path: `${SHOTS}/m-register-360.png` });

  // opt in to the "left plugged in" driver, so step 5 can show the operator's reminder on the phone
  await phone.getByText("시연 옵션").click();
  await phone.getByLabel(/충전 완료 후 차량 이동/).selectOption("12");
  await phone.getByRole("button", { name: "대기 등록" }).click();

  // --- step 3: queue timeline, then the operator adds three more cars -------------------------------
  await expect(phone).toHaveURL(/\/m\/queue/);
  await expect(phone.getByText(/내 앞 \d+대/)).toBeVisible();
  for (let i = 0; i < 3; i++) await ops.getByTestId("add-vehicle").click();
  await expect(ops.getByTestId("add-vehicle")).toContainText("(3)");

  // the same session is visible on both screens, and both agree on the queue position
  const mine = ops.getByTestId("gantt-block-1001");
  await expect(mine).toBeVisible();
  await expect(ops.getByTestId("gantt-block-1004")).toBeVisible();
  const api = await phone.request.get("/api/sessions/1001");
  const ahead = ((await api.json()) as { ahead: number }).ahead;
  await expect(phone.getByText(`내 앞 ${ahead}대`)).toBeVisible();
  await phone.screenshot({ path: `${SHOTS}/m-queue-360.png` });

  // --- step 4: operator switches to 10x; blocks move and the phone follows ---------------------------
  const clock0 = await ops.getByTestId("sim-clock").textContent();
  await ops.getByRole("button", { name: "10x" }).click();
  await ops.getByTestId("sim-toggle").click();
  await expect(ops.getByTestId("sim-toggle")).toHaveText(/일시정지/);
  await expect(ops.getByTestId("sim-clock")).not.toHaveText(clock0 ?? "");
  await expect(mine).toHaveAttribute("data-kind", "charging", { timeout: 90_000 });
  await expect(phone).toHaveURL(/\/m\/charging/, { timeout: 15_000 });
  await phone.screenshot({ path: `${SHOTS}/m-charging-360.png` });

  // --- step 5: more cars, load reaches 90 % -> output limit / delayed start ---------------------------
  await ops.getByRole("button", { name: "60x" }).click();
  await expect(ops.getByTestId("load-alert")).toBeVisible({ timeout: 120_000 });
  expect(await ops.getByTestId("load-gauge").getAttribute("data-load-pct")).toBeDefined();
  await expect(
    ops.locator('[data-event-type="limited"], [data-event-type="delayed"]').first(),
  ).toBeVisible();
  await ops.screenshot({ path: `${SHOTS}/ops-load-alert-1920x1080.png` });

  // the driver's finished car stays plugged in: abandoned after 5 minutes -> operator reminds
  await expect(phone).toHaveURL(/\/m\/done/, { timeout: 120_000 });
  await expect(phone.getByText("충전이 끝났습니다. 차량을 이동해 주세요.")).toBeVisible();
  const abandoned = ops.getByTestId("abandoned-1001");
  await expect(abandoned).toBeVisible({ timeout: 120_000 });
  await abandoned.getByRole("button", { name: "운전자 알림" }).click();
  await expect(abandoned.getByRole("button", { name: "알림 전송됨" })).toBeVisible();
  await expect(phone.getByText(/관제에서 차량 이동을 요청했습니다/).first()).toBeVisible();
  await phone.screenshot({ path: `${SHOTS}/m-nudge-360.png` });
  await expect(ops.locator('[data-event-type="nudged"]').first()).toBeVisible();
  await expect(ops.locator('[data-event-type="left"]').first()).toBeVisible({ timeout: 60_000 });

  // --- step 6: no-control vs VoltQueue graph and KPI cards ---------------------------------------------
  await expect(ops.getByTestId("load-chart").locator(".recharts-line")).toHaveCount(2);
  expect(await numberIn(ops, "kpi-turnover-value")).toBeGreaterThanOrEqual(1);
  expect(await numberIn(ops, "kpi-peak-value")).toBeGreaterThan(0); // peak reduction in kW
  await ops.getByTestId("sim-toggle").click(); // freeze the picture for the screenshot
  await expect(ops.getByTestId("sim-toggle")).toHaveText(/시작/);
  await ops.screenshot({ path: `${SHOTS}/ops-1920x1080.png` });
  expect(await verticalOverflow(ops)).toBeLessThanOrEqual(4); // the whole dashboard fits 1920x1080

  // --- layout: 1440x900 has no horizontal overflow --------------------------------------------------------
  const small = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "ko-KR" });
  const page1440 = await small.newPage();
  await page1440.goto("/ops");
  await expect(page1440.getByTestId("gantt")).toBeVisible();
  await expect(page1440.getByTestId("load-chart")).toBeVisible();
  const overflowX = await page1440.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflowX).toBeLessThanOrEqual(0);
  expect(await verticalOverflow(page1440)).toBeLessThanOrEqual(4); // ... and 1440x900 without scrolling
  await page1440.screenshot({ path: `${SHOTS}/ops-1440x900.png` });

  expect(consoleErrors).toEqual([]);
  await small.close();
  await opsCtx.close();
  await phoneCtx.close();
});
