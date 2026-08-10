import { Suspense } from "react";
import { AnalyticsCharts } from "@/components/analytics-charts";
import { DashboardCards } from "@/components/dashboard-cards";
import { ExportButtons } from "@/components/export-buttons";
import { SimilarGamesSearch } from "@/components/similar-games-search";
import { FiltersBar } from "@/components/filters-bar";
import { GamesTable } from "@/components/games-table";

export default function DashboardPage() {
  return (
    <div className="flex flex-col gap-5">
      <DashboardCards />
      <AnalyticsCharts />
      <SimilarGamesSearch />
      <Suspense>
        <div className="flex flex-col gap-2">
          <FiltersBar />
          <ExportButtons />
        </div>
        <GamesTable />
      </Suspense>
    </div>
  );
}
