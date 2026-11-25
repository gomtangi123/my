import Link from "next/link";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

const REGION_KO = { europe: "유럽", asia: "아시아" } as const;

export default async function LeaguesPage() {
  const leagues = await api.leagues();
  return (
    <div>
      <h1 className="text-xl font-bold">리그</h1>
      {(["europe", "asia"] as const).map((region) => (
        <section key={region} className="mt-5">
          <h2 className="mb-2 text-sm font-bold text-slate-600">{REGION_KO[region]}</h2>
          <ul className="divide-y divide-slate-100 overflow-hidden rounded-xl border border-slate-200 bg-white">
            {leagues
              .filter((l) => l.region === region)
              .map((l) => (
                <li key={l.key}>
                  <Link href={`/leagues/${l.key}`} className="flex items-center justify-between gap-2 px-4 py-3 hover:bg-slate-50">
                    <div className="min-w-0">
                      <p className="truncate font-medium">{l.name_ko}</p>
                      <p className="text-xs text-slate-500">
                        {l.current_season} 시즌{l.type === "cup" ? " · 컵 대회" : ""}
                      </p>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      {l.has_match_stats && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">경기 통계</span>}
                      {l.has_xg && <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] text-blue-700">xG</span>}
                      <span className="text-slate-300">›</span>
                    </div>
                  </Link>
                </li>
              ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
