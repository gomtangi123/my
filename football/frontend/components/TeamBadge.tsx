import type { TeamRef } from "@/lib/api";

/** 로고 대신 쓰는 팀 컬러 원형 배지 + 약칭 (구단 엠블럼·로고는 저작권 문제로 쓰지 않는다). */
export function TeamBadge({ team, size = 32 }: { team: TeamRef; size?: number }) {
  const fontSize = Math.max(9, Math.round(size * (team.short_name.length > 3 ? 0.26 : 0.32)));
  return (
    <span
      aria-hidden
      className="inline-flex shrink-0 items-center justify-center rounded-full font-bold text-white ring-1 ring-black/10"
      style={{ width: size, height: size, backgroundColor: team.color, fontSize }}
    >
      {team.short_name}
    </span>
  );
}
