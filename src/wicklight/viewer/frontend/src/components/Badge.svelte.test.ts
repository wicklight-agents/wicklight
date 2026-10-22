import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Badge from "./Badge.svelte";

describe("Badge", () => {
  it("renders the icon and a text label so status is not color-only", () => {
    render(Badge, { props: { badge: { label: "blocked", icon: "⨯", tone: "danger" } } });
    // The text label carries meaning without relying on color.
    expect(screen.getByText("blocked")).toBeInTheDocument();
    expect(screen.getByText("⨯")).toBeInTheDocument();
  });
});
