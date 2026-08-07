import { Suspense } from "react";
import { DashboardCards } from "@/components/dashboard-cards";
import { FiltersBar } from "@/components/filters-bar";
import { GamesTable } from "@/components/games-table";

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-5">
      <DashboardCards />
      <Suspense>
        <FiltersBar />
        <GamesTable />
      </Suspense>
    </div>
  );
}
