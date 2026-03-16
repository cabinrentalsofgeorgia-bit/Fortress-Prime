import GuestDataTable from "./_components/guest-data-table";

export default function GuestsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">
          Guest Intelligence
        </h1>
        <p className="text-muted-foreground">
          Historical guest ledger and lifetime value tracking
        </p>
      </div>

      <GuestDataTable />
    </div>
  );
}
