import Link from "next/link";
import { Fragment } from "react";
import { notFound } from "next/navigation";
import { Card, Pills, Stat } from "@/components/Card";
import { FormChips } from "@/components/FormChips";
import { MatchCard } from "@/components/MatchCard";
import { TeamBadge } from "@/components/TeamBadge";
import { ApiError, api, type League, type Standings } from "@/lib/api";
import { num, pct, teamName, todayKst } from "@/lib/format";

export const dynamic = "force-dynamic";

const TIEBREAK_KO = { points: "승점", gd: "득실차", gf: "다득점" } as const;

const VENUES = [
  { key: "all", label: "전체" },
  { key: "home", label: "홈" },
  { key: "away", label: "원정" },
];

export default async function LeaguePage({
  params,
  searchParams,
}: {
  params: Promise<{ key: string }>;
  searchParams: Promise<{ venue?: string; season?: string }>;
}) {
  const { key } = await params;
  const { venue = "all", season } = await searchParams;
  const league = (await api.leagues()).find((l) => l.key === key);
  if (!league) notFound();
  if (!league.has_standings) return <CupPage league={league} />;

  let st: Standings;
  try {
    st = await api.standings(key, venue, season);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const a = st.averages;
  const base = `/leagues/${key}`;
  const q = (v: string, s: string) => `${base}?venue=${v}&season=${encodeURIComponent(s)}`;

  return (
    <div>
      <Link href="/leagues" className="text-sm text-slate-500">
        ← 리그 목록
      </Link>
      <h1 className="mt-2 text-xl font-bold">{league.name_ko}</h1>

      <div className="mt-3 space-y-2">
        <Pills items={[...league.seasons].reverse().map((s) => ({ key: s, label: `${s} 시즌`, href: q(venue, s) }))} active={st.season} />
        <Pills items={VENUES.map((v) => ({ key: v.key, label: v.label, href: q(v.key, st.season) }))} active={st.venue} />
      </div>

      <Card title={`순위표${st.venue === "home" ? " (홈 경기만)" : st.venue === "away" ? " (원정 경기만)" : ""}`}>
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full min-w-[340px] text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="py-1.5 pr-1 font-medium">#</th>
                <th className="py-1.5 font-medium">팀</th>
                <th className="py-1.5 text-center font-medium">경기</th>
                <th className="hidden py-1.5 text-center font-medium sm:table-cell">승</th>
                <th className="hidden py-1.5 text-center font-medium sm:table-cell">무</th>
                <th className="hidden py-1.5 text-center font-medium sm:table-cell">패</th>
                <th className="py-1.5 text-center font-medium">득실</th>
                <th className="py-1.5 text-center font-medium">승점</th>
                <th className="hidden py-1.5 pl-2 font-medium sm:table-cell">최근 5경기</th>
              </tr>
            </thead>
            <tbody>
              {st.rows.map((r, i) => (
                <Fragment key={r.team.id}>
                {r.group && r.group !== st.rows[i - 1]?.group && (
                  <tr>
                    <td colSpan={9} className={`pb-1 pt-3 text-xs font-bold ${r.group === "A" ? "text-blue-700" : "text-slate-500"}`}>
                      {r.group === "A" ? "파이널 A (상위 그룹)" : "파이널 B (하위 그룹) — 승점과 관계없이 파이널 A 아래"}
                    </td>
                  </tr>
                )}
                <tr className="border-t border-slate-100">
                  <td className="py-2 pr-1 tabular-nums text-slate-500">{r.rank}</td>
                  <td className="py-2">
                    <Link href={`/teams/${r.team.id}`} className="flex min-w-0 items-center gap-2">
                      <TeamBadge team={r.team} size={22} />
                      <span className="truncate">{teamName(r.team)}</span>
                    </Link>
                  </td>
                  <td className="py-2 text-center tabular-nums">{r.played}</td>
                  <td className="hidden py-2 text-center tabular-nums sm:table-cell">{r.won}</td>
                  <td className="hidden py-2 text-center tabular-nums sm:table-cell">{r.drawn}</td>
                  <td className="hidden py-2 text-center tabular-nums sm:table-cell">{r.lost}</td>
                  <td className="py-2 text-center tabular-nums">{r.goal_diff > 0 ? `+${r.goal_diff}` : r.goal_diff}</td>
                  <td className="py-2 text-center font-bold tabular-nums">{r.points}</td>
                  <td className="hidden py-2 pl-2 sm:table-cell">
                    <FormChips results={r.form} />
                  </td>
                </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] text-slate-400">{(league.tiebreak ?? ["points", "gd", "gf"]).map((k) => TIEBREAK_KO[k]).join(" → ")} 순{league.has_split ? ", 정규 라운드 후 상·하위 그룹 분리" : ""}. 화면이 넓으면 승·무·패와 최근 5경기도 표시됩니다.</p>
      </Card>

      <Card title={`리그 평균 지표 (${a.matches}경기)`}>
        <div className="grid grid-cols-3 gap-3 text-center">
          <Stat label="경기당 골" value={num(a.goals_per_match, 2)} />
          <Stat label="2.5골 초과" value={pct(a.over_2_5_rate)} />
          <Stat label="양팀 득점" value={pct(a.btts_rate)} />
          <Stat label="홈승" value={pct(a.home_win_rate)} />
          <Stat label="무승부" value={pct(a.draw_rate)} />
          <Stat label="원정승" value={pct(a.away_win_rate)} />
          {a.shots_per_team != null && <Stat label="팀당 슈팅" value={num(a.shots_per_team, 1)} />}
          {a.corners_per_team != null && <Stat label="팀당 코너킥" value={num(a.corners_per_team, 1)} />}
          {a.xg_per_team != null && <Stat label="팀당 xG" value={num(a.xg_per_team, 2)} />}
        </div>
      </Card>

      <Card title="득점 순위">
        <p className="text-sm text-slate-500">선수 기록 데이터가 아직 없어 준비 중입니다.</p>
      </Card>
    </div>
  );
}

async function CupPage({ league }: { league: League }) {
  const today = todayKst();
  const from = new Date(Date.now() - 21 * 864e5 + 9 * 3600e3).toISOString().slice(0, 10);
  const to = new Date(Date.now() + 21 * 864e5 + 9 * 3600e3).toISOString().slice(0, 10);
  const ms = await api.matches({ from, to, league: league.key });
  const upcoming = ms.filter((m) => m.status === "scheduled" && m.kickoff_kst.slice(0, 10) >= today);
  const recent = ms.filter((m) => m.status === "finished").reverse();
  return (
    <div>
      <Link href="/leagues" className="text-sm text-slate-500">
        ← 리그 목록
      </Link>
      <h1 className="mt-2 text-xl font-bold">{league.name_ko}</h1>
      <p className="mt-1 text-sm text-slate-500">컵 대회는 순위표 대신 최근·다가오는 경기를 보여줍니다 (앞뒤 3주).</p>
      <Card title="다가오는 경기">
        {upcoming.length ? (
          <div className="grid grid-cols-1 gap-2">{upcoming.map((m) => <MatchCard key={m.id} m={m} showLeague={false} />)}</div>
        ) : (
          <p className="text-sm text-slate-500">예정된 경기가 없습니다.</p>
        )}
      </Card>
      <Card title="최근 결과">
        {recent.length ? (
          <div className="grid grid-cols-1 gap-2">{recent.map((m) => <MatchCard key={m.id} m={m} showLeague={false} />)}</div>
        ) : (
          <p className="text-sm text-slate-500">최근 경기가 없습니다.</p>
        )}
      </Card>
    </div>
  );
}
