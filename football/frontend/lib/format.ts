// 표시 형식 도우미. API가 이미 KST(+09:00) 문자열을 주므로 문자열에서 바로 날짜·시각을 읽는다.

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

/** "2026-11-28T16:30:00+09:00" → { date: "2026-11-28", label: "11월 28일 (토)", time: "16:30" } */
export function kst(iso: string) {
  const [d, t] = iso.split("T");
  const [y, m, day] = d.split("-").map(Number);
  const wd = WEEKDAYS[new Date(Date.UTC(y, m - 1, day)).getUTCDay()];
  return { date: d, label: `${m}월 ${day}일 (${wd})`, time: t.slice(0, 5) };
}

export function todayKst(): string {
  return new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);
}

export function pct(v: number | null | undefined, digits = 0): string {
  return v == null ? "-" : `${(v * 100).toFixed(digits)}%`;
}

export function num(v: number | null | undefined, digits = 1): string {
  return v == null ? "-" : v.toFixed(digits);
}

export function teamName(t: { name: string; name_ko: string | null }): string {
  return t.name_ko ?? t.name;
}
