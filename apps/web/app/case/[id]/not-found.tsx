import Link from "next/link";
import { ErrorNotice } from "@/components/error-notice";

export default function CaseNotFound() {
  return (
    <main className="mx-auto max-w-3xl space-y-4 px-6 py-10">
      <ErrorNotice
        testId="case-error"
        title="No case with that id"
        message="The corpus has no case or document with the id in this address."
        hint="The id may be mistyped, or the case is not in the corpus."
      />
      <p className="text-sm">
        <Link href="/ask" className="underline underline-offset-2">Back to Ask</Link>
      </p>
    </main>
  );
}
