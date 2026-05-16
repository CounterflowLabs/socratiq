"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Script from "next/script";

import { loginWithGoogle } from "@/lib/api";
import {
  consumeReturnPath,
  getAccessToken,
  setSession,
} from "@/lib/auth";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";

interface GoogleCredentialResponse {
  credential: string;
  select_by?: string;
}

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: GoogleCredentialResponse) => void;
            ux_mode?: "popup" | "redirect";
            auto_select?: boolean;
          }) => void;
          renderButton: (
            parent: HTMLElement,
            options: {
              type?: "standard" | "icon";
              theme?: "outline" | "filled_blue" | "filled_black";
              size?: "small" | "medium" | "large";
              shape?: "rectangular" | "pill" | "circle" | "square";
              width?: number;
              text?: "signin_with" | "signup_with" | "continue_with";
            }
          ) => void;
          prompt: () => void;
        };
      };
    };
  }
}

export default function LoginPage() {
  const router = useRouter();
  const buttonRef = useRef<HTMLDivElement>(null);
  const [gisReady, setGisReady] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (getAccessToken()) {
      const next = consumeReturnPath() ?? "/";
      router.replace(next);
    }
  }, [router]);

  useEffect(() => {
    if (!gisReady || !buttonRef.current || !GOOGLE_CLIENT_ID) return;

    const handleCredential = async (response: GoogleCredentialResponse) => {
      if (!response.credential) return;
      setSubmitting(true);
      setError(null);
      try {
        const result = await loginWithGoogle(response.credential);
        setSession(result.tokens, result.user);
        // If the user has no active subscription, send them to /redeem before
        // the dashboard would 402 anyway.
        const next = result.user.has_active_subscription
          ? consumeReturnPath() ?? "/"
          : "/redeem";
        router.replace(next);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "登录失败，请稍后再试。"
        );
        setSubmitting(false);
      }
    };

    window.google?.accounts.id.initialize({
      client_id: GOOGLE_CLIENT_ID,
      callback: handleCredential,
      ux_mode: "popup",
    });
    window.google?.accounts.id.renderButton(buttonRef.current, {
      theme: "outline",
      size: "large",
      shape: "pill",
      width: 280,
      text: "continue_with",
    });
  }, [gisReady, router]);

  const noClientId = !GOOGLE_CLIENT_ID;

  return (
    <>
      <Script
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onLoad={() => setGisReady(true)}
      />
      <main className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="w-full max-w-sm space-y-6 rounded-2xl border border-border bg-card p-8 shadow-sm">
          <header className="space-y-1 text-center">
            <h1 className="text-2xl font-semibold tracking-tight">
              Socratiq
            </h1>
            <p className="text-sm text-muted-foreground">
              用 Google 账号登录开始使用
            </p>
          </header>

          {noClientId ? (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
              未配置 <code>NEXT_PUBLIC_GOOGLE_CLIENT_ID</code>，登录暂不可用。
            </div>
          ) : (
            <div className="flex flex-col items-center gap-3">
              <div ref={buttonRef} aria-busy={submitting} />
              {submitting && (
                <p className="text-xs text-muted-foreground">登录中…</p>
              )}
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
        </div>
      </main>
    </>
  );
}
