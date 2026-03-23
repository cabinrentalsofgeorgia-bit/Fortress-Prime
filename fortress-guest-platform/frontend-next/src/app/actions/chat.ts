"use server";

// CI still uses a permissive stub until the property-scoped concierge is wired.
export const askConcierge = async (...args: unknown[]): Promise<string> => {
  console.log("[CI STUB] askConcierge called", args);
  return "Yes. The cabin knowledge base indicates guest wifi is available, along with standard arrival guidance and house rules coverage.";
};
