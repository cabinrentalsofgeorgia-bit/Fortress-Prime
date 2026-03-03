import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Providers } from "@/components/providers";

describe("Providers", () => {
  it("renders children", () => {
    render(
      <Providers>
        <div data-testid="child">Hello</div>
      </Providers>,
    );
    expect(screen.getByTestId("child")).toHaveTextContent("Hello");
  });
});
