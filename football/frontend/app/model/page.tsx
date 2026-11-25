import Link from "next/link";
import { Card } from "@/components/Card";
import { CalibrationChart } from "@/components/charts";
import { TeamBadge } from "@/components/TeamBadge";
import { api, type PerformanceRow } from "@/lib/api";
import { pct, teamName } from "@/lib/format";

export const dynamic = "force-dynamic";

const SHORT: Record<string, string> = { "Dixon-Coles": "DC", "xG Dixon-Coles": "xG DC", LightGBM: "LGBM", Elo: "Elo" };

function PerfTable({ rows }: { rows: PerformanceRow[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-xs text-slate-500">
          <th className="py-1 text-left font-medium">모델</th>
          <th className="py-1 text-right font-medium">경기</th>
          <th className="py-1 text-right font-medium">Log loss</th>
          <th className="py-1 text-right font-medium">Brier</th>
          <th className="py-1 text-right font-medium">적중률</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.model} className="border-t border-slate-100 tabular-nums">
            <td className="py-1.5 font-medium">{r.model}</td>
            <td className="py-1.5 text-right">{r.matches.toLocaleString()}</td>
            <td className="py-1.5 text-right">{r.log_loss.toFixed(3)}</td>
            <td className="py-1.5 text-right">{r.brier.toFixed(3)}</td>
            <td className="py-1.5 text-right">{pct(r.accuracy, 1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default async function ModelPage() {
  const p = await api.performance();
  const series = Object.entries(p.calibration).map(([name, points]) => ({ name, points }));
  return (
    <div>
      <h1 className="text-xl font-bold">모델 성능</h1>
      <p className="mt-1 text-sm text-slate-500">지난 경기에서 예측이 실제 결과와 얼마나 맞았는지 투명하게 공개합니다.</p>

      <Card title="전체 성능">
        <PerfTable rows={p.overall} />
        <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
          Log loss·Brier는 낮을수록 좋습니다. 아무 정보 없이 세 결과에 같은 확률(33%)을 주면 Log loss는 약 1.099입니다. 적중률은 가장 높은
          확률을 준 결과가 맞은 비율로, 참고용입니다.
        </p>
      </Card>

      <Card title="보정 그래프">
        <CalibrationChart series={series} />
        <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
          예를 들어 &quot;40%&quot;라고 예측한 결과들이 실제로 약 40% 일어났다면 점선 위에 놓입니다. 점선에 가까울수록 확률을 그대로 믿을 수
          있습니다.
        </p>
      </Card>

      <Card title="대회별 Log loss (낮을수록 좋음)">
        <div className="-mx-4 overflow-x-auto px-4">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500">
                <th className="py-1 text-left font-medium">대회</th>
                <th className="px-1 py-1 text-right font-medium">DC</th>
                <th className="px-1 py-1 text-right font-medium">Elo</th>
                <th className="px-1 py-1 text-right font-medium">LGBM</th>
                <th className="py-1 pl-2 text-center font-medium">대표</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(p.by_league).map(([name, rows]) => {
                const get = (m: string) => rows.find((r) => r.model === m);
                const cands = ["Dixon-Coles", "Elo", "LightGBM"].map(get);
                const best = Math.min(...cands.map((r) => r?.log_loss ?? Infinity));
                const cell = (r?: PerformanceRow) =>
                  r ? <span className={r.log_loss === best ? "font-bold text-slate-900" : "text-slate-500"}>{r.log_loss.toFixed(3)}</span> : "-";
                return (
                  <tr key={name} className="border-t border-slate-100 tabular-nums">
                    <td className="py-1.5">
                      {name}
                      <span className="block text-[11px] text-slate-400">{(cands.find(Boolean)?.matches ?? 0).toLocaleString()}경기</span>
                    </td>
                    {cands.map((r, i) => (
                      <td key={i} className="px-1 py-1.5 text-right text-xs sm:text-sm">
                        {cell(r)}
                      </td>
                    ))}
                    <td className="py-1.5 pl-2 text-center">
                      <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[11px] font-semibold text-blue-700">
                        {SHORT[p.selection?.[name] ?? ""] ?? "-"}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-slate-400">
          DC = Dixon-Coles, LGBM = LightGBM, xG DC = xG Dixon-Coles. 대회마다 세 모델이 모두 예측한 같은 경기로 비교했고, 굵은 숫자가 가장 좋은 모델입니다.
          대표 모델은 기본 모델(리그 Dixon-Coles, 컵 Elo)보다 Log loss가 0.003 이상 낮고 비교 경기가 200개 이상일 때만 바꿉니다.
        </p>
      </Card>

      <Card title="최근 경기: 예측 vs 실제">
        <ul className="divide-y divide-slate-100">
          {p.recent.map((r) => (
            <li key={r.match.id}>
              <Link href={`/matches/${r.match.id}`} className="flex items-center gap-2 py-2 text-sm">
                <span className={`w-6 shrink-0 text-center font-bold ${r.hit ? "text-emerald-600" : "text-rose-500"}`}>
                  {r.hit ? "○" : "×"}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1">
                    <TeamBadge team={r.match.home} size={18} />
                    <span className="truncate">{teamName(r.match.home)}</span>
                    <span className="shrink-0 px-1 font-semibold tabular-nums">
                      {r.match.home_goals}:{r.match.away_goals}
                    </span>
                    <span className="truncate">{teamName(r.match.away)}</span>
                    <TeamBadge team={r.match.away} size={18} />
                  </div>
                  <p className="text-[11px] text-slate-500">
                    {r.match.league_name_ko} · 예측 {r.predicted_pick} → 실제 {r.actual}
                    {r.kind === "backtest" && " · 검증 예측"}
                  </p>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="설명">
        <ul className="list-disc space-y-1 pl-5 text-xs leading-relaxed text-slate-600">
          {p.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
