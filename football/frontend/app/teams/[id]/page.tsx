import Link from "next/link";
import { notFound } from "next/navigation";
import { Card, Stat } from "@/components/Card";
import { FormChart, HalfGoalsChart, type FormPoint } from "@/components/charts";
import { FormChips } from "@/components/FormChips";
import { MatchCard } from "@/components/MatchCard";
import { TeamBadge } from "@/components/TeamBadge";
import { ApiError, api, type MatchItem, type TeamDetail } from "@/lib/api";
import { num, pct, teamName } from "@/lib/format";

export const dynamic = "force-dynamic";

function toFormPoints(teamId: number, ms: MatchItem[]): FormPoint[] {
  return [...ms].reverse().map((m) => {
    const home = m.home.id === teamId;
    const gf = (home ? m.home_goals : m.away_goals) ?? 0;
    const ga = (home ? m.away_goals : m.home_goals) ?? 0;
    // 연장·승부차기 경기는 90분 기준 무승부로 본다
    const extra = m.decided_by === "extra_time" || m.decided_by === "penalties";
    const result = extra ? "무" : gf > ga ? "승" : gf < ga ? "패" : "무";
    const opp = home ? m.away : m.home;
    return {
      label: m.kickoff_kst.slice(5, 10).replace("-", "/"),
      opponent: `${teamName(opp)} (${home ? "홈" : "원정"})`,
      points: result === "승" ? 3 : result === "무" ? 1 : 0,
      gf,
      ga,
      result,
    };
  });
}

const PROFILE_ITEMS: { key: string; label: string; fmt: (v: number | null) => string }[] = [
  { key: "goals_for", label: "경기당 득점", fmt: (v) => num(v, 2) },
  { key: "goals_against", label: "경기당 실점", fmt: (v) => num(v, 2) },
  { key: "over_2_5", label: "2.5골 초과", fmt: (v) => pct(v) },
  { key: "btts", label: "양팀 득점", fmt: (v) => pct(v) },
  { key: "clean_sheet", label: "무실점", fmt: (v) => pct(v) },
  { key: "failed_to_score", label: "무득점", fmt: (v) => pct(v) },
  { key: "xg_for", label: "xG", fmt: (v) => num(v, 2) },
  { key: "xg_against", label: "xGA (상대 xG)", fmt: (v) => num(v, 2) },
  { key: "goals_minus_xg", label: "득점 − xG", fmt: (v) => (v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(2)}`) },
  { key: "shots_for", label: "슈팅", fmt: (v) => num(v, 1) },
  { key: "sot_for", label: "유효슈팅", fmt: (v) => num(v, 1) },
  { key: "corners_for", label: "코너킥", fmt: (v) => num(v, 1) },
  { key: "yellow_for", label: "경고", fmt: (v) => num(v, 1) },
  { key: "red_for", label: "퇴장", fmt: (v) => num(v, 2) },
];

export default async function TeamPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let t: TeamDetail;
  try {
    t = await api.team(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const s = t.standing;
  const formPoints = toFormPoints(t.team.id, t.recent_matches);
  const gh = t.goals_by_half;
  const hasHalves = gh.first_half_goals_for != null;
  const profile = PROFILE_ITEMS.filter((p) => t.profile[p.key] != null);

  return (
    <div>
      {t.league && (
        <Link href={`/leagues/${t.league.key}`} className="text-sm text-slate-500">
          ← {t.league.name_ko}
        </Link>
      )}
      <section className="mt-3 flex items-center gap-4 rounded-xl bg-slate-900 p-4 text-white">
        <TeamBadge team={t.team} size={56} />
        <div className="min-w-0">
          <h1 className="truncate text-xl font-bold">{teamName(t.team)}</h1>
          {t.team.name_ko && <p className="text-xs text-slate-400">{t.team.name}</p>}
          {s && t.league && (
            <p className="mt-1 text-sm text-slate-300">
              {t.league.name_ko} {t.season} · {s.rank}위 · 승점 {s.points} ({s.won}승 {s.drawn}무 {s.lost}패)
            </p>
          )}
        </div>
      </section>

      <Card title="최근 폼">
        <div className="mb-3 flex flex-col gap-1">
          <FormChips results={t.form10.results} />
          <span className="text-xs text-slate-500">
            최근 {t.form10.games}경기 승점 {t.form10.points} · 득실 {t.form10.goals_for}-{t.form10.goals_against}
          </span>
        </div>
        {formPoints.length > 0 && <FormChart data={formPoints} />}
        <p className="mt-1 text-[11px] text-slate-400">수집된 모든 대회 기준 (UEFA 대회·국내 컵은 미포함)</p>
      </Card>

      {t.home && t.away && (
        <Card title="홈 / 원정 성적 (이번 시즌 리그)">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500">
                <th className="py-1 text-left font-medium" />
                <th className="py-1 font-medium">경기</th>
                <th className="py-1 font-medium">승</th>
                <th className="py-1 font-medium">무</th>
                <th className="py-1 font-medium">패</th>
                <th className="py-1 font-medium">득점</th>
                <th className="py-1 font-medium">실점</th>
                <th className="py-1 font-medium">승점</th>
              </tr>
            </thead>
            <tbody>
              {[
                ["홈", t.home],
                ["원정", t.away],
              ].map(([label, r]) => {
                const x = r as Record<string, number | string | null>;
                return (
                  <tr key={label as string} className="border-t border-slate-100 text-center tabular-nums">
                    <td className="py-1.5 text-left font-medium">{label as string}</td>
                    <td>{x.played}</td>
                    <td>{x.won}</td>
                    <td>{x.drawn}</td>
                    <td>{x.lost}</td>
                    <td>{x.gf}</td>
                    <td>{x.ga}</td>
                    <td className="font-bold">{x.points}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      )}

      {hasHalves && (
        <Card title="전반 / 후반 경기당 득점·실점">
          <HalfGoalsChart
            data={[
              { half: "전반", 득점: gh.first_half_goals_for ?? 0, 실점: gh.first_half_goals_against ?? 0 },
              { half: "후반", 득점: gh.second_half_goals_for ?? 0, 실점: gh.second_half_goals_against ?? 0 },
            ]}
          />
          <p className="mt-1 text-[11px] text-slate-400">골 시간 데이터가 없어 15분 단위 대신 전·후반으로 나눠 보여줍니다.</p>
        </Card>
      )}

      {profile.length > 0 && (
        <Card title={`팀 지표 (경기당, ${t.profile.games ?? 0}경기 기준)`}>
          <div className="grid grid-cols-3 gap-3 text-center">
            {profile.map((p) => (
              <Stat key={p.key} label={p.label} value={p.fmt(t.profile[p.key] as number | null)} />
            ))}
          </div>
        </Card>
      )}

      {t.upcoming_matches.length > 0 && (
        <Card title="다가오는 경기">
          <div className="grid grid-cols-1 gap-2">
            {t.upcoming_matches.map((m) => (
              <MatchCard key={m.id} m={m} />
            ))}
          </div>
        </Card>
      )}

      <Card title="최근 경기">
        <div className="grid grid-cols-1 gap-2">
          {t.recent_matches.map((m) => (
            <MatchCard key={m.id} m={m} />
          ))}
        </div>
      </Card>

      <Card title="주요 선수 · 부상자">
        <ul className="list-disc space-y-1 pl-5 text-sm text-slate-500">
          {t.data_notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
