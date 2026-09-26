import { NextRequest, NextResponse } from "next/server";

/**
 * GitHub Actions(daily-signals.yml)の日次スケジュール実行が大幅に遅延・未発火の
 * ときだけ、修復モード(REPAIR_MISSING_CLOSES_ONLY)でworkflow_dispatchを起動する。
 *
 * 11:07 JSTの本実行・13:07 JSTの修復実行(2026-09-07に前倒し、2026-09-26にさらに30分前倒し。実測では4〜6時間遅れて
 * 16〜19時台に発火している)はどちらもGitHub Actionsの`schedule`イベントに依存しており、GitHub側のスケジュール配送遅延には対処できない
 * (GitHub公式もscheduled workflowが高負荷時に遅延・欠落しうると案内しており、
 * 特に毎時ちょうど等キリの良い時刻は混雑しやすいと明記している。2026-09-04に
 * 本実行:30・修復実行:00がどちらも未発火する事象が発生したため、daily-signals.yml
 * 側のcron分も:30/:00から:37/:12へ変更した)。
 * このAPIはVercel Cron(vercel.jsonで17:52 JST頃・19:07 JST頃の2回に設定、
 * 2026-09-04に17:45を追加して二段構成化、同日中に:45/:00→:52/:07へ再調整)
 * から呼び出され、GitHub Actions基盤とは独立した経路でフェイルセーフとして
 * 機能する。
 * 1回目(17:52)は本実行・修復実行の想定遅延を見込んだ早期検知、2回目(19:07)は
 * 1回目のVercel Cron自体が飛んだ場合の最終保険。判定ロジックが冪等
 * (queued/in_progress/success済みなら何もしない)なので、2本立てても
 * 正規の実行と競合しない。
 *
 * 2026-09-04時点ではcron分の調整が実際に発火安定性を改善するかは未検証。
 * 2026-09-08週以降の実行実績(gh run list)を見て、必要ならさらに調整する。
 *
 * 判定ロジック(2026-09-03、2026-09-26修正):
 * - 本日(JST)の取引終了(15:00 JST)以降に開始したdaily-signals実行だけを数える。
 *   取引終了前に開始した実行は当日分を除外して前営業日までしか処理しないため
 *   (scripts/fetch_and_signal.pyのMARKET_CLOSE_HOUR_JST)、それを「成功済み」と
 *   みなすと当日終値が翌日まで反映されない。スケジュール遅延が縮まり11:07/13:07に
 *   定刻発火した日にこの状態になるため、以前の「本日0時以降」基準から変更した。
 * - 上記の実行が既にqueued/in_progressなら何もしない。
 * - 上記の実行が既にsuccessで完了していれば何もしない。
 * - どちらにも該当しない場合だけ、修復モードでworkflow_dispatchを起動する。
 *   当日のシグナルが未保存ならスクリプト側で通常モードへ切り替わる。
 *
 * データ欠損の妥当性検証自体はscripts/fetch_and_signal.py側(代表4銘柄の
 * 終値チェック)が既に行っており、取引日なのに欠損していればジョブがfailする
 * ため、ここでは「実行されたかどうか」だけを見ればよい。
 */

export const dynamic = "force-dynamic";

const OWNER = "naokoni24";
const REPO = "stock-predictor";
const WORKFLOW_FILE = "daily-signals.yml";
const REF = "main";

type WorkflowRun = {
  status: string; // "queued" | "in_progress" | "completed" など
  conclusion: string | null;
  created_at: string;
  run_started_at?: string | null;
  html_url: string;
};

// 東証の取引終了時刻(JST)。scripts/fetch_and_signal.pyのMARKET_CLOSE_HOUR_JSTと同じ値。
const MARKET_CLOSE_HOUR_JST = 15;

/** JST基準の「今日の取引終了時刻」をUTCのISO文字列で返す(JSTはUTC+9固定、サマータイムなし)。 */
function todayMarketCloseJstAsUtcIso(): string {
  const now = new Date();
  const jstNow = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const y = jstNow.getUTCFullYear();
  const m = jstNow.getUTCMonth();
  const d = jstNow.getUTCDate();
  const closeJstUtcMs = Date.UTC(y, m, d, MARKET_CLOSE_HOUR_JST, 0, 0) - 9 * 60 * 60 * 1000;
  return new Date(closeJstUtcMs).toISOString();
}

function githubHeaders(token: string) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
  };
}

export async function GET(req: NextRequest) {
  const cronSecret = process.env.CRON_SECRET;
  const authHeader = req.headers.get("authorization");
  if (!cronSecret || authHeader !== `Bearer ${cronSecret}`) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  const githubToken = process.env.GITHUB_ACTIONS_TOKEN;
  if (!githubToken) {
    return NextResponse.json(
      { error: "GITHUB_ACTIONS_TOKEN is not configured" },
      { status: 500 }
    );
  }

  const runsRes = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/runs?per_page=10`,
    { headers: githubHeaders(githubToken), cache: "no-store" }
  );
  if (!runsRes.ok) {
    const detail = await runsRes.text();
    return NextResponse.json(
      { error: "failed to list workflow runs", detail },
      { status: 502 }
    );
  }

  const { workflow_runs: runs } = (await runsRes.json()) as {
    workflow_runs: WorkflowRun[];
  };

  // 取引終了後に開始した実行だけが当日終値を処理できる。queuedの実行は開始前のため
  // run_started_atが無い(または作成時刻と同じ)場合があり、その場合はcreated_atで判定する。
  const marketCloseIso = todayMarketCloseJstAsUtcIso();
  const todaysRuns = runs.filter(
    (r) => (r.run_started_at ?? r.created_at) >= marketCloseIso
  );

  const inFlight = todaysRuns.find(
    (r) => r.status === "queued" || r.status === "in_progress"
  );
  if (inFlight) {
    return NextResponse.json({
      action: "skip",
      reason: "already running",
      run: inFlight.html_url,
    });
  }

  const succeeded = todaysRuns.find(
    (r) => r.status === "completed" && r.conclusion === "success"
  );
  if (succeeded) {
    return NextResponse.json({
      action: "skip",
      reason: "already succeeded today",
      run: succeeded.html_url,
    });
  }

  const dispatchRes = await fetch(
    `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    {
      method: "POST",
      headers: {
        ...githubHeaders(githubToken),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: REF, inputs: { repair_only: "1" } }),
    }
  );
  if (!dispatchRes.ok) {
    const detail = await dispatchRes.text();
    return NextResponse.json(
      { error: "failed to dispatch workflow", detail },
      { status: 502 }
    );
  }

  return NextResponse.json({
    action: "dispatched",
    reason: "no successful run found after today's market close",
    todaysRunsChecked: todaysRuns.length,
  });
}
