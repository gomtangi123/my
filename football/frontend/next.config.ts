import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 외부 이미지(로고·선수 사진)는 쓰지 않는다 — 저작권·초상권
  images: { unoptimized: true },
};

export default nextConfig;
