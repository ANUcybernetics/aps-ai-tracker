import type { APIRoute } from "astro";
import { similarity, getAgencies } from "@/lib/load";
import type { GraphData } from "@/types/exporter";

// The D3 island fetches the graph at runtime, so emit it as a static JSON file
// — assembled here from the zod-validated similarity + agency data, rather than
// shipped as a separate exporter artifact that could go missing or stale
// independently of the data the rest of the site is built from.
export const GET: APIRoute = async () => {
  const agencies = await getAgencies();
  const byAbbr = new Map(agencies.map((a) => [a.abbr, a]));
  const graph: GraphData = {
    nodes: similarity.abbrs.map((abbr) => ({
      id: abbr,
      abbr,
      size: byAbbr.get(abbr)?.size ?? "unknown",
      originality: byAbbr.get(abbr)?.originality ?? 0,
    })),
    edges: similarity.edges,
  };
  return new Response(JSON.stringify(graph), {
    headers: { "content-type": "application/json" },
  });
};
