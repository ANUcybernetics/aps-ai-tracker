// The site.standard.* record keys, read from the committed atproto-state.json
// at the repo root. Those lexicons are `key: tid`, so unlike our own
// me.benswift.* rkeys these cannot be computed from the corpus — they are
// allocated once by scripts/atproto-publish.ts and recorded there.
//
// Kept separate from atproto.ts so that module stays pure and env-free: this
// one reaches outside the Astro root, and is only imported by pages that emit
// AT-URIs.

import rawState from "../../../atproto-state.json";
import { publicationUri } from "./atproto";

// Typed structurally rather than off the JSON's inferred shape, so the site
// still builds from a state file written before these keys existed.
const state = rawState as {
  publicationRkey?: string;
  documentRkeys?: Record<string, string>;
};

const documentRkeys: Record<string, string> = state.documentRkeys ?? {};

/**
 * The document rkey for an agency, or undefined before the publisher has
 * allocated one. Pages treat that as "no backing record yet" and emit no
 * <link> rather than guessing a URI that would 404.
 */
export function documentRkey(abbr: string): string | undefined {
  return documentRkeys[abbr];
}

export const PUBLICATION_RKEY: string | undefined = state.publicationRkey;

export const PUBLICATION_URI: string | undefined = PUBLICATION_RKEY
  ? publicationUri(PUBLICATION_RKEY)
  : undefined;
