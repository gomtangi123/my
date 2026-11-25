import Link from "next/link";
import { notFound } from "next/navigation";
import { FormChips } from "@/components/FormChips";
import { ProbBar } from "@/components/ProbBar";
import { ScoreHeatmap } from "@/components/ScoreHeatmap";
import { TeamBadge } from "@/components/TeamBadge";
import { ApiError, api, type ComparisonSide, type MatchDetail } from "@/lib/api";
import { kst, num, pct, teamName } from "@/lib/format";

export const dynamic = "force-dynamic";

const MODEL_KO: Record<string, string> = { dixon_coles: "Dixon-Coles", elo: "Elo" };

function Card({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <section className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      {title && <h2 className="mb-3 text-sm font-bold text-slate-700">{title}</h2>}
      {children}
    </section>
  );
}

type Row = { label: string; get: (s: ComparisonSide) => number | null | undefined; fmt: (v: number | null | undefined) => string; higherBetter?: boolean };

const ROWS: Row[] = [
  { label: "최근 5경기 승점", get: (s) => s.form5.points, fmt: (v) => (v == null ? "-" : String(v)), higherBetter: true },
  { label: "경기당 득점", get: (s) => s.profile.goals_for, fmt: (v) => num(v, 2), higherBetter: true },
  { label: "경기당 실점", get: (s) => s.profile.goals_against, fmt: (v) => num(v, 2), higherBetter: false },
  { label: "xG (경기당)", get: (s) => s.profile.xg_for, fmt: (v) => num(v, 2), higherBetter: true },
  { label: "슈팅 (경기당)", get: (s) => s.profile.shots_for, fmt: (v) => num(v, 1), higherBetter: true },
  { label: "유효슈팅 (경기당)", get: (s) => s.profile.sot_for, fmt: (v) => num(v, 1), higherBetter: true },
  { label: "코너킥 (경기당)", get: (s) => s.profile.corners_for, fmt: (v) => num(v, 1) },
  { label: "2.5골 초과 비율", get: (s) => s.profile.over_2_5, fmt: (v) => pct(v) },
  { label: "양팀 득점 비율", get: (s) => s.profile.btts, fmt: (v) => pct(v) },
  { label: "무실점 비율", get: (s) => s.profile.clean_sheet, fmt: (v) => pct(v), higherBetter: true },
  { label: "휴식일", get: (s) => s.rest_days, fmt: (v) => (v == null ? "-" : `${Math.round(v)}일`) },
  { label: "최근 14일 경기 수", get: (s) => s.matches_last_14d, fmt: (v) => (v == null ? "-" : `${v}경기`) },
  { label: "Elo 레이팅", get: (s) => s.elo, fmt: (v) => num(v, 0), higherBetter: true },
];

function Comparison({ d }: { d: MatchDetail }) {
  const { home, away } = d.comparison;
  // 두 팀 모두 값이 없는 지표(예: 아시아 대회 슈팅·xG)는 숨긴다
  const rows = ROWS.filter((r) => r.get(home) != null || r.get(away) != null);
  return (
    <div>
      <div className="mb-2 grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-sm">
        <div className="flex items-center gap-2 font-semibold">
          <TeamBadge team={home.team} size={24} />
          <span className="truncate">{teamName(home.team)}</span>
        </div>
        <div />
        <div className="flex items-center justify-end gap-2 font-semibold">
          <span className="truncate text-right">{teamName(away.team)}</span>
          <TeamBadge team={away.team} size={24} />
        </div>
      </div>
      <div className="mb-3 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <FormChips results={home.form5.results} />
        <span className="text-center text-xs text-slate-500">최근 5경기</span>
        <div className="flex justify-end">
          <FormChips results={away.form5.results} />
        </div>
      </div>
      <table className="w-full text-sm">
        <tbody>
          {rows.map((r) => {
            const a = r.get(home);
            const b = r.get(away);
            const better =
              r.higherBetter === undefined || a == null || b == null || a === b
                ? null
                : (a > b) === r.higherBetter
                  ? "home"
                  : "away";
            return (
              <tr key={r.label} className="border-t border-slate-100">
                <td className={`py-1.5 tabular-nums ${better === "home" ? "font-bold text-blue-700" : ""}`}>{r.fmt(a)}</td>
                <td className="py-1.5 text-center text-xs text-slate-500">{r.label}</td>
                <td className={`py-1.5 text-right tabular-nums ${better === "away" ? "font-bold text-orange-600" : ""}`}>{r.fmt(b)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-slate-400">모두 경기 시작 전까지의 기록 기준. 제공되지 않는 지표는 표시하지 않습니다.</p>
    </div>
  );
}

export default async function MatchPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let d: MatchDetail;
  try {
    d = await api.match(id);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const m = d.match;
  const k = kst(m.kickoff_kst);
  const finished = m.status === "finished";
  const p = d.prediction;
  const homeName = teamName(m.home);
  const awayName = teamName(m.away);

  return (
    <div>
      <Link href="/" className="text-sm text-slate-500">
        ← 경기 목록
      </Link>

      {/* 경기 정보 */}
      <section className="mt-3 rounded-xl bg-slate-900 p-4 text-white">
        <p className="text-center text-xs text-slate-300">
          {m.league_name_ko} · {k.label} {k.time}
          {d.neutral_venue && " · 중립 경기"}
        </p>
        <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
          <div className="flex flex-col items-center gap-1 text-center">
            <TeamBadge team={m.home} size={52} />
            <span className="text-sm font-semibold leading-tight">{homeName}</span>
            {m.home.name_ko && <span className="text-[11px] text-slate-400">{m.home.name}</span>}
          </div>
          <div className="text-center">
            {finished ? (
              <span className="text-3xl font-bold tabular-nums">
                {m.home_goals} : {m.away_goals}
              </span>
            ) : (
              <span className="text-lg text-slate-400">vs</span>
            )}
            {finished && <p className="text-xs text-slate-400">종료{m.decided_by === "extra_time" ? " (연장)" : m.decided_by === "penalties" ? " (승부차기)" : ""}</p>}
          </div>
          <div className="flex flex-col items-center gap-1 text-center">
            <TeamBadge team={m.away} size={52} />
            <span className="text-sm font-semibold leading-tight">{awayName}</span>
            {m.away.name_ko && <span className="text-[11px] text-slate-400">{m.away.name}</span>}
          </div>
        </div>
      </section>

      {/* 고지문 — 예측 정보 바로 위에 항상 표시 */}
      <p className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-relaxed text-amber-900">
        ⓘ {d.disclaimer}
      </p>

      {p ? (
        <>
          <Card title={`승/무/패 확률 · ${MODEL_KO[p.main.model]}`}>
            <ProbBar p={p.main} large />
            {p.others.map((o) => (
              <div key={o.model} className="mt-4">
                <p className="mb-1 text-xs text-slate-500">참고: {MODEL_KO[o.model]} 모델</p>
                <ProbBar p={o} />
              </div>
            ))}
            {!p.pre_match && (
              <p className="mt-3 text-[11px] text-slate-400">
                이 경기는 경기 전 예측이 저장되지 않아, 검증용으로 경기 이전 데이터만으로 다시 계산한 예측을 보여줍니다.
              </p>
            )}
          </Card>

          {(p.main.over_2_5 != null || p.most_likely_score) && (
            <Card title="득점 예측">
              <div className="grid grid-cols-2 gap-3 text-center sm:grid-cols-4">
                {p.main.over_2_5 != null && <Stat label="2.5골 초과" value={pct(p.main.over_2_5)} sub={`이하 ${pct(1 - p.main.over_2_5)}`} />}
                {p.main.btts != null && <Stat label="양팀 득점" value={pct(p.main.btts)} sub={`아님 ${pct(1 - p.main.btts)}`} />}
                {p.most_likely_score && (
                  <Stat
                    label="가장 가능성 높은 스코어"
                    value={`${p.most_likely_score.home} : ${p.most_likely_score.away}`}
                    sub={pct(p.most_likely_score.probability, 1)}
                  />
                )}
                {p.expected_goals && (
                  <Stat label="예상 득점" value={`${num(p.expected_goals.home, 2)} : ${num(p.expected_goals.away, 2)}`} sub="홈 : 원정" />
                )}
              </div>
            </Card>
          )}

          {p.score_matrix && (
            <Card title="스코어 확률 히트맵">
              <ScoreHeatmap matrix={p.score_matrix} homeLabel={homeName} awayLabel={awayName} />
            </Card>
          )}
        </>
      ) : (
        <Card>
          <p className="text-sm text-slate-500">이 경기에 대한 예측이 아직 없습니다.</p>
        </Card>
      )}

      <Card title="두 팀 비교">
        <Comparison d={d} />
      </Card>

      <Card title={d.head_to_head.games ? `상대 전적 (최근 ${d.head_to_head.games}경기)` : "상대 전적"}>
        {d.head_to_head.games === 0 ? (
          <p className="text-sm text-slate-500">수집된 기간 안에 맞대결 기록이 없습니다.</p>
        ) : (
          <>
            <div className="mb-3 grid grid-cols-3 text-center">
              <Stat label={`${homeName} 승`} value={String(d.head_to_head.home_team_wins)} />
              <Stat label="무승부" value={String(d.head_to_head.draws)} />
              <Stat label={`${awayName} 승`} value={String(d.head_to_head.away_team_wins)} />
            </div>
            <ul className="divide-y divide-slate-100 text-sm">
              {d.head_to_head.matches.map((h) => {
                const [hn, an, hg, ag] = h.home_team_was_home
                  ? [homeName, awayName, h.home_team_goals, h.away_team_goals]
                  : [awayName, homeName, h.away_team_goals, h.home_team_goals];
                return (
                  <li key={h.match_id} className="flex items-center justify-between py-1.5">
                    <span className="w-24 shrink-0 text-xs text-slate-500">{h.kickoff_kst.slice(0, 10)}</span>
                    <span className="flex-1 truncate text-right">{hn}</span>
                    <span className="w-14 text-center font-semibold tabular-nums">
                      {hg} : {ag}
                    </span>
                    <span className="flex-1 truncate">{an}</span>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </Card>

      <Card title="모델 설명">
        <p className="text-sm leading-relaxed text-slate-700">{d.model_explanation}</p>
        {p && <p className="mt-2 text-[11px] text-slate-400">예측 생성: {p.made_at_kst.replace("T", " ").slice(0, 16)} (KST)</p>}
        <Link href="/model" className="mt-2 inline-block text-sm text-blue-700 underline">
          지난 경기 예측이 얼마나 맞았는지 보기 →
        </Link>
      </Card>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <p className="text-xs text-slate-500">{label}</p>
      <p className="text-xl font-bold tabular-nums">{value}</p>
      {sub && <p className="text-[11px] text-slate-400">{sub}</p>}
    </div>
  );
}
