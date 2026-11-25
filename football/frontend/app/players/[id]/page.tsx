import Link from "next/link";
import { Card } from "@/components/Card";

// 선수 페이지: 무료 데이터 소스에 선수 기록이 없어 준비 중.
// 선수 데이터(득점·도움·90분당 기록·출전 시간·레이더 차트)는 API-Football 등 선수 데이터 소스가 연결되면 채운다.
export default function PlayerPage() {
  return (
    <div>
      <Link href="/" className="text-sm text-slate-500">
        ← 경기 목록
      </Link>
      <Card title="선수 기록 — 준비 중">
        <p className="text-sm leading-relaxed text-slate-600">
          지금 쓰는 무료 데이터 소스에는 선수 기록이 없습니다. 선수 데이터를 제공하는 소스가 연결되면 득점·도움, 90분당 기록,
          출전 시간, 같은 포지션 선수 비교 레이더 차트를 이 화면에서 보여드립니다.
        </p>
      </Card>
    </div>
  );
}
