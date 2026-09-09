import type { APIRoute } from "astro";
import { PUBLICATION_URI } from "@/lib/atproto-ids";

// Points Standard-lexicon consumers at the publication record backing this
// site. Generated rather than a public/ file because the rkey is a TID
// allocated by scripts/atproto-publish.ts, not a constant.
export const GET: APIRoute = () =>
  new Response(PUBLICATION_URI ? `${PUBLICATION_URI}\n` : "", {
    status: PUBLICATION_URI ? 200 : 404,
    headers: { "content-type": "text/plain; charset=utf-8" },
  });
