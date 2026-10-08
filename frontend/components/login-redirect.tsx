"use client"

import { signInWithRedirect } from "aws-amplify/auth"
import { AlertCircle } from "lucide-react"
import { useRouter } from "next/navigation"
import { useEffect, useRef, useState } from "react"

import { useAuth } from "@/components/auth-provider"
import { AuthLoading } from "@/components/require-auth"
import { SiteHeader } from "@/components/site-header"
import { authErrorMessage, configureAuth, isAuthConfigured } from "@/lib/auth"

/**
 * Sends the browser to Cognito's managed login page (email + password, sign-up
 * and "Continue with Google"); Cognito brings it back to /auth/callback/.
 */
export function LoginRedirect() {
  const { status } = useAuth()
  const router = useRouter()
  const [error, setError] = useState<string | null>(
    isAuthConfigured ? null : "Sign-in isn't configured on this deployment.",
  )
  // StrictMode runs effects twice in dev; a second redirect would start a new
  // OAuth flow and overwrite the first one's state.
  const started = useRef(false)

  useEffect(() => {
    if (status === "loading" || !isAuthConfigured || started.current) return
    started.current = true
    if (status === "signedIn") {
      router.replace("/today/")
      return
    }
    configureAuth()
    signInWithRedirect().catch((caught: unknown) => {
      if (caught instanceof Error && caught.name === "UserAlreadyAuthenticatedException") {
        router.replace("/today/")
      } else {
        setError(authErrorMessage(caught))
      }
    })
  }, [status, router])

  return (
    <>
      <SiteHeader />
      {error ? (
        <main className="mx-auto flex w-full max-w-md flex-1 items-center justify-center px-4 py-24">
          <div
            role="alert"
            className="bg-destructive/10 text-destructive flex items-start gap-2 rounded-2xl px-4 py-3 text-sm"
          >
            <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>{error}</span>
          </div>
        </main>
      ) : (
        <AuthLoading label="Redirecting to sign in…" />
      )}
    </>
  )
}
