"use client";

import {
  Line,
  LineChart,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  ReferenceLine,
} from "recharts";

type ScorePoint = {
  date: string;
  ml_score: number | null;
};

export default function AiScoreHistoryChart({ data }: { data: ScorePoint[] }) {
  const chartData = data
    .filter((d) => d.ml_score != null)
    .map((d) => ({ date: d.date, score: Math.round((d.ml_score as number) * 100) }));

  return (
    <div className="h-48 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--color-border)" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
            tickFormatter={(d: string) => d.slice(5)}
            minTickGap={24}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 10, fill: "var(--color-muted-foreground)" }}
            tickFormatter={(v: number) => `${v}%`}
            width={40}
          />
          <ReferenceLine y={50} stroke="var(--color-muted-foreground)" strokeDasharray="3 3" />
          <Tooltip
            formatter={(value) => [`${value}%`, "上昇確率"]}
            contentStyle={{
              backgroundColor: "var(--color-card)",
              border: "1px solid var(--color-border)",
              borderRadius: "8px",
              fontSize: "12px",
            }}
          />
          <Line
            type="monotone"
            dataKey="score"
            stroke="var(--color-primary)"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
