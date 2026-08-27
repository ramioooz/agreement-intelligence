import { mkdir } from "node:fs/promises";
import { resolve } from "node:path";

import { expect, test, type Page } from "@playwright/test";

// The release project has one worker and loads the established end-to-end journeys into one
// suite. Together they cover playbook administration, findings/reviewer decisions, scoped
// search and Q&A boundaries, staged approval, and immutable package downloads.
import "./approval-workflow.spec";
import "./review-decision-export.spec";
import "./review-workspace.spec";
import "./search-workspace.spec";

const adminPassword = process.env.DEMO_ADMIN_PASSWORD;
const screenshotDirectory = process.env.PUBLIC_RELEASE_SCREENSHOT_DIR;

function pdfWithText(text: string): Buffer {
  const escaped = text
    .replaceAll("\\", "\\\\")
    .replaceAll("(", "\\(")
    .replaceAll(")", "\\)");
  const stream = `BT /F1 12 Tf 72 720 Td (${escaped}) Tj ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`)
    .join("");
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf);
}

async function signIn(page: Page) {
  await page.getByRole("button", { name: "Continue with Keycloak" }).click();
  await page
    .getByLabel("Username or email")
    .fill(process.env.DEMO_ADMIN_USERNAME ?? "platform.admin");
  await page.getByRole("textbox", { name: "Password" }).fill(adminPassword!);
  await page.getByRole("button", { name: "Sign In" }).click();
}

async function capture(page: Page, name: string) {
  if (!screenshotDirectory) return;
  const directory = resolve(screenshotDirectory);
  await mkdir(directory, { recursive: true });
  await page.screenshot({
    animations: "disabled",
    fullPage: true,
    path: resolve(directory, name),
  });
}

async function waitForServerRenderedHeading(page: Page, name: string) {
  await expect
    .poll(
      async () => {
        await page.reload({ waitUntil: "domcontentloaded" });
        await page
          .getByRole("heading", { name: "Compare agreement versions" })
          .waitFor({ state: "visible" });
        return page.getByRole("heading", { name }).isVisible();
      },
      { intervals: [500, 1_000, 2_000], timeout: 45_000 },
    )
    .toBe(true);
}

test("public release repository, analysis, search, and version comparison journey", async ({
  page,
}) => {
  test.skip(
    !adminPassword,
    "DEMO_ADMIN_PASSWORD is required for the public release E2E test.",
  );
  test.setTimeout(240_000);

  const unique = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const title = `Public release synthetic agreement ${unique}`;

  await page.goto("/dashboard");
  await signIn(page);
  await expect(
    page.getByRole("heading", { name: "Agreement workspace" }),
  ).toBeVisible();
  await capture(page, "dashboard.png");

  await page.goto("/dashboard/agreements");
  const upload = page
    .getByRole("heading", { name: "Upload agreement" })
    .locator("..");
  await upload.getByLabel("Agreement title").fill(title);
  await upload.getByLabel("Agreement type").fill("client_agreement");
  await upload.getByLabel("Jurisdiction").fill("UAE");
  await upload.getByLabel("Original agreement file").setInputFiles({
    name: "northstar-client-agreement-v1.pdf",
    mimeType: "application/pdf",
    buffer: pdfWithText(
      "Northstar Demo Markets Ltd and Cedar Demo Trading LLC. Termination requires 30 days notice. Liability is capped at fees paid in the preceding 12 months. NORTHSTAR-SYNTHETIC-ALPHA.",
    ),
  });
  await upload.getByRole("button", { name: "Upload agreement" }).click();
  await expect(page.getByRole("status")).toHaveText("Agreement uploaded.");
  await page.getByRole("link", { name: title }).click();
  await expect(page).toHaveURL(/\/dashboard\/agreements\/[0-9a-f-]+$/);

  await expect(
    page.getByRole("heading", { name: "Document understanding" }),
  ).toBeVisible({ timeout: 45_000 });
  await expect(page.getByText("Deterministic analysis.")).toBeVisible();
  await capture(page, "agreement-analysis.png");

  await page.getByLabel("Revision file").setInputFiles({
    name: "northstar-client-agreement-v2.pdf",
    mimeType: "application/pdf",
    buffer: pdfWithText(
      "Northstar Demo Markets Ltd and Cedar Demo Trading LLC. Termination requires 60 days notice. Liability is capped at fees paid in the preceding 6 months. NORTHSTAR-SYNTHETIC-BETA.",
    ),
  });
  await page.getByRole("button", { name: "Upload new version" }).click();
  await page.getByRole("button", { name: "Start analysis" }).click();
  await expect(
    page.getByRole("link", { name: "Compare versions" }),
  ).toBeVisible({ timeout: 45_000 });
  await page.getByRole("link", { name: "Compare versions" }).click();
  await expect(
    page.getByRole("heading", { name: "Compare agreement versions" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Compare versions" }).click();
  await expect(page).toHaveURL(/comparison_id=/);
  await waitForServerRenderedHeading(page, "Material changes");
  await expect(
    page.getByRole("heading", { name: "Material changes" }),
  ).toBeVisible({ timeout: 10_000 });
  await capture(page, "version-comparison.png");

  await page.goto("/dashboard/search");
  await page
    .getByRole("searchbox", { name: "Search" })
    .fill("termination notice");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByRole("heading", { name: "Cited Q&A" })).toBeVisible();
  await capture(page, "grounded-search.png");
});
