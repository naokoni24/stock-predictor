"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";

type PricePoint = {
  date: string;
  close: number;
};

export default function PriceChart({ data }: { data: PricePoint[] }) {
  return (
    <div className="h-64 w-full rounded-lg border border-zinc-800 bg-zinc-900 p-2">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11 }}
            tickFormatter={(v: string) => v.slice(5)}
            minTickGap={20}
          />
          <YAxis
            domain={["auto", "auto"]}
            tick={{ fontSize: 11 }}
            width={60}
          />
          <Tooltip
            formatter={(value) => `${Number(value).toLocaleString()} 円`}
          />
          <Line
            type="monotone"
            dataKey="close"
            stroke="#71717a"
            strokeWidth={2}
            dot={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
