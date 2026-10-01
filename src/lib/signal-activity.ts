export type DailySignal = {
  ticker: string;
  date: string;
  close: number | null;
  signal: string | null;
  ml_signal: string | null;
  ml_score: number | null;
  model_version: string | null;
  name?: string;
};

export const SIGNAL_LABELS: Record<string, string> = {
  buy_candidate: "買い候補",
  sell_candidate: "売り候補",
  hold: "様子見",
};

export function validPrice(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value) && value > 0;
}

export function signalChanges(current: DailySignal[], previous: DailySignal[]) {
  const before = new Map(previous.map((row) => [row.ticker, row]));
  return current.flatMap((row) => {
    const prev = before.get(row.ticker);
    // 分析対象の入れ替わり・価格欠損をシグナル変化と扱わない。
    if (!prev || !validPrice(row.close) || !validPrice(prev.close)) return [];
    const changes: string[] = [];
    for (const [label, oldValue, newValue] of [
      ["テクニカル", prev.signal, row.signal],
      ["AI", prev.ml_signal, row.ml_signal],
    ]) {
      if (
        oldValue &&
        newValue &&
        oldValue !== newValue &&
        SIGNAL_LABELS[oldValue] &&
        SIGNAL_LABELS[newValue]
      ) {
        changes.push(
          `${label}: ${SIGNAL_LABELS[oldValue]} → ${SIGNAL_LABELS[newValue]}`,
        );
      }
    }
    if (!changes.length) return [];
    const sameModel =
      !!row.model_version && row.model_version === prev.model_version;
    const scoreDelta =
      sameModel &&
      row.ml_score != null &&
      prev.ml_score != null &&
      Number.isFinite(row.ml_score) &&
      Number.isFinite(prev.ml_score)
        ? row.ml_score - prev.ml_score
        : null;
    return [
      {
        ...row,
        previous: prev,
        changes,
        scoreDelta,
        modelChanged: !!row.model_version && !!prev.model_version && !sameModel,
      },
    ];
  });
}

type ReviewInput = {
  close: number | null;
  costPrice: number;
  priceDate: string | null;
  latestDate: string | null;
  current: DailySignal | null;
  previous: DailySignal | null;
};

/** 確認順を決めるためのルール。売買指示ではなく、理由をそのまま表示する。 */
export function holdingReview(input: ReviewInput) {
  const reasons: string[] = [];
  let priority = 0;
  const { close, costPrice, priceDate, latestDate, current, previous } = input;
  const freshPrice =
    validPrice(close) && !!latestDate && priceDate === latestDate;
  const distance =
    validPrice(close) && validPrice(costPrice)
      ? ((close - costPrice * 0.92) / close) * 100
      : null;
  if (!freshPrice) {
    reasons.push("価格が未取得・更新待ち");
    priority = 80;
  }
  if (freshPrice && distance != null) {
    if (distance <= 0) {
      reasons.push("取得単価−8%の損切り目安に到達");
      priority = 100;
    } else if (distance <= 3) {
      reasons.push(`損切り目安まであと${distance.toFixed(1)}%の下落`);
      priority = 70;
    }
  }
  if (!current || current.date !== latestDate || !validPrice(current.close)) {
    reasons.push("シグナルが更新待ち");
    priority = Math.max(priority, 80);
  } else {
    if (current.signal === "sell_candidate") {
      reasons.push("テクニカルが売り候補");
      priority = Math.max(priority, 90);
    }
    if (
      previous?.model_version &&
      previous.model_version === current.model_version &&
      current.ml_score != null &&
      previous.ml_score != null &&
      Number.isFinite(current.ml_score) &&
      Number.isFinite(previous.ml_score) &&
      previous.ml_score - current.ml_score >= 0.1 - 1e-9
    ) {
      reasons.push("AI相対スコアが前回より0.10以上低下");
      priority = Math.max(priority, 60);
    }
    if (current.ml_signal === "hold") {
      reasons.push("AIの買い条件を満たしていません");
      priority = Math.max(priority, 20);
    }
  }
  if (!reasons.length) reasons.push("現在の確認条件に該当なし");
  return {
    priority,
    reasons,
    distance,
    label:
      priority >= 90
        ? "優先確認"
        : priority >= 80
          ? "更新確認"
          : priority >= 60
            ? "注意"
            : "通常",
  };
}

export type WatchRule = {
  price_above: number | null;
  price_below: number | null;
  signal_alert: boolean;
  created_at: string;
};

export function watchAlerts(
  rule: WatchRule,
  price: { close: number | null; date: string } | null,
  current: DailySignal | null,
  previous: DailySignal | null,
  latestDate: string | null,
) {
  const alerts: string[] = [];
  if (price && price.date === latestDate && validPrice(price.close)) {
    if (validPrice(rule.price_above) && price.close >= rule.price_above)
      alerts.push(`終値が上限 ¥${rule.price_above.toLocaleString()} 以上`);
    if (validPrice(rule.price_below) && price.close <= rule.price_below)
      alerts.push(`終値が下限 ¥${rule.price_below.toLocaleString()} 以下`);
  }
  // 登録以前の変化は通知しない。比較日が登録日以降なら、日次更新の変化を表示する。
  const createdDate = new Date(rule.created_at).toLocaleDateString("sv-SE", {
    timeZone: "Asia/Tokyo",
  });
  if (
    rule.signal_alert &&
    current?.date === latestDate &&
    previous &&
    previous.date >= createdDate
  ) {
    const change = signalChanges([current], [previous])[0];
    if (change) alerts.push(...change.changes);
  }
  return alerts;
}

export function parseWatchPrices(above: string, below: string) {
  const parse = (value: string) => (value.trim() ? Number(value) : null);
  const price_above = parse(above),
    price_below = parse(below);
  if (
    (price_above != null && (!validPrice(price_above) || price_above > 1e12)) ||
    (price_below != null && (!validPrice(price_below) || price_below > 1e12))
  ) {
    return { error: "価格は0より大きい有限の数値で入力してください。" };
  }
  if (
    price_above != null &&
    price_below != null &&
    price_below >= price_above
  ) {
    return { error: "下限価格は上限価格より小さくしてください。" };
  }
  return { price_above, price_below };
}
