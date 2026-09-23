import type { APIRoute } from "astro";
import { getPublishedNews } from "@/lib/load";
import { SITE_URL } from "@/lib/atproto";

// RSS 2.0 for the news posts: title, link, date and summary. Hand-rolled, as
// the feed is four fields per item.
const escape = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export const GET: APIRoute = async () => {
  const posts = await getPublishedNews();
  const origin = new URL(SITE_URL).origin;
  const items = posts
    .map((p) => {
      const link = `${origin}/news/${p.id}`;
      return [
        "<item>",
        `<title>${escape(p.data.title)}</title>`,
        `<link>${link}</link>`,
        `<guid isPermaLink="true">${link}</guid>`,
        `<pubDate>${p.data.date.toUTCString()}</pubDate>`,
        `<description>${escape(p.data.summary)}</description>`,
        "</item>",
      ].join("");
    })
    .join("\n");
  const xml = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>APS AI Tracker news</title>
<link>${origin}/news</link>
<description>News about the APS AI Tracker itself.</description>
<language>en-au</language>
${items}
</channel>
</rss>
`;
  return new Response(xml, { headers: { "content-type": "application/rss+xml; charset=utf-8" } });
};
