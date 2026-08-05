import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DashboardShell } from "@/components/dashboard-shell";

describe("DashboardShell", () => {
  it("links authenticated users to the agreement repository", () => {
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

    expect(screen.getByRole("link", { name: "Repository" })).toHaveAttribute(
      "href",
      "/dashboard/agreements",
    );
    expect(screen.getByRole("link", { name: "Playbooks" })).toHaveAttribute(
      "href",
      "/dashboard/playbooks",
    );
    expect(screen.getByRole("link", { name: "Reviews" })).toHaveAttribute(
      "href",
      "/dashboard/reviews",
    );
    expect(screen.getAllByText("Available")).toHaveLength(5);
    expect(screen.getByRole("link", { name: "Search" })).toHaveAttribute(
      "href",
      "/dashboard/search",
    );
    expect(screen.getByRole("link", { name: "Reviews" })).toHaveAttribute(
      "href",
      "/dashboard/reviews",
    );
    expect(screen.getByRole("link", { name: "Administration" })).toHaveAttribute(
      "href",
      "/dashboard/approval-policies",
    );
    expect(
      screen.getByRole("button", { name: "Sign out" }),
    ).toBeInTheDocument();
  });
});
