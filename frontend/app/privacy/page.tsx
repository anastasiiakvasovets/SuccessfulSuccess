import { HeaderAuth } from "@/components/header-auth"
import { SiteHeader } from "@/components/site-header"

export const metadata = {
  title: "Privacy policy — SuccessfulSuccess",
}

const CONTACT = "kvasovets.pn@ucu.edu.ua"

/** Static page: no auth, no data fetching, so the export writes privacy/index.html. */
export default function PrivacyPage() {
  return (
    <>
      <SiteHeader>
        <HeaderAuth />
      </SiteHeader>
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 pt-10 pb-16 sm:px-6 lg:px-8">
        <h1 className="text-3xl font-extrabold tracking-tight">Privacy policy</h1>
        <p className="text-muted-foreground mt-3 text-sm">
          SuccessfulSuccess is a student lab project, not a commercial service.
        </p>

        <div className="mt-8 grid gap-6 leading-relaxed">
          <section className="grid gap-2">
            <h2 className="text-lg font-bold">How you sign in</h2>
            <p>
              We use Amazon Cognito and Google sign-in only to identify you, so that you see your
              own meetings.
            </p>
          </section>

          <section className="grid gap-2">
            <h2 className="text-lg font-bold">What we store</h2>
            <ul className="list-disc space-y-1 pl-6">
              <li>your email address;</li>
              <li>your name;</li>
              <li>your Cognito user id.</li>
            </ul>
          </section>

          <section className="grid gap-2">
            <h2 className="text-lg font-bold">Sharing</h2>
            <p>We do not share your data with third parties.</p>
          </section>

          <section className="grid gap-2">
            <h2 className="text-lg font-bold">Contact</h2>
            <p>
              Questions or requests about your data:{" "}
              <a href={`mailto:${CONTACT}`} className="text-primary font-medium hover:underline">
                {CONTACT}
              </a>
              .
            </p>
          </section>
        </div>
      </main>
    </>
  )
}
