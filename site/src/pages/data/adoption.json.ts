import type { APIRoute } from "astro";
import { provenance } from "@/lib/dataset";
import { adoption, meta } from "@/lib/load";

// The monthly concept-adoption series behind the policy page's charts, plus
// every agency-level transition (concept gained or lost, with the revision sha).
export const GET: APIRoute = () =>
  new Response(JSON.stringify({ dataset: "adoption", ...provenance(meta), ...adoption }), {
    headers: { "content-type": "application/json" },
  });
