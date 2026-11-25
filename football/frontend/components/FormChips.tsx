const STYLE: Record<string, string> = {
  승: "bg-emerald-500 text-white",
  무: "bg-slate-300 text-slate-800",
  패: "bg-rose-500 text-white",
};

/** 최근 경기 결과 칩 (오래된 → 최근 순). */
export function FormChips({ results }: { results: string }) {
  if (!results) return <span className="text-xs text-slate-400">기록 없음</span>;
  return (
    <span className="inline-flex gap-0.5" aria-label={`최근 경기 ${results}`}>
      {[...results].map((r, i) => (
        <span key={i} className={`inline-flex h-5 w-5 items-center justify-center rounded text-[11px] font-bold ${STYLE[r] ?? "bg-slate-100"}`}>
          {r}
        </span>
      ))}
    </span>
  );
}
