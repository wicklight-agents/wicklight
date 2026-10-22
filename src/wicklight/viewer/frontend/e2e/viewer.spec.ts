import { expect, test } from "@playwright/test";

// Smoke test over the committed injection fixture: the run renders, the injection
// step expands to show the untrusted email and the policy block, the blocks
// filter narrows the timeline, and the page renders in dark mode.
test("views a run, expands the injection step, filters, and goes dark", async ({
  page,
}) => {
  await page.goto("/");

  // Run header renders.
  await expect(page.getByText("inbox-summarizer", { exact: true })).toBeVisible();

  // Expand the blocked step (#2) and see the untrusted poisoned email.
  await page.getByRole("button", { name: /blocked: send_email/ }).click();
  await expect(page.getByText("untrusted · tool result from read_inbox")).toBeVisible();
  await expect(page.getByText(/attacker@evil\.com/).first()).toBeVisible();
  await expect(page.getByText(/inbox\.md line 22/).first()).toBeVisible();

  // Filter to blocks only.
  await page.getByRole("button", { name: "blocks" }).click();
  await expect(
    page.getByRole("button", { name: /blocked: send_email/ }),
  ).toBeVisible();

  // Renders in dark mode.
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.getByText("inbox-summarizer", { exact: true })).toBeVisible();
});
