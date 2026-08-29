import type { APIRoute } from "astro";
import { CSV_HEADER, agencyCsvRow, toCsv } from "@/lib/dataset";
import { getAgencies } from "@/lib/load";
import { getStatements } from "@/lib/statements";

// The flat spreadsheet view: one row per tracked agency (including those with
// no statement, so the coverage gaps are in the file), columns documented on
// /data/. List-valued profile fields are joined with "; ".
export const GET: APIRoute = async () => {
  const agencies = await getAgencies();
  const docs = await getStatements();
  const rows = agencies.map((a) =>
    agencyCsvRow(a, a.statementId ? docs[a.statementId] : undefined),
  );
  return new Response(toCsv(CSV_HEADER, rows), {
    headers: { "content-type": "text/csv; charset=utf-8" },
  });
};
