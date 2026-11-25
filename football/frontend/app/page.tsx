import Link from "next/link";
import { MatchCard } from "@/components/MatchCard";
import { api, type MatchItem } from "@/lib/api";
import { kst, todayKst } from "@/lib/format";

const TABS = [
  { key: "", label: "전체" },
  { key: "europe", label: "유럽" },
  { key: "asia", label: "아시아" },
];

export const dynamic = "force-dynamic";

export default async function Home({ searchParams }: { searchParams: Promise<{ region?: string }> }) {
  const { region = "" } = await searchParams;
  const today = todayKst();
  let matches: MatchItem[] = [];
  let error: string | null = null;
  try {
    matches = await api.matches({ from: today, region: region || undefined });
  } catch (e) {
    error = e instanceof Error ? e.message : "경기 목록을 불러오지 못했습니다";
  }

  // 날짜(KST)별 → 대회별로 묶기
  const byDate = new Map<string, Map<string, MatchItem[]>>();
  for (const m of matches) {
    const d = kst(m.kickoff_kst).date;
    if (!byDate.has(d)) byDate.set(d, new Map());
    const byLeague = byDate.get(d)!;
    if (!byLeague.has(m.league_name_ko)) byLeague.set(m.league_name_ko, []);
    byLeague.get(m.league_name_ko)!.push(m);
  }

  return (
    <div>
      <h1 className="text-xl font-bold">오늘·이번 주 경기</h1>
      <p className="mt-1 text-sm text-slate-500">한국 시간 기준 · 막대는 통계 모델의 승/무/패 확률</p>

      <div className="mt-4 flex gap-2" role="tablist">
        {TABS.map((t) => (
          <Link
            key={t.key}
            href={t.key ? `/?region=${t.key}` : "/"}
            role="tab"
            aria-selected={region === t.key}
            className={`rounded-full px-4 py-1.5 text-sm font-medium ${
              region === t.key ? "bg-slate-900 text-white" : "bg-white text-slate-600 ring-1 ring-slate-200"
            }`}
          >
            {t.label}
          </Link>
        ))}
      </div>

      {error && <p className="mt-6 rounded-lg bg-red-50 p-4 text-sm text-red-700">{error}</p>}
      {!error && matches.length === 0 && (
        <p className="mt-6 rounded-lg bg-white p-6 text-center text-sm text-slate-500 ring-1 ring-slate-200">
          이번 주 예정된 경기가 아직 없습니다. 일정은 매일 갱신됩니다.
        </p>
      )}

      {[...byDate.entries()].map(([d, byLeague]) => (
        <section key={d} className="mt-6">
          <h2 className="sticky top-12 z-[5] -mx-4 bg-slate-50/95 px-4 py-2 text-sm font-bold text-slate-700 backdrop-blur">
            {kst(`${d}T00:00:00+09:00`).label}
            {d === today && <span className="ml-2 rounded bg-blue-600 px-1.5 py-0.5 text-[11px] text-white">오늘</span>}
          </h2>
          {[...byLeague.entries()].map(([league, ms]) => (
            <div key={league} className="mt-2">
              <h3 className="mb-2 text-xs font-semibold text-slate-500">{league}</h3>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {ms.map((m) => (
                  <MatchCard key={m.id} m={m} showLeague={false} />
                ))}
              </div>
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}
