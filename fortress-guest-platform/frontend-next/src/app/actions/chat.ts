"use server";

// Highly permissive stub to satisfy any widget signature during Next.js build
export const askConcierge = async (...args: any[]): Promise<any> => {
  console.log("[CI STUB] askConcierge called", args);
  return { role: "assistant", content: "Sovereign Concierge is offline during CI." };
};
