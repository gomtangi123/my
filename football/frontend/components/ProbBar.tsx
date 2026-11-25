import type { Probabilities } from "@/lib/api";
import { pct } from "@/lib/format";

export const OUTCOME_COLORS = { home: "bg-blue-600", draw: "bg-slate-400", away: "bg-orange-500" };

/** 승/무/패 확률 막대. 가장 높은 결과는 숫자를 굵게 표시. */
export function ProbBar({ p, large = false }: { p: Probabilities; large?: boolean }) {
  const parts = [
    { key: "home", label: "홈승", v: p.home_win, cls: OUTCOME_COLORS.home },
    { key: "draw", label: "무", v: p.draw, cls: OUTCOME_COLORS.draw },
    { key: "away", label: "원정승", v: p.away_win, cls: OUTCOME_COLORS.away },
  ];
  const max = Math.max(p.home_win, p.draw, p.away_win);
  return (
    <div className="w-full" role="img" aria-label={`홈승 ${pct(p.home_win)}, 무승부 ${pct(p.draw)}, 원정승 ${pct(p.away_win)}`}>
      <div className={`flex w-full overflow-hidden rounded-full bg-slate-100 ${large ? "h-4" : "h-2.5"}`}>
        {parts.map((x) => (
          <div key={x.key} className={x.cls} style={{ width: `${x.v * 100}%` }} />
        ))}
      </div>
      <div className={`mt-1 flex justify-between ${large ? "text-sm" : "text-xs"} text-slate-600`}>
        {parts.map((x) => (
          <span key={x.key} className={x.v === max ? "font-bold text-slate-900" : ""}>
            {x.label} {pct(x.v)}
          </span>
        ))}
      </div>
    </div>
  );
}
