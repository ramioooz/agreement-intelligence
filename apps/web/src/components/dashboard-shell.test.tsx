import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DashboardShell } from "@/components/dashboard-shell";

describe("DashboardShell", () => {
  it("shows account context and honest placeholder navigation", () => {
    render(
      <DashboardShell
        user={{
          email: "legal.reviewer@example.test",
          name: "Legal Reviewer",
        }}
        signOutAction={() => undefined}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Agreement workspace" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Legal Reviewer")).toBeInTheDocument();
    expect(screen.getByText("legal.reviewer@example.test")).toBeInTheDocument();

    for (const item of [
      "Repository",
      "Reviews",
      "Search",
      "Playbooks",
      "Administration",
    ]) {
      expect(screen.getByLabelText(item)).toBeInTheDocument();
    }

    expect(screen.getAllByText("Coming soon")).toHaveLength(5);
    expect(
      screen.getByRole("button", { name: "Sign out" }),
    ).toBeInTheDocument();
  });
});
