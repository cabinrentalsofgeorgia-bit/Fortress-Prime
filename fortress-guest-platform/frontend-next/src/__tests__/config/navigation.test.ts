import { describe, expect, it } from "vitest";
import {
  filterCommandHierarchy,
  flattenCommandHierarchy,
  isActionItem,
  normalizeRole,
} from "@/config/navigation";

describe("navigation config", () => {
  it("normalizes current app roles into the hardened role contract", () => {
    expect(normalizeRole("admin")).toBe("super_admin");
    expect(normalizeRole("manager")).toBe("ops_manager");
    expect(normalizeRole("legal")).toBe("legal");
    expect(normalizeRole("maintenance")).toBe("staff");
  });

  it("filters restricted entries before render for ops roles", () => {
    const groups = filterCommandHierarchy("manager");
    const items = flattenCommandHierarchy(groups);
    const labels = items.map((item) => item.label);

    expect(labels).toContain("Operations Dashboard");
    expect(labels).toContain("System Health");
    expect(labels).toContain("Run Housekeeping Auto-Schedule");
    expect(labels).toContain("Dispatch Hunter Target");
    expect(labels).not.toContain("Iron Dome Ledger");
    expect(labels).not.toContain("E-Discovery Vault");
    expect(items.some((item) => item.label === "Run Housekeeping Auto-Schedule" && isActionItem(item))).toBe(true);
    expect(items.some((item) => item.label === "Dispatch Hunter Target" && isActionItem(item))).toBe(true);
  });

  it("returns only legal surfaces for the legal role", () => {
    const groups = filterCommandHierarchy("legal");
    const labels = flattenCommandHierarchy(groups).map((item) => item.label);

    expect(labels).toContain("Active Dockets");
    expect(labels).toContain("Damage Claims");
    expect(labels).not.toContain("Operations Dashboard");
    expect(labels).not.toContain("Fortress Prime");
  });
});
