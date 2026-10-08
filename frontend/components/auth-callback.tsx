"use client"

import { Hub } from "aws-amplify/utils"
import { AlertCircle } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useEffect, useState } from "react"

import { useAuth } from "@/components/auth-provider"
import { AuthLoading } from "@/components/require-auth"
import { SiteHeader } from "@/components/site-header"
import { Button } from "@/components/ui/button"

/** Cognito reports a refused sign-in as ?error=...&error_description=... */
function errorFromUrl(): string | null {
  const params = new URLSearchParams(window.location.search)
  const error = params.get("error_description") ?? params.get("error")
  if (error) return error
  if (!params.get("code")) return "There is no sign-in to finish here. Start again from the login page."
  return null
}

/**
 * Amplify's OAuth listener (imported by lib/auth) swaps ?code for tokens as soon
 * as the auth provider configures Amplify; this page only waits for the outcome.
 */
export function AuthCallback() {
  const { status } = useAuth()
  const router = useRouter()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Read once on load, before Amplify cleans ?code&state out of the URL. The
    // effect runs before the provider's (children first), so no event is missed.
    // eslint-disable-next-line react-hooks/set-state-in-effect -- window only exists in the browser
    setError(errorFromUrl())
    return Hub.listen("auth", ({ payload }) => {
      if (payload.event === "signInWithRedirect_failure") {
        setError(payload.data?.error?.message || "Sign-in failed. Please try again.")
      }
    })
  }, [])

  useEffect(() => {
    if (status === "signedIn") router.replace("/today/")
  }, [status, router])

  return (
    <>
      <SiteHeader />
      {error && status !== "signedIn" ? (
        <main className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-6 px-4 py-24 text-center">
          <div
            role="alert"
            className="bg-destructive/10 text-destructive flex items-start gap-2 rounded-2xl px-4 py-3 text-left text-sm"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>{error}</span>
          </div>
          <Button asChild>
            <Link href="/login/">Back to log in</Link>
          </Button>
        </main>
      ) : (
        <AuthLoading label="Signing in…" />
      )}
    </>
  )
}
