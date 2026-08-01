import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProcessingStatusRefresher } from "@/components/processing-status-refresher";

const refresh = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

describe("ProcessingStatusRefresher", () => {
  beforeEach(() => {
    refresh.mockReset();
    vi.useFakeTimers();
  });

  afterEach(() => vi.useRealTimers());

  it("refreshes only while processing is non-terminal", () => {
    const { rerender } = render(<ProcessingStatusRefresher state="queued" />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Refreshing analysis status",
    );
    act(() => vi.advanceTimersByTime(2_000));
    expect(refresh).toHaveBeenCalledOnce();

    rerender(<ProcessingStatusRefresher state="completed" />);
    act(() => vi.advanceTimersByTime(4_000));
    expect(refresh).toHaveBeenCalledOnce();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
