import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import DashboardError from "@/app/(dashboard)/error";

describe("DashboardError", () => {
  it("renders the error message", () => {
    const error = new Error("Test failure");
    const reset = vi.fn();

    render(<DashboardError error={error} reset={reset} />);

    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("Test failure")).toBeInTheDocument();
  });

  it("calls reset on try again click", () => {
    const error = new Error("oops");
    const reset = vi.fn();

    render(<DashboardError error={error} reset={reset} />);

    fireEvent.click(screen.getByText("Try again"));
    expect(reset).toHaveBeenCalledOnce();
  });

  it("shows digest reference when available", () => {
    const error = Object.assign(new Error("err"), { digest: "abc123" });
    render(<DashboardError error={error} reset={vi.fn()} />);
    expect(screen.getByText("Ref: abc123")).toBeInTheDocument();
  });
});
