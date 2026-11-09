import { DOC_TYPES } from "@echr/contract";
import { CHUNK_STRATEGIES, labHref, type LabParams } from "../lab-model";

const input =
  "rounded-md border border-stone-300 bg-white px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-sky-600";

export function LabForm({ params }: { params: LabParams }) {
  return (
    <form action="/lab" method="get" className="mt-6 rounded-lg border border-stone-200 bg-white p-4" data-testid="lab-form">
      <div className="flex flex-col gap-1">
        <label htmlFor="lab-q" className="text-sm font-medium">
          Question
        </label>
        <input
          id="lab-q"
          name="q"
          type="text"
          defaultValue={params.q}
          maxLength={500}
          required
          className={input}
          data-testid="lab-query"
        />
      </div>
      <div className="mt-3 flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-1">
          <label htmlFor="lab-chunking" className="text-sm font-medium">
            Chunking strategy
          </label>
          <select id="lab-chunking" name="chunking" defaultValue={params.chunking} className={input} data-testid="lab-chunking">
            {CHUNK_STRATEGIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="lab-k" className="text-sm font-medium">
            Hits per column (k)
          </label>
          <input id="lab-k" name="k" type="number" min={1} max={50} defaultValue={params.k} className={`${input} w-24`} data-testid="lab-k" />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="lab-article" className="text-sm font-medium">
            Article (optional)
          </label>
          <input
            id="lab-article"
            name="article"
            type="text"
            placeholder="e.g. 8"
            defaultValue={params.article ?? ""}
            maxLength={10}
            className={`${input} w-28`}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="lab-doctype" className="text-sm font-medium">
            Document type (optional)
          </label>
          <select id="lab-doctype" name="doc_type" defaultValue={params.docType ?? ""} className={input}>
            <option value="">any</option>
            {DOC_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          className="rounded-md bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-sky-600"
          data-testid="lab-submit"
        >
          Run all four
        </button>
        <a href={labHref(params)} className="text-xs text-stone-500 underline" data-testid="lab-share">
          Link to this exact view
        </a>
      </div>
    </form>
  );
}
