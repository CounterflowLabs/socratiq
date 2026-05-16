import { redirect } from "next/navigation";

// SaaS mode: LLM providers are managed by the platform, so the setup flow is
// hidden. Admins manage providers via env vars + `seed_platform_models`.
export default function SetupPage() {
  redirect("/");
}
