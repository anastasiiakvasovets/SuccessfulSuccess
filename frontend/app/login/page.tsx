import { LoginRedirect } from "@/components/login-redirect"

export const metadata = {
  title: "Log in — SuccessfulSuccess",
}

/** Straight on to Cognito's managed login (exported as login/index.html). */
export default function LoginPage() {
  return <LoginRedirect />
}
