type Props = {
  title: string;
  message: string;
  hint?: string;
  testId?: string;
};

/** A readable error state for any failed API call (API down, 404, contract mismatch). */
export function ErrorNotice({ title, message, hint, testId = "error-notice" }: Props) {
  return (
    <div role="alert" data-testid={testId} className="rounded-lg border border-red-300 bg-red-50 p-5 text-sm text-red-900">
      <p className="font-semibold">
        <span aria-hidden="true">⚠ </span>
        {title}
      </p>
      <p className="mt-1 break-words">{message}</p>
      {hint ? <p className="mt-2 text-red-800">{hint}</p> : null}
    </div>
  );
}
