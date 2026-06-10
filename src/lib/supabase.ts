import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!;

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

export type Signal = {
  ticker: string;
  date: string;
  close: number;
  sma25: number | null;
  sma75: number | null;
  rsi14: number | null;
  signal: string | null;
  score: number | null;
  stocks?: { name: string };
};

export type Holding = {
  id: number;
  ticker: string;
  shares: number;
  cost_price: number;
  stocks?: { name: string };
};
