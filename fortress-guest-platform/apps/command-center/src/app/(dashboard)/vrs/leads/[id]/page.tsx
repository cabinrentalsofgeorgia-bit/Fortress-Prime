import React from "react";
import { VRSQuoteBuilderPanel } from "./_components/vrs-quote-builder";

interface LeadPageProps {
  params: {
    id: string;
  };
}

export default function LeadDetailPage({ params }: LeadPageProps) {
  // In a full implementation, you would fetch the lead's CRM data here
  // const leadData = await fetchLeadData(params.id);

  return (
    <div className="p-6 max-w-7xl mx-auto">
      <div className="mb-6 border-b border-gray-700 pb-4">
        <h1 className="text-3xl font-bold text-white tracking-tight">Lead Operations</h1>
        <p className="text-gray-400 font-mono mt-1">Lead ID: {params.id}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Guest CRM Data (Stubbed for now) */}
        <div className="col-span-1 lg:col-span-2 bg-gray-900 border border-gray-700 rounded-lg p-6">
          <h2 className="text-xl font-semibold text-gray-200 mb-4">Guest Inquiry Details</h2>
          <div className="space-y-4 text-gray-400">
            <p>System waiting for live CRM integration...</p>
            {/* Future Lead Intake Data Goes Here */}
          </div>
        </div>

        {/* Right Column: The Swarm Engine */}
        <div className="col-span-1">
          <VRSQuoteBuilderPanel leadId={params.id} />
        </div>
      </div>
    </div>
  );
}
