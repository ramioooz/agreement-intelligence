import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignInPanel } from "@/components/sign-in-panel";

describe("SignInPanel", () => {
  it("explains the product and delegates credentials to Keycloak", () => {
    render(<SignInPanel signInAction={() => undefined} />);

    expect(
      screen.getByRole("heading", {
        name: "Sign in to Agreement Intelligence",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Your credentials are handled by the identity provider/i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Continue with Keycloak" }),
    ).toBeInTheDocument();
  });
});
