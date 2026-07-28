import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiStatus } from "@/components/api-status";

describe("ApiStatus", () => {
  it("announces a connected API", () => {
    render(<ApiStatus status="connected" />);

    expect(screen.getByRole("status")).toHaveTextContent("API connected");
  });

  it("announces an unavailable API", () => {
    render(<ApiStatus status="unavailable" />);

    expect(screen.getByRole("status")).toHaveTextContent("API unavailable");
  });
});
