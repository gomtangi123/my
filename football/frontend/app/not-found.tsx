import Link from "next/link";

export default function NotFound() {
  return (
    <div className="py-16 text-center">
      <p className="text-lg font-bold">페이지를 찾을 수 없습니다</p>
      <Link href="/" className="mt-4 inline-block text-sm text-blue-700 underline">
        경기 목록으로
      </Link>
    </div>
  );
}
