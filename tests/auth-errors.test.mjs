import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import ts from "typescript";
function load(path) {
  const code = ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const loaded = { exports: {} };
  new Function("exports", "module", "console", code)(loaded.exports, loaded, { error() {} });
  return loaded.exports;
}
const { authErrorMessage } = load("../src/lib/auth-errors.ts");

test("Supabaseの英語エラーを日本語の案内に置き換え、想定外は原文を出さない", () => {
  const fallback = "ログインできませんでした。";
  assert.match(authErrorMessage({ code: "invalid_credentials", message: "Invalid login credentials" }, fallback), /パスワードが正しくありません/);
  assert.match(authErrorMessage({ message: "Invalid login credentials" }, fallback), /パスワードが正しくありません/);
  assert.match(authErrorMessage({ name: "AuthSessionMissingError", message: "Auth session missing!" }, fallback), /同じブラウザ/);
  assert.match(authErrorMessage({ code: "over_email_send_rate_limit" }, fallback), /上限/);
  assert.match(authErrorMessage({ message: "For security purposes, you can only request this after 30 seconds." }, fallback), /しばらく待って/);
  assert.equal(authErrorMessage({ code: "unexpected_failure", message: "Database error" }, fallback), fallback);
  for (const result of [authErrorMessage({ code: "same_password" }, fallback), authErrorMessage({ code: "weak_password" }, fallback)]) {
    assert.doesNotMatch(result, /[A-Za-z]{4,}/);
  }
});
