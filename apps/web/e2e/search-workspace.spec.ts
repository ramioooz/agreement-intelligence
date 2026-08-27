import { expect, test, type Page } from "@playwright/test";

const adminPassword = process.env.DEMO_ADMIN_PASSWORD;

async function signIn(page: Page) {
  await page.getByRole("button", { name: "Continue with Keycloak" }).click();
  await page
    .getByLabel("Username or email")
    .fill(process.env.DEMO_ADMIN_USERNAME ?? "platform.admin");
  await page.getByRole("textbox", { name: "Password" }).fill(adminPassword!);
  await page.getByRole("button", { name: "Sign In" }).click();
}

test("an administrator runs a scoped search and sees grounded Q&A boundaries", async ({
  page,
}) => {
  test.skip(
    !adminPassword,
    "DEMO_ADMIN_PASSWORD is required for this E2E test.",
  );
  await page.goto("/dashboard/search");
  await signIn(page);
  await page.getByRole("link", { name: "Search" }).click();

  await expect(
    page.getByRole("heading", { name: "Grounded search" }),
  ).toBeVisible();
  await page
    .getByRole("searchbox", { name: "Search" })
    .fill("no-evidence-e2e-query");
  await page.getByLabel("Agreement type").fill("client_agreement");
  await page.getByLabel("Party").fill("Example Counterparty");
  await page.getByLabel("Status").selectOption("active");
  await page.getByLabel("Updated after").fill("2026-01-01");
  await page.getByLabel("Updated before").fill("2026-01-31");
  await page.getByLabel("Source version").fill("v3");
  await page
    .getByLabel("Agreement IDs")
    .fill("55555555-5555-5555-5555-555555555555");
  await page.getByRole("button", { name: "Search" }).click();

  await expect(page).toHaveURL(
    /q=no-evidence-e2e-query.*agreement_type=client_agreement.*party=Example\+Counterparty.*status=active.*updated_after=2026-01-01.*updated_before=2026-01-31.*source_version=v3.*agreement_id=55555555-5555-5555-5555-555555555555/,
  );
  await expect(
    page.getByText("No reviewer-approved information matched this search."),
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Cited Q&A" })).toBeVisible();
  const askQuestion = page.getByRole("button", { name: "Ask question" });
  await expect(askQuestion).toBeDisabled();
  await page
    .getByRole("textbox", { name: "Question" })
    .fill("What does this agreement say about termination?");
  await expect(askQuestion).toBeEnabled();
});
