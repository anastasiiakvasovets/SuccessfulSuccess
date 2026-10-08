import Link from "next/link"

/** Shared bottom bar, rendered once in the root layout so every page has it. */
export function SiteFooter() {
  return (
    <footer className="mt-auto border-t">
      <div className="text-muted-foreground mx-auto flex h-14 max-w-6xl items-center justify-between gap-3 px-4 text-sm sm:px-6 lg:px-8">
        <span>SuccessfulSuccess</span>
        <Link href="/privacy/" className="hover:text-foreground font-medium hover:underline">
          Privacy policy
        </Link>
      </div>
    </footer>
  )
}
