"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import {
  getCurrentUser,
  getSubscriptionStatus,
  redeemActivationCode,
  type SubscriptionStatus,
} from "@/lib/api";
import {
  consumeReturnPath,
  getAccessToken,
  redirectToLogin,
  setStoredUser,
} from "@/lib/auth";

function formatExpiry(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export default function RedeemPage() {
  const router = useRouter();
  const [bootstrapping, setBootstrapping] = useState(true);
  const [status, setStatus] = useState<SubscriptionStatus | null>(null);
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!getAccessToken()) {
      redirectToLogin();
      return;
    }
    (async () => {
      try {
        const s = await getSubscriptionStatus();
        setStatus(s);
      } catch (err) {
        setError(err instanceof Error ? err.message : "无法读取订阅状态");
      } finally {
        setBootstrapping(false);
      }
    })();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await redeemActivationCode(code.trim());
      setSuccess(
        `兑换成功！套餐 ${result.tier}，可用至 ${formatExpiry(result.subscription_until)}`
      );
      setStatus({
        has_active_subscription: true,
        subscription_until: result.subscription_until,
        monthly_usd_cap: result.monthly_usd_cap,
        tier: result.tier,
      });
      try {
        const me = await getCurrentUser();
        setStoredUser(me);
      } catch {
        // non-fatal
      }
      setCode("");
      // Land back where the user was bounced from (if anywhere), shortly after.
      const next = consumeReturnPath();
      setTimeout(() => {
        router.replace(next ?? "/");
      }, 1200);
    } catch (err) {
      setError(err instanceof Error ? err.message : "兑换失败");
      setSubmitting(false);
    }
  };

  const active = status?.has_active_subscription === true;

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md space-y-6 rounded-2xl border border-border bg-card p-8 shadow-sm">
        <header className="space-y-1 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">兑换激活码</h1>
          <p className="text-sm text-muted-foreground">
            输入你购买或收到的激活码，开通访问权限
          </p>
        </header>

        {bootstrapping ? (
          <p className="text-center text-sm text-muted-foreground">
            正在读取订阅状态…
          </p>
        ) : (
          <>
            {status && (
              <div className="rounded-md border border-border bg-muted/40 p-3 text-sm">
                <p>
                  当前状态：
                  <span className={active ? "text-emerald-600 font-medium" : "text-muted-foreground"}>
                    {active ? "已激活" : "未激活"}
                  </span>
                </p>
                {status.tier && <p>套餐：{status.tier}</p>}
                {status.subscription_until && (
                  <p>有效期至：{formatExpiry(status.subscription_until)}</p>
                )}
                {status.monthly_usd_cap != null && (
                  <p>月度额度：${status.monthly_usd_cap.toFixed(2)}</p>
                )}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-3">
              <label className="block text-sm font-medium" htmlFor="code">
                激活码
              </label>
              <input
                id="code"
                type="text"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="SCQ-XXXX-XXXX-XXXX"
                autoComplete="off"
                spellCheck={false}
                className="w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm tracking-widest uppercase shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <button
                type="submit"
                disabled={submitting || !code.trim()}
                className="w-full rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground shadow-sm hover:opacity-90 disabled:opacity-50"
              >
                {submitting ? "兑换中…" : active ? "继续叠加" : "立即兑换"}
              </button>
            </form>

            {success && (
              <div
                role="status"
                className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900"
              >
                {success}
              </div>
            )}
            {error && (
              <div
                role="alert"
                className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
              >
                {error}
              </div>
            )}

            {!active && (
              <p className="text-center text-xs text-muted-foreground">
                还没有激活码？联系运营或访问购买页购买后回到此页面兑换。
              </p>
            )}
          </>
        )}
      </div>
    </main>
  );
}
