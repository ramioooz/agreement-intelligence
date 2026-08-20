import { expect, test, type Page } from "@playwright/test";

/**
 * The approval journey uses an already processed, policy-routed agreement so
 * it can be run repeatedly without mutating the developer's local database.
 * Set APPROVAL_E2E_AGREEMENT_ID to a completed agreement before opting in.
 */
const adminPassword = process.env.DEMO_ADMIN_PASSWORD;
const reviewerPassword = process.env.DEMO_REVIEWER_PASSWORD;
const businessPassword = process.env.DEMO_BUSINESS_APPROVER_PASSWORD;
const agreementId = process.env.APPROVAL_E2E_AGREEMENT_ID;

async function signIn(page: Page, username: string, password: string) {
  await page.getByRole("button", { name: "Continue with Keycloak" }).click();
  await page.getByLabel("Username or email").fill(username);
  await page.getByRole("textbox", { name: "Password" }).fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();
}

test("approval workspace exposes the connected review journey", async ({
  page,
}) => {
  test.skip(
    !agreementId || !adminPassword || !reviewerPassword || !businessPassword,
    "Set APPROVAL_E2E_AGREEMENT_ID and all demo identity passwords to run the local approval journey.",
  );
  test.setTimeout(180_000);

  await page.goto(`/dashboard/agreements/${agreementId}`);
  await signIn(
    page,
    process.env.DEMO_ADMIN_USERNAME ?? "platform.admin",
    adminPassword!,
  );
  await page.goto(`/dashboard/agreements/${agreementId}`);
  const startReview = page.getByRole("button", {
    name: "Start approval review",
  });
  await expect(startReview).toBeVisible();
  await startReview.click();

  await expect(page).toHaveURL(/\/dashboard\/reviews\/[0-9a-f-]+$/);
  await expect(
    page.getByRole("heading", { name: "Approval review" }),
  ).toBeVisible();
  await expect(page.getByText("Approval action")).toBeVisible();
  await expect(page.getByText("Timeline")).toBeVisible();

  // The API returns actionable authorization instead of exposing decision
  // controls to a user without an active eligible assignment.
  await expect(
    page.getByText(
      /eligible to record an approval decision|awaiting an authorized decision/i,
    ),
  ).toBeVisible();
});
