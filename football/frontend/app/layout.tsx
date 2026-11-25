import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "축구 통계·예측",
  description: "유럽·아시아 리그 통계와 통계 모델 기반 경기 예측 (참고용 정보)",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#0f172a" };

const NAV = [
  { href: "/", label: "경기" },
  { href: "/leagues", label: "리그" },
  { href: "/model", label: "모델 성능" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="min-h-screen overflow-x-hidden bg-slate-50 text-slate-900 antialiased">
        <header className="sticky top-0 z-10 bg-slate-900 text-white">
          <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-3">
            <Link href="/" className="text-base font-bold">
              ⚽ 축구 통계·예측
            </Link>
            <nav className="flex gap-4 text-sm">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href} className="text-slate-300 hover:text-white">
                  {n.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-3xl px-4 py-4">{children}</main>
        <footer className="mx-auto max-w-3xl px-4 pb-8 pt-4 text-xs leading-relaxed text-slate-500">
          <p>
            데이터 출처: <a className="underline" href="https://www.football-data.co.uk" rel="noopener noreferrer">Football-Data.co.uk</a>
            {" · "}
            <a className="underline" href="https://www.thesportsdb.com" rel="noopener noreferrer">TheSportsDB</a>
          </p>
          <p className="mt-1">
            예측은 과거 기록을 바탕으로 한 통계 모델의 계산 결과로, 참고용 정보입니다. 리그·구단 로고와 선수 사진은 사용하지 않습니다.
          </p>
        </footer>
      </body>
    </html>
  );
}
