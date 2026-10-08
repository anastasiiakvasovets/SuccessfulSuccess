"use client"

import Link from "next/link"
import { toast } from "sonner"

import { useAuth } from "@/components/auth-provider"
import { Button } from "@/components/ui/button"
import { authErrorMessage, isAuthConfigured, isGoogleConfigured, signInWithGoogle } from "@/lib/auth"

/** Header actions for public pages: sign-in buttons, or who is signed in. */
export function HeaderAuth() {
  const { status, user, signOut } = useAuth()
  if (!isAuthConfigured || status === "loading") return null

  if (status === "signedIn") {
    return (
      <div className="ml-auto flex items-center gap-3">
        <span className="text-muted-foreground hidden truncate text-sm sm:inline">{user.email}</span>
        <Button variant="outline" size="sm" onClick={() => void signOut()}>
          Sign out
        </Button>
      </div>
    )
  }

  return (
    <div className="ml-auto flex items-center gap-2">
      {isGoogleConfigured ? (
        <Button
          variant="outline"
          size="sm"
          onClick={() => signInWithGoogle().catch((error) => toast.error(authErrorMessage(error)))}
        >
          Sign in with Google
        </Button>
      ) : null}
      <Button asChild size="sm">
        <Link href="/login/">Sign in</Link>
      </Button>
    </div>
  )
}
