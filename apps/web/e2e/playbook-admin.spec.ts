import { expect, test } from "@playwright/test";

const adminPassword = process.env.DEMO_ADMIN_PASSWORD;

test("a platform administrator publishes an immutable client-agreement playbook", async ({
  page,
}) => {
  test.skip(
    !adminPassword,
    "DEMO_ADMIN_PASSWORD is required for this E2E test.",
  );
  const priority = String(Date.now() % 1_000);
  const name = `Client agreement ${Date.now()}`;

  await page.goto("/dashboard/playbooks");
  await page.getByRole("button", { name: "Continue with Keycloak" }).click();
  await page
    .getByLabel("Username or email")
    .fill(process.env.DEMO_ADMIN_USERNAME ?? "platform.admin");
  await page.getByRole("textbox", { name: "Password" }).fill(adminPassword!);
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.getByRole("link", { name: "Playbooks" }).click();

  await expect(
    page.getByRole("heading", { name: "Create playbook draft" }),
  ).toBeVisible();
  await page.getByLabel("Playbook name").fill(name);
  await page.getByLabel("Agreement family").selectOption("client_agreement");
  await page.getByText("Advanced settings").click();
  await expect(page.getByRole("textbox", { name: "Jurisdiction" })).toHaveValue(
    "UAE",
  );
  await page
    .getByRole("spinbutton", { name: "Override priority" })
    .fill(priority);
  await page.getByRole("button", { name: "Create draft" }).click();

  await expect(page.getByRole("heading", { name: "Add rule" })).toBeVisible();
  await page.getByLabel("Clause type").selectOption("limitation_of_liability");
  await page.getByLabel("Rule title").fill("Limitation of liability");
  await page
    .getByLabel(/Preferred language/)
    .fill("Liability is limited to fees paid in the preceding twelve months.");
  await page
    .getByLabel("Legal rationale")
    .fill("Caps exposure to the amount approved by policy.");
  await page
    .getByLabel("Reviewer guidance")
    .fill("Escalate uncapped liability to legal review.");
  await page.getByRole("button", { name: "Add rule" }).click();

  await page.waitForTimeout(500);
  const ruleTitle = page.getByLabel("Rule title");
  await expect(ruleTitle).toHaveValue("Limitation of liability");
  await ruleTitle.fill("Updated limitation of liability");
  await page.getByRole("button", { name: "Save rule" }).click();
  await expect(
    page.getByText("An error occurred in the Server Components render"),
  ).not.toBeVisible();
  await page.waitForTimeout(500);
  await page.reload();
  await expect(page.getByLabel("Rule title")).toHaveValue(
    "Updated limitation of liability",
  );

  const publish = page.getByRole("button", { name: "Publish version" });
  await expect(publish).toBeEnabled();
  await publish.click();
  await expect(page.getByText(/^Published · Version \d+$/)).toBeVisible();
  await expect(
    page.getByText("Published playbooks are immutable policy records."),
  ).toBeVisible();
  await page.getByRole("button", { name: "Create next draft" }).click();
  await expect(page.getByText(/^Draft · Version 2$/)).toBeVisible();
  await page.getByRole("link", { name: "Back to playbooks" }).click();
  await expect(page).toHaveURL(/\/dashboard\/playbooks$/);

  const card = page.getByRole("article", { name: name });
  await expect(
    card.getByRole("button", { name: "Delete draft version 2" }),
  ).toBeVisible();
  await card.getByRole("button", { name: "Delete draft version 2" }).click();
  await expect(
    page.getByRole("heading", { name: "Delete draft version 2?" }),
  ).toBeVisible();
  await page
    .getByRole("dialog", { name: "Delete draft version 2?" })
    .getByRole("button", { name: "Delete draft version" })
    .click();
  const archive = card.getByRole("button", { name: "Archive playbook" });
  await expect(archive).toBeVisible();
  await archive.click();
  await expect(
    page.getByRole("heading", { name: "Archive playbook?" }),
  ).toBeVisible();
  await page
    .getByRole("dialog", { name: "Archive playbook?" })
    .getByRole("button", { name: "Archive playbook" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Legal playbooks" }),
  ).toBeVisible();
});

test("a platform administrator permanently deletes an unused draft playbook", async ({
  page,
}) => {
  test.skip(
    !adminPassword,
    "DEMO_ADMIN_PASSWORD is required for this E2E test.",
  );
  const name = `Draft cleanup ${Date.now()}`;

  await page.goto("/dashboard/playbooks");
  await page.getByRole("button", { name: "Continue with Keycloak" }).click();
  await page
    .getByLabel("Username or email")
    .fill(process.env.DEMO_ADMIN_USERNAME ?? "platform.admin");
  await page.getByRole("textbox", { name: "Password" }).fill(adminPassword!);
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.getByRole("link", { name: "Playbooks" }).click();

  await page.getByLabel("Playbook name").fill(name);
  await page
    .getByLabel("Agreement family")
    .selectOption("liquidity_provider_agreement");
  await page.getByRole("button", { name: "Create draft" }).click();

  await page.getByRole("link", { name: "Back to playbooks" }).click();
  await expect(page).toHaveURL(/\/dashboard\/playbooks$/);
  const card = page.getByRole("article", { name });
  await card.getByRole("button", { name: "Delete playbook" }).click();
  await expect(
    page.getByRole("heading", { name: "Delete draft playbook?" }),
  ).toBeVisible();
  await page
    .getByRole("dialog", { name: "Delete draft playbook?" })
    .getByRole("button", { name: "Delete playbook" })
    .click();

  await expect(page).toHaveURL(/\/dashboard\/playbooks$/);
  await expect(
    page.getByRole("heading", { name: "Legal playbooks" }),
  ).toBeVisible();
  await expect(page.getByText(name)).not.toBeVisible();
});
