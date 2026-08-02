import { expect, test, type Page } from "@playwright/test";

const adminPassword = process.env.DEMO_ADMIN_PASSWORD;
const reviewerPassword = process.env.DEMO_REVIEWER_PASSWORD;

if (!adminPassword || !reviewerPassword) {
  throw new Error(
    "DEMO_ADMIN_PASSWORD and DEMO_REVIEWER_PASSWORD must be set to run the review decision E2E test.",
  );
}

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

async function signIn(page: Page, username: string, password: string) {
  await page.getByRole("button", { name: "Continue with Keycloak" }).click();
  await page.getByLabel("Username or email").fill(username);
  await page.getByRole("textbox", { name: "Password" }).fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();
}

test("a legal reviewer records a cited decision and downloads the review report", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const unique = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const family = `decision_e2e_${unique}`;
  const title = `Decision export agreement ${unique}`;

  await page.goto("/dashboard/playbooks");
  await signIn(
    page,
    process.env.DEMO_ADMIN_USERNAME ?? "platform.admin",
    adminPassword!,
  );
  await page.getByRole("link", { name: "Playbooks" }).click();
  await page.getByLabel("Playbook name").fill(`Decision export ${unique}`);
  await page.getByLabel("Agreement family").fill(family);
  await page.getByRole("button", { name: "Create draft" }).click();
  const ruleForm = page
    .getByRole("heading", { name: "Add rule" })
    .locator("..");
  await ruleForm.getByLabel("Clause type").fill("liability");
  await ruleForm.getByLabel("Rule title").fill("Liability cap decision");
  await ruleForm.getByLabel("Policy type").selectOption("prohibited");
  await ruleForm.getByLabel("Severity").selectOption("high");
  await ruleForm.getByLabel(/Preferred language/).fill("unlimited liability");
  await ruleForm
    .getByLabel("Legal rationale")
    .fill("Unlimited exposure conflicts with the approved cap.");
  await ruleForm
    .getByLabel("Reviewer guidance")
    .fill("Confirm the cited exposure before deciding.");
  await ruleForm.getByRole("button", { name: "Add rule" }).click();
  await expect(
    page.locator('input[value="Liability cap decision"]'),
  ).toBeVisible();
  await page.getByRole("button", { name: "Publish version" }).click();
  await expect(page.getByText(/^Published · Version \d+$/)).toBeVisible();

  await page.goto("/dashboard/agreements");
  const upload = page
    .getByRole("heading", { name: "Upload agreement" })
    .locator("..");
  await upload.getByLabel("Agreement title").fill(title);
  await upload.getByLabel("Agreement type").fill(family);
  await upload.getByLabel("Original agreement file").setInputFiles({
    name: `decision-${unique}.pdf`,
    mimeType: "application/pdf",
    buffer: pdfWithText(
      `The supplier accepts unlimited liability. Reference ${unique}.`,
    ),
  });
  await upload.getByRole("button", { name: "Upload agreement" }).click();
  await expect(page.getByRole("status")).toHaveText("Agreement uploaded.");
  await page.getByRole("link", { name: title }).click();
  const reviewLink = page.getByRole("link", {
    name: "Review playbook findings",
  });
  await expect(reviewLink).toBeVisible({ timeout: 30_000 });
  const reviewUrl = await reviewLink.getAttribute("href");
  expect(reviewUrl).toMatch(/^\/dashboard\/agreements\/.+\/review$/);
  await expect
    .poll(
      async () => {
        await page.goto(`${reviewUrl}?ready=${Date.now()}`);
        const decisionHeading = page.getByRole("heading", {
          name: "Reviewer decision",
        });
        await decisionHeading
          .or(
            page.getByText(
              "No playbook findings are available for this agreement.",
            ),
          )
          .waitFor({ state: "visible", timeout: 10_000 });
        return decisionHeading.count();
      },
      { intervals: [250, 500, 1000], timeout: 30_000 },
    )
    .toBe(1);

  await page.context().clearCookies();
  await page.goto(reviewUrl!);
  await signIn(
    page,
    process.env.DEMO_REVIEWER_USERNAME ?? "legal.reviewer",
    reviewerPassword!,
  );
  await page.goto(`${reviewUrl}?reviewer=${Date.now()}`);
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  await page.getByRole("radio", { name: "Accept finding" }).check();
  await page
    .getByLabel("Reviewer rationale")
    .fill("The cited clause supports the recorded reviewer decision.");
  await page.getByRole("button", { name: "Record decision" }).click();
  await expect(
    page.getByRole("status", { name: "Current reviewer decision" }),
  ).toContainText("Accepted");
  await expect(
    page.getByText("1 immutable decision event recorded."),
  ).toBeVisible();

  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export cited review report" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/review-report\.pdf$/);
  expect(await download.failure()).toBeNull();
});
