import type { APIRoute } from "astro";
import { publicStatement, provenance } from "@/lib/dataset";
import { getAgencies, meta } from "@/lib/load";
import { getStatements } from "@/lib/statements";

// The full per-statement dataset: roster row + current profile + Standard
// report card + currency + every revision's classification, summary and
// profile deltas. Bodies are excluded; see /data/ for where they live.
export const GET: APIRoute = async () => {
  const agencies = await getAgencies();
  const docs = await getStatements();
  const statements = agencies.flatMap((a) => {
    const doc = a.statementId ? docs[a.statementId] : undefined;
    return doc ? [publicStatement(a, doc)] : [];
  });
  return new Response(JSON.stringify({ dataset: "statements", ...provenance(meta), statements }), {
    headers: { "content-type": "application/json" },
  });
};
