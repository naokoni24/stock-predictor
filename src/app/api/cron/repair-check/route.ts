import { NextRequest, NextResponse } from "next/server";

/**
 * GitHub Actions(daily-signals.yml)の日次スケジュール実行が大幅に遅延・未発火の
 * ときだけ、修復モード(REPAIR_MISSING_CLOSES_ONLY)でworkflow_dispatchを起動する。
 *
 * 15:30 JSTの本実行・17:00 JSTの修復実行はどちらもGitHub Actionsの`schedule`
 * イベントに依存しており、GitHub側のスケジュール配送遅延には対処できない
 * (GitHub公式もscheduled workflowが高負荷時に遅延・欠落しうると案内している)。
 * このAPIはVercel Cron(vercel.jsonで17:45 JST頃・19:00 JST頃の2回に設定、
 * 2026-09-04に17:45を追加して二段構成化)から呼び出され、GitHub Actions基盤
 * とは独立した経路でフェイルセーフとして機能する。
 * 1回目(17:45)は17:00修復実行の想定遅延を見込んだ早期検知、2回目(19:00)は
 * 1回目のVercel Cron自体が飛んだ場合の最終保険。判定ロジックが冪等
 * (queued/in_progress/success済みなら何もしない)なので、2本立てても
 * 正規の実行と競合しない。
 *
 * 判定ロジック(2026-09-03):
 * - 本日(JST)分のdaily-signals実行が既にqueued/in_progressなら何もしない。
 * - 本日(JST)分のdaily-signals実行が既にsuccessで完了していれば何もしない。
 * - どちらにも該当しない(=本日分の実行が1件も無い、または失敗のみ)場合だけ、
 *   修復モードでworkflow_dispatchを起動する。
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
  html_url: string;
};

/** JST基準の「今日0時」をUTCのISO文字列で返す(JSTはUTC+9固定、サマータイムなし)。 */
function startOfTodayJstAsUtcIso(): string {
  const now = new Date();
  const jstNow = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const y = jstNow.getUTCFullYear();
  const m = jstNow.getUTCMonth();
  const d = jstNow.getUTCDate();
  const startOfTodayJstUtcMs = Date.UTC(y, m, d, 0, 0, 0) - 9 * 60 * 60 * 1000;
  return new Date(startOfTodayJstUtcMs).toISOString();
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

  const todayStartIso = startOfTodayJstAsUtcIso();
  const todaysRuns = runs.filter((r) => r.created_at >= todayStartIso);

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
    reason: "no successful run found for today",
    todaysRunsChecked: todaysRuns.length,
  });
}
