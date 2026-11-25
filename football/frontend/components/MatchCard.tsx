import Link from "next/link";
import type { MatchItem } from "@/lib/api";
import { kst, teamName } from "@/lib/format";
import { ProbBar } from "./ProbBar";
import { TeamBadge } from "./TeamBadge";

const STATUS_KO: Record<string, string> = { postponed: "연기", cancelled: "취소" };

export function MatchCard({ m, showLeague = true }: { m: MatchItem; showLeague?: boolean }) {
  const { time } = kst(m.kickoff_kst);
  const finished = m.status === "finished";
  const kickedOff = new Date(m.kickoff_kst).getTime() < Date.now();
  return (
    <Link
      href={`/matches/${m.id}`}
      className="block min-w-0 rounded-xl border border-slate-200 bg-white p-3 shadow-sm transition active:scale-[0.99] hover:border-slate-300"
    >
      <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
        <span className="truncate">{showLeague ? m.league_name_ko : ""}</span>
        <span className="shrink-0">
          {STATUS_KO[m.status] ?? (finished ? "종료" : kickedOff ? "결과 대기" : time)}
          {m.decided_by === "extra_time" && " (연장)"}
          {m.decided_by === "penalties" && " (승부차기)"}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <TeamBadge team={m.home} />
          <span className="truncate text-sm font-medium">{teamName(m.home)}</span>
        </div>
        <div className="w-14 shrink-0 text-center text-base font-bold tabular-nums">
          {finished ? `${m.home_goals} : ${m.away_goals}` : <span className="text-xs font-normal text-slate-400">vs</span>}
        </div>
        <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
          <span className="truncate text-right text-sm font-medium">{teamName(m.away)}</span>
          <TeamBadge team={m.away} />
        </div>
      </div>
      {m.prediction && (
        <div className="mt-3">
          <ProbBar p={m.prediction} />
        </div>
      )}
    </Link>
  );
}
