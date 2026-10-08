import { AuthCallback } from "@/components/auth-callback"

export const metadata = {
  title: "Signing in — SuccessfulSuccess",
}

/** Where Cognito sends the browser back after Google sign-in (auth/callback/index.html). */
export default function AuthCallbackPage() {
  return <AuthCallback />
}
