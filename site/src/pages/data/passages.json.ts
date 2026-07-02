import type { APIRoute } from "astro";
import { propagation } from "@/lib/load";

// The propagation page's passage browser needs every cluster (so its search
// covers them all), but that's ~55 KB — too much to inline into the page HTML.
// Emit it as a static JSON file the island fetches on demand instead, mirroring
// how the similarity graph loads its data.
export const GET: APIRoute = () =>
  new Response(JSON.stringify({ clusters: propagation.clusters }), {
    headers: { "content-type": "application/json" },
  });
