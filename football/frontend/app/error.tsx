"use client";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="py-16 text-center">
      <p className="text-lg font-bold">데이터를 불러오지 못했습니다</p>
      <p className="mt-2 text-sm text-slate-500">{error.message}</p>
      <button onClick={reset} className="mt-4 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white">
        다시 시도
      </button>
    </div>
  );
}
