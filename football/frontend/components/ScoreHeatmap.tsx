import { pct } from "@/lib/format";

/** 스코어 확률 히트맵. 행 = 홈팀 득점, 열 = 원정팀 득점 (0~6골). 진할수록 확률이 높다. */
export function ScoreHeatmap({ matrix, homeLabel, awayLabel }: { matrix: number[][]; homeLabel: string; awayLabel: string }) {
  const max = Math.max(...matrix.flat());
  const n = matrix.length;
  return (
    <div>
      <div className="mb-1 text-center text-xs text-slate-500">→ {awayLabel} 득점</div>
      <div className="flex">
        <div className="flex w-5 items-center justify-center">
          <span className="whitespace-nowrap text-xs text-slate-500 [writing-mode:vertical-rl]">{homeLabel} 득점 →</span>
        </div>
        <div className="grid flex-1 gap-0.5" style={{ gridTemplateColumns: `1.25rem repeat(${n}, minmax(0, 1fr))` }}>
          <div />
          {matrix[0].map((_, j) => (
            <div key={`c${j}`} className="text-center text-xs font-medium text-slate-500">
              {j}
            </div>
          ))}
          {matrix.map((row, i) => (
            <div key={`r${i}`} className="contents">
              <div className="flex items-center justify-center text-xs font-medium text-slate-500">{i}</div>
              {row.map((v, j) => {
                const a = max > 0 ? v / max : 0;
                return (
                  <div
                    key={`${i}-${j}`}
                    title={`${i}:${j} — ${pct(v, 1)}`}
                    className="flex aspect-square items-center justify-center rounded text-[10px] tabular-nums sm:text-xs"
                    style={{
                      backgroundColor: `rgba(37, 99, 235, ${0.06 + a * 0.84})`,
                      color: a > 0.5 ? "white" : "#334155",
                    }}
                  >
                    {v >= 0.005 ? (v * 100).toFixed(v >= 0.1 ? 0 : 1) : ""}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
      <p className="mt-1 text-right text-[11px] text-slate-400">칸 안 숫자: 확률(%)</p>
    </div>
  );
}
