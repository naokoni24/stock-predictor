"use client";

import {
  Bar,
  BarChart,
  ComposedChart,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
} from "recharts";

type PricePoint = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

const BULLISH = "var(--color-bullish)";
const BEARISH = "var(--color-bearish)";

type CandleProps = {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: PricePoint;
};

function Candle({ x, y, width, height, payload }: CandleProps) {
  if (x == null || y == null || width == null || height == null || !payload) return null;

  const { open, close, high, low } = payload;
  const isUp = close >= open;
  const color = isUp ? BULLISH : BEARISH;
  const range = high - low || 1;

  // y/height represent the [low, high] range; derive the open/close body within it
  const bodyTopValue = Math.max(open, close);
  const bodyBottomValue = Math.min(open, close);
  const bodyTop = y + ((high - bodyTopValue) / range) * height;
  const bodyHeight = Math.max(((bodyTopValue - bodyBottomValue) / range) * height, 1);

  const center = x + width / 2;

  return (
    <g>
      <line x1={center} x2={center} y1={y} y2={y + height} stroke={color} strokeWidth={1} />
      <rect x={x} y={bodyTop} width={width} height={bodyHeight} fill={color} rx={1} />
    </g>
  );
}

export default function CandlestickChart({ data }: { data: PricePoint[] }) {
  const chartData = data.map((d) => ({ ...d, range: [d.low, d.high] }));
  const closes = data.map((d) => d.close).filter((v) => v != null);
  const lows = data.map((d) => d.low ?? d.close);
  const highs = data.map((d) => d.high ?? d.close);
  const min = Math.min(...lows, ...closes);
  const max = Math.max(...highs, ...closes);
  const pad = (max - min) * 0.05 || 1;

  return (
    <div className="flex flex-col gap-2">
      <div className="h-72 w-full rounded-xl border border-border bg-card p-3">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11 }}
              tickFormatter={(v: string) => v.slice(5)}
              minTickGap={24}
            />
            <YAxis
              domain={[min - pad, max + pad]}
              tick={{ fontSize: 11 }}
              width={56}
              tickFormatter={(v: number) => v.toLocaleString()}
            />
            <Tooltip
              content={({ active, payload, label }) => {
                if (!active || !payload?.length) return null;
                const d = payload[0].payload as PricePoint;
                return (
                  <div className="rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-md">
                    <p className="font-medium mb-1">{label}</p>
                    <p>始値 {d.open?.toLocaleString()}</p>
                    <p>高値 {d.high?.toLocaleString()}</p>
                    <p>安値 {d.low?.toLocaleString()}</p>
                    <p>終値 {d.close?.toLocaleString()}</p>
                  </div>
                );
              }}
            />
            <Bar dataKey="range" shape={Candle as never} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <div className="h-20 w-full rounded-xl border border-border bg-card p-3">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
            <XAxis dataKey="date" hide />
            <YAxis hide />
            <Tooltip
              formatter={(value) => [Number(value).toLocaleString(), "出来高"]}
            />
            <Bar dataKey="volume" radius={[2, 2, 0, 0]} isAnimationActive={false}>
              {chartData.map((d, i) => (
                <Cell key={i} fill={d.close >= d.open ? BULLISH : BEARISH} opacity={0.5} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
