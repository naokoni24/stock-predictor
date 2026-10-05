// Supabase Authのエラーは英語のまま返るため、画面には日本語の案内を表示する。
// 想定外のエラーは原文を画面に出さず、サーバーログ(console.error)にだけ残す。
type AuthErrorLike = {
  code?: string | null;
  name?: string | null;
  message?: string | null;
};

const AUTH_ERROR_MESSAGES: Record<string, string> = {
  invalid_credentials: "メールアドレスまたはパスワードが正しくありません。",
  email_not_confirmed: "メールアドレスの確認が完了していません。届いた確認メールのリンクを開いてください。",
  user_banned: "このアカウントは利用できません。",
  over_request_rate_limit: "試行回数が多すぎます。しばらく待ってから再度お試しください。",
  over_email_send_rate_limit: "メールの送信回数が上限に達しました。しばらく待ってから再度お試しください。",
  weak_password: "パスワードが短すぎるか、推測されやすいものです。別のパスワードにしてください。",
  same_password: "新しいパスワードは現在のパスワードと異なるものにしてください。",
  session_not_found: "再設定リンクの有効期限が切れています。もう一度、再設定メールを送信してください。",
  session_expired: "再設定リンクの有効期限が切れています。もう一度、再設定メールを送信してください。",
  otp_expired: "再設定リンクの有効期限が切れています。もう一度、再設定メールを送信してください。",
  flow_state_expired: "再設定リンクの有効期限が切れています。もう一度、再設定メールを送信してください。",
  flow_state_not_found: "再設定リンクを確認できませんでした。再設定メールを送信したのと同じブラウザで開いてください。",
  bad_code_verifier: "再設定リンクを確認できませんでした。再設定メールを送信したのと同じブラウザで開いてください。",
  validation_failed: "入力内容を確認してください。",
};

export function authErrorMessage(error: AuthErrorLike, fallback: string): string {
  if (error.code && AUTH_ERROR_MESSAGES[error.code]) return AUTH_ERROR_MESSAGES[error.code];
  if (error.name === "AuthSessionMissingError") {
    return "再設定リンクの有効期限が切れたか、別のブラウザで開かれています。再設定メールを送信したのと同じブラウザで、もう一度お試しください。";
  }
  // コードを持たない古い形式のエラー
  const message = error.message ?? "";
  if (/invalid login credentials/i.test(message)) return AUTH_ERROR_MESSAGES.invalid_credentials;
  if (/rate limit|security purposes/i.test(message)) return AUTH_ERROR_MESSAGES.over_request_rate_limit;
  if (/password should be/i.test(message)) return AUTH_ERROR_MESSAGES.weak_password;
  console.error("認証エラー:", error.code ?? error.name ?? "", message);
  return fallback;
}
