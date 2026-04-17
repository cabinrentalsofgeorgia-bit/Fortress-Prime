"use client";

import { useState } from "react";
import { ManualQuoteGenerator } from "../_components/manual-quote-generator";
import { TaylorQuoteDashboard } from "../_components/taylor-quote-dashboard";

const TABS = [
  { id: "taylor", label: "Taylor Quote Tool" },
  { id: "manual", label: "Manual Quote Engine" },
] as const;

type Tab = (typeof TABS)[number]["id"];

export default function VrsQuotesPage() {
  const [activeTab, setActiveTab] = useState<Tab>("taylor");

  return (
    <div className="space-y-6">
      <div className="flex gap-1 rounded-lg border bg-muted p-1 w-fit">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "taylor" && <TaylorQuoteDashboard />}
      {activeTab === "manual" && <ManualQuoteGenerator />}
    </div>
  );
}
