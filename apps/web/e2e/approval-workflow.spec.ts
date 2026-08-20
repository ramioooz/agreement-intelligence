import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

const adminPassword = process.env.DEMO_ADMIN_PASSWORD;
const reviewerPassword = process.env.DEMO_REVIEWER_PASSWORD;
const businessPassword = process.env.DEMO_BUSINESS_APPROVER_PASSWORD;

if (!adminPassword || !reviewerPassword || !businessPassword) {
  throw new Error(
    "The admin, legal-reviewer, and business-approver demo passwords are required for the approval E2E test.",
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

function sha256(content: Buffer): string {
  return createHash("sha256").update(content).digest("hex");
}

async function signIn(page: Page, username: string, password: string) {
  await page.getByRole("button", { name: "Continue with Keycloak" }).click();
  await page.getByLabel("Username or email").fill(username);
  await page.getByRole("textbox", { name: "Password" }).fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();
}

async function changeIdentity(
  page: Page,
  targetUrl: string,
  username: string,
  password: string,
) {
  await page.context().clearCookies();
  await page.goto(targetUrl);
  await signIn(page, username, password);
  await page.goto(targetUrl);
}

test("legal and business approvers complete a routed review with immutable packages", async ({
  page,
}, testInfo) => {
  test.setTimeout(240_000);
  const unique = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const family = "client_agreement";
  const jurisdiction = `A${Date.now().toString(36).slice(-6)}${Math.random()
    .toString(36)
    .slice(2, 6)}`.toUpperCase();
  const policyName = "Sprint 6 E2E two-stage approval";
  const agreementTitle = `Approval agreement ${unique}`;

  await page.goto("/dashboard/approval-policies");
  await signIn(
    page,
    process.env.DEMO_ADMIN_USERNAME ?? "platform.admin",
    adminPassword!,
  );
  await page.goto("/dashboard/approval-policies");

  let policyCard = page
    .getByRole("heading", { name: policyName, exact: true })
    .locator("..");
  if ((await policyCard.count()) === 0) {
    await page.getByLabel("Policy name").fill(policyName);
    await page.getByLabel("Agreement family").selectOption(family);
    await page.getByLabel("Jurisdiction").fill("any");
    await page.getByLabel("Legal review role").fill("legal_reviewer");
    await page.getByRole("button", { name: "Add business stage" }).click();
    await page.getByLabel("Business approval role").fill("business_approver");
    await page.getByRole("button", { name: "Create policy" }).click();
    await expect(page.getByRole("status")).toHaveText(
      "Policy submitted for publication.",
    );
    await page.reload();
    policyCard = page
      .getByRole("heading", { name: policyName, exact: true })
      .locator("..");
  }
  await expect(policyCard).toBeVisible();
  const publish = policyCard.getByRole("button", {
    name: /Publish version/,
  });
  if ((await publish.count()) > 0) {
    await publish.click();
    await page.reload();
    policyCard = page
      .getByRole("heading", { name: policyName, exact: true })
      .locator("..");
  }
  await expect(policyCard).toContainText(/published/i);

  await page.goto("/dashboard/playbooks");
  await page.getByLabel("Playbook name").fill(`Approval E2E ${unique}`);
  await page.getByLabel("Agreement family").selectOption(family);
  await page.getByText("Advanced settings", { exact: true }).click();
  await page.getByLabel("Jurisdiction").fill(jurisdiction);
  await page.getByLabel("Override priority").fill("1000");
  await page.getByRole("button", { name: "Create draft" }).click();
  const ruleForm = page
    .getByRole("heading", { name: "Add rule" })
    .locator("..");
  await ruleForm
    .getByLabel("Clause type")
    .selectOption("limitation_of_liability");
  await ruleForm.getByLabel("Rule title").fill("Approval liability control");
  await ruleForm.getByLabel("Rule type").selectOption("prohibited");
  await ruleForm.getByLabel("Severity").selectOption("high");
  await ruleForm.getByLabel(/Preferred language/).fill("unlimited liability");
  await ruleForm
    .getByLabel("Legal rationale")
    .fill("Unlimited exposure requires explicit approval.");
  await ruleForm
    .getByLabel("Reviewer guidance")
    .fill("Confirm the cited exposure before approving.");
  await ruleForm.getByRole("button", { name: "Add rule" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Edit rule: Approval liability control",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Publish version" }).click();
  await expect(page.getByText(/^Published · Version \d+$/)).toBeVisible();

  await page.goto("/dashboard/agreements");
  const upload = page
    .getByRole("heading", { name: "Upload agreement" })
    .locator("..");
  await upload.getByLabel("Agreement title").fill(agreementTitle);
  await upload.getByLabel("Agreement type").fill(family);
  await upload.getByLabel("Jurisdiction").fill(jurisdiction);
  await upload.getByLabel("Original agreement file").setInputFiles({
    name: `approval-${unique}.pdf`,
    mimeType: "application/pdf",
    buffer: pdfWithText(
      `The supplier accepts unlimited liability under this client agreement. Reference ${unique}.`,
    ),
  });
  await upload.getByRole("button", { name: "Upload agreement" }).click();
  await expect(page.getByRole("status")).toHaveText("Agreement uploaded.");
  await page.getByRole("link", { name: agreementTitle }).click();
  await expect(
    page.getByRole("link", { name: "Review playbook findings" }),
  ).toBeVisible({ timeout: 30_000 });
  const startReview = page.getByRole("button", {
    name: "Start approval review",
  });
  await expect(startReview).toBeVisible({ timeout: 30_000 });
  await startReview.click();

  await expect(page).toHaveURL(/\/dashboard\/reviews\/[0-9a-f-]+$/);
  const reviewUrl = page.url();
  const reviewId = reviewUrl.split("/").at(-1)!;
  await expect(
    page.getByText(/not eligible to record an approval decision/i),
  ).toBeVisible();

  await changeIdentity(
    page,
    reviewUrl,
    process.env.DEMO_REVIEWER_USERNAME ?? "legal.reviewer",
    reviewerPassword!,
  );
  await expect(page.getByText(/Stage 1 is awaiting/i)).toBeVisible();
  await page
    .getByLabel("Review comment")
    .fill("Legal review confirmed the cited liability finding.");
  await page.getByRole("button", { name: "Add comment" }).click();
  await expect(
    page.getByText("Legal review confirmed the cited liability finding."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/Stage 2 is awaiting/i)).toBeVisible();

  await changeIdentity(
    page,
    reviewUrl,
    process.env.DEMO_BUSINESS_APPROVER_USERNAME ?? "business.approver",
    businessPassword!,
  );
  await expect(page.getByText(/Stage 2 is awaiting/i)).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(
    page.getByRole("link", { name: "Download final PDF" }),
  ).toBeVisible();
  await page.reload();

  const manifestChecksumText = await page
    .getByText(/^Manifest sha256:/)
    .textContent();
  const pdfChecksumText = await page.getByText(/^PDF sha256:/).textContent();
  const manifestChecksum = manifestChecksumText!.replace(
    "Manifest sha256:",
    "",
  );
  const pdfChecksum = pdfChecksumText!.replace("PDF sha256:", "");

  const pdfDownloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download final PDF" }).click();
  const pdfDownload = await pdfDownloadPromise;
  const pdfPath = await pdfDownload.path();
  expect(pdfPath).not.toBeNull();
  const pdf = await readFile(pdfPath!);
  expect(sha256(pdf)).toBe(pdfChecksum);

  const manifestDownloadPromise = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download JSON manifest" }).click();
  const manifestDownload = await manifestDownloadPromise;
  const manifestPath = await manifestDownload.path();
  expect(manifestPath).not.toBeNull();
  const manifestContent = await readFile(manifestPath!);
  expect(sha256(manifestContent)).toBe(manifestChecksum);
  const manifest = JSON.parse(manifestContent.toString()) as {
    review_id: string;
    state: string;
    decisions: Array<{ action: string }>;
    findings: Array<{ citation_ids: string[] }>;
  };
  expect(manifest.review_id).toBe(reviewId);
  expect(manifest.state).toBe("approved");
  expect(manifest.decisions.map((decision) => decision.action)).toEqual([
    "approve",
    "approve",
  ]);
  expect(
    manifest.findings.some((finding) => finding.citation_ids.length > 0),
  ).toBe(true);

  await testInfo.attach("approval-package-evidence", {
    body: Buffer.from(
      JSON.stringify({ reviewId, manifestChecksum, pdfChecksum }, null, 2),
    ),
    contentType: "application/json",
  });
  await page.screenshot({
    fullPage: true,
    path: testInfo.outputPath("approval-workflow.png"),
  });
});
