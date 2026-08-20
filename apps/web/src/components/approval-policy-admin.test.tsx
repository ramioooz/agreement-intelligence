import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApprovalPolicyAdmin } from "@/components/approval-policy-admin";

describe("ApprovalPolicyAdmin", () => {
  it("submits a two-stage policy with explicit routing fields", async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined);
    render(<ApprovalPolicyAdmin policies={[]} onCreate={onCreate} />);

    fireEvent.change(screen.getByLabelText("Policy name"), {
      target: { value: "UAE legal and business review" },
    });
    fireEvent.change(screen.getByLabelText("Jurisdiction"), {
      target: { value: "UAE" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add business stage" }));
    fireEvent.click(screen.getByRole("button", { name: "Create policy" }));

    expect(
      await screen.findByText("Policy submitted for publication."),
    ).toBeVisible();
    expect(onCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "UAE legal and business review",
        jurisdiction: "UAE",
        stages: expect.arrayContaining([
          expect.objectContaining({ name: "Legal review" }),
          expect.objectContaining({ name: "Business approval" }),
        ]),
      }),
    );
  });

  it("publishes a draft through its stable policy lineage identifier", async () => {
    const onPublish = vi.fn().mockResolvedValue(undefined);
    render(
      <ApprovalPolicyAdmin
        onCreate={vi.fn()}
        onPublish={onPublish}
        policies={[
          {
            id: "version-1",
            policy_id: "policy-1",
            name: "Two-stage approval",
            version: 1,
            status: "draft",
            jurisdiction: "any",
          },
        ]}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Publish version 1" }));

    expect(onPublish).toHaveBeenCalledWith("policy-1", 1);
  });
});
