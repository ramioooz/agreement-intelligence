import { expect, test, type Page } from "@playwright/test";

const adminPassword = process.env.DEMO_ADMIN_PASSWORD;
const reviewerPassword = process.env.DEMO_REVIEWER_PASSWORD;

if (!adminPassword || !reviewerPassword) {
  throw new Error(
    "DEMO_ADMIN_PASSWORD and DEMO_REVIEWER_PASSWORD must be set to run the review workspace E2E test.",
  );
}

function pdfWithText(text: string): Buffer {
  const escapedText = text
    .replaceAll("\\", "\\\\")
    .replaceAll("(", "\\(")
    .replaceAll(")", "\\)");
  const stream = `BT /F1 12 Tf 72 720 Td (${escapedText}) Tj ET`;
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

test("a legal reviewer filters high-severity findings and opens cited evidence by keyboard", async ({
  page,
}) => {
  test.setTimeout(90_000);
  const unique = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const agreementFamily = `review_e2e_${unique}`;
  const agreementTitle = `Supplier agreement ${unique}`;

  await page.goto("/dashboard/playbooks");
  await signIn(
    page,
    process.env.DEMO_ADMIN_USERNAME ?? "platform.admin",
    adminPassword!,
  );
  await page.getByRole("link", { name: "Playbooks" }).click();
  await expect(
    page.getByRole("heading", { name: "Create playbook draft" }),
  ).toBeVisible();
  await page.getByLabel("Playbook name").fill(`Review E2E ${unique}`);
  await page.getByLabel("Agreement family").fill(agreementFamily);
  await page.getByRole("button", { name: "Create draft" }).click();

  const ruleForm = page
    .getByRole("heading", { name: "Add rule" })
    .locator("..");
  await ruleForm.getByLabel("Clause type").fill("liability");
  await ruleForm.getByLabel("Rule title").fill("Prohibit unlimited liability");
  await ruleForm.getByLabel("Policy type").selectOption("prohibited");
  await ruleForm.getByLabel("Severity").selectOption("high");
  await ruleForm.getByLabel(/Preferred language/).fill("unlimited liability");
  await ruleForm
    .getByLabel("Approved fallback language (optional)")
    .fill("Liability is capped at fees paid in the prior twelve months.");
  await ruleForm
    .getByLabel("Legal rationale")
    .fill("Unlimited exposure conflicts with the approved liability cap.");
  await ruleForm
    .getByLabel("Reviewer guidance")
    .fill("Escalate uncapped liability for legal approval.");
  await ruleForm.getByRole("button", { name: "Add rule" }).click();
  await expect(
    page.locator('input[value="Prohibit unlimited liability"]'),
  ).toBeVisible();

  await page.reload();
  const secondRuleForm = page
    .getByRole("heading", { name: "Add rule" })
    .locator("..");
  await secondRuleForm.getByLabel("Clause type").fill("confidentiality");
  await secondRuleForm
    .getByLabel("Rule title")
    .fill("Confidentiality survival");
  await secondRuleForm.getByLabel("Policy type").selectOption("required");
  await secondRuleForm.getByLabel("Severity").selectOption("high");
  await secondRuleForm
    .getByLabel(/Preferred language/)
    .fill("confidentiality survives termination");
  await secondRuleForm
    .getByLabel("Legal rationale")
    .fill("Confidentiality should survive termination.");
  await secondRuleForm
    .getByLabel("Reviewer guidance")
    .fill("Confirm the survival period.");
  await secondRuleForm.getByRole("button", { name: "Add rule" }).click();
  await expect(
    page.locator('input[value="Confidentiality survival"]'),
  ).toBeVisible();
  await page.getByRole("button", { name: "Publish version" }).click();
  await expect(page.getByText(/^Published · Version \d+$/)).toBeVisible();

  await page.goto("/dashboard/agreements");
  const uploadForm = page
    .getByRole("heading", { name: "Upload agreement" })
    .locator("..");
  await uploadForm.getByLabel("Agreement title").fill(agreementTitle);
  await uploadForm.getByLabel("Agreement type").fill(agreementFamily);
  await uploadForm.getByLabel("Original agreement file").setInputFiles({
    name: `review-${unique}.pdf`,
    mimeType: "application/pdf",
    buffer: pdfWithText(
      `The supplier accepts unlimited liability under this agreement. Reference ${unique}.`,
    ),
  });
  await uploadForm.getByRole("button", { name: "Upload agreement" }).click();
  await expect(page.getByRole("status")).toHaveText("Agreement uploaded.");

  const agreementLink = page.getByRole("link", { name: agreementTitle });
  await expect(agreementLink).toBeVisible();
  await agreementLink.click();
  const reviewLink = page.getByRole("link", {
    name: "Review playbook findings",
  });
  await expect(reviewLink).toBeVisible({ timeout: 30_000 });
  const reviewUrl = await reviewLink.getAttribute("href");
  expect(reviewUrl).toMatch(/^\/dashboard\/agreements\/.+\/review$/);
  await expect
    .poll(
      async () => {
        await page.goto(`${reviewUrl}?e2e_ready=${Date.now()}`);
        const severity = page.getByRole("combobox", { name: "Severity" });
        await severity
          .or(
            page.getByText(
              "No playbook findings are available for this agreement.",
            ),
          )
          .waitFor({ state: "visible", timeout: 10_000 });
        return severity.count();
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
  await page.goto(`${reviewUrl}?e2e_ready=${Date.now()}`);

  await expect(
    page.getByRole("heading", { name: agreementTitle }),
  ).toBeVisible();
  const severityFilter = page.getByRole("combobox", { name: "Severity" });
  await severityFilter.focus();
  await page.keyboard.press("h");
  await expect(severityFilter).toHaveValue("high");
  await expect(page.getByText("2 of 2 shown")).toBeVisible();

  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("combobox", { name: "Finding status" }),
  ).toBeFocused();
  await page.keyboard.press("Tab");
  const confidentialityFinding = page.getByRole("button", {
    name: /Confidentiality — Confidentiality survival.*High severity/,
  });
  await expect(confidentialityFinding).toBeFocused();
  await expect(confidentialityFinding).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("heading", { name: "Confidentiality survival" }),
  ).toBeVisible();
  await expect(
    page.getByText("No source location is available for this finding."),
  ).toBeVisible();

  await page.keyboard.press("Tab");
  const liabilityFinding = page.getByRole("button", {
    name: /Liability — Prohibit unlimited liability.*High severity/,
  });
  await expect(liabilityFinding).toBeFocused();
  await expect(liabilityFinding).toHaveAttribute("aria-pressed", "false");
  await page.keyboard.press("Enter");
  await expect(liabilityFinding).toHaveAttribute("aria-pressed", "true");
  await expect(confidentialityFinding).toHaveAttribute("aria-pressed", "false");
  await expect(
    page.getByRole("heading", { name: "Prohibit unlimited liability" }),
  ).toBeVisible();

  const evidence = page.getByRole("region", { name: "Source evidence" });
  await expect(evidence).toContainText("accepts unlimited liability");
  await expect(evidence).toContainText("Page 1 · Paragraph");
  const citation = evidence.getByRole("link", {
    name: /Citation .+ on page 1/,
  });
  await expect(citation).toHaveAttribute("href", /^#source-/);
  const citationTarget = page.getByRole("link", {
    name: /View citation .+/,
  });
  const citationHash = await citationTarget.getAttribute("href");
  await citationTarget.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`${citationHash}$`));
  await expect(
    page.getByRole("heading", { name: "Policy rationale" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Optional model explanation" }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Generated suggestion" }),
  ).toBeVisible();
  await expect(page.getByText(/^(AI-generated|Policy-derived)$/)).toBeVisible();
  await page.screenshot({
    fullPage: true,
    path: "test-results/review-workspace.png",
  });
});
