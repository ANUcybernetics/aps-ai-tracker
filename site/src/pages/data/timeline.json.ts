import type { APIRoute } from "astro";
import { provenance } from "@/lib/dataset";
import { getTimeline, meta } from "@/lib/load";

// Every observed change as a flat event list, newest first: the data behind
// the timeline page, classification and model-written summary included.
export const GET: APIRoute = async () => {
  const events = await getTimeline();
  return new Response(JSON.stringify({ dataset: "timeline", ...provenance(meta), events }), {
    headers: { "content-type": "application/json" },
  });
};
