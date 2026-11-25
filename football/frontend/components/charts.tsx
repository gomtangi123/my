"use client";
// Recharts 그래프 (브라우저에서 그림). 색은 확률 막대와 같은 계열을 쓴다.

import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const BLUE = "#2563eb";
const ORANGE = "#f97316";
const GREEN = "#16a34a";
const SLATE = "#94a3b8";

export type FormPoint = { label: string; opponent: string; points: number; gf: number; ga: number; result: string };

/** 폼 그래프: 경기별 득점·실점 막대 + 누적 승점 선 (오래된 경기 → 최근) */
export function FormChart({ data }: { data: FormPoint[] }) {
  let acc = 0;
  const rows = data.map((d) => ({ ...d, cum: (acc += d.points) }));
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer>
        <ComposedChart data={rows} margin={{ top: 8, right: 4, left: -24, bottom: 0 }}>
          <CartesianGrid stroke="#e2e8f0" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 9 }} interval="preserveStartEnd" minTickGap={6} />
          <YAxis yAxisId="g" allowDecimals={false} tick={{ fontSize: 10 }} />
          <YAxis yAxisId="p" orientation="right" allowDecimals={false} tick={{ fontSize: 10 }} width={28} />
          <Tooltip
            formatter={(v, name) => [String(v), String(name)]}
            labelFormatter={(_, p) => (p?.[0] ? `${p[0].payload.label} vs ${p[0].payload.opponent} (${p[0].payload.result})` : "")}
          />
          <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 4 }} />
          <Bar isAnimationActive={false} yAxisId="g" dataKey="gf" name="득점" fill={BLUE} radius={[3, 3, 0, 0]} />
          <Bar isAnimationActive={false} yAxisId="g" dataKey="ga" name="실점" fill={ORANGE} radius={[3, 3, 0, 0]} />
          <Line isAnimationActive={false} yAxisId="p" dataKey="cum" name="누적 승점" stroke={GREEN} strokeWidth={2} dot={{ r: 3 }} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/** 전반·후반 경기당 득점·실점 */
export function HalfGoalsChart({ data }: { data: { half: string; 득점: number; 실점: number }[] }) {
  return (
    <div className="h-44 w-full">
      <ResponsiveContainer>
        <BarChart data={data} margin={{ top: 8, right: 4, left: -24, bottom: 0 }}>
          <CartesianGrid stroke="#e2e8f0" vertical={false} />
          <XAxis dataKey="half" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 10 }} />
          <Tooltip formatter={(v) => Number(v).toFixed(2)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar isAnimationActive={false} dataKey="득점" fill={BLUE} radius={[3, 3, 0, 0]} />
          <Bar isAnimationActive={false} dataKey="실점" fill={ORANGE} radius={[3, 3, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** 보정 그래프: x = 예측 확률, y = 실제 발생 비율. 대각선에 가까울수록 좋다. */
export function CalibrationChart({ series }: { series: { name: string; points: { predicted: number; observed: number; count: number }[] }[] }) {
  const colors = [BLUE, ORANGE, GREEN];
  const diagonal = [
    { predicted: 0, observed: 0 },
    { predicted: 1, observed: 1 },
  ];
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <ComposedChart margin={{ top: 8, right: 8, left: -16, bottom: 12 }}>
          <CartesianGrid stroke="#e2e8f0" />
          <XAxis
            type="number"
            dataKey="predicted"
            domain={[0, 1]}
            ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
            tickFormatter={(v) => `${Math.round(v * 100)}%`}
            tick={{ fontSize: 10 }}
            label={{ value: "예측 확률", position: "insideBottom", offset: -6, fontSize: 11 }}
          />
          <YAxis
            type="number"
            dataKey="observed"
            domain={[0, 1]}
            ticks={[0, 0.2, 0.4, 0.6, 0.8, 1]}
            tickFormatter={(v) => `${Math.round(v * 100)}%`}
            tick={{ fontSize: 10 }}
          />
          <Tooltip
            formatter={(v, name) => [`${(Number(v) * 100).toFixed(1)}%`, String(name)]}
            labelFormatter={() => ""}
          />
          <Legend verticalAlign="top" wrapperStyle={{ fontSize: 11, paddingBottom: 4 }} />
          <Line isAnimationActive={false} data={diagonal} dataKey="observed" name="완벽한 보정" stroke={SLATE} strokeDasharray="4 4" dot={false} />
          {series.map((s, i) => (
            <Line isAnimationActive={false} key={s.name} data={s.points} dataKey="observed" name={s.name} stroke={colors[i % 3]} strokeWidth={2} dot={{ r: 3 }} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
