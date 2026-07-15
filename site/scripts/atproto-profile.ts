#!/usr/bin/env pnpm exec tsx
// Set the apsaitracker Bluesky profile (display name, bio, avatar). One-shot
// and idempotent — putRecord overwrites app.bsky.actor.profile/self in place —
// so re-run after editing the constants below.
//
//   mise exec -- pnpm run atproto:profile

import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { AtpAgent } from "@atproto/api";
import { ATPROTO_SERVICE, SITE_URL, TRACKER_DID, TRACKER_HANDLE } from "../src/lib/atproto";

net.setDefaultAutoSelectFamily(true);
net.setDefaultAutoSelectFamilyAttemptTimeout(500);

const DISPLAY_NAME = "APS AI Tracker";
// Bluesky caps bios at 256 graphemes; keep well under.
const DESCRIPTION = `Tracking how Australian Government agencies describe their use of AI — full text + change history of every AI transparency statement, updated daily.

${SITE_URL}
doi.org/10.5281/zenodo.20842437`;

const AVATAR_PATH = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "src",
  "assets",
  "publication-icon.png",
);

async function main() {
  const password = process.env.APSAITRACKER_BSKY_TOKEN;
  if (!password) {
    throw new Error("APSAITRACKER_BSKY_TOKEN required — run via 'mise exec --'");
  }
  const agent = new AtpAgent({ service: ATPROTO_SERVICE });
  await agent.login({ identifier: TRACKER_HANDLE, password });
  if (agent.session!.did !== TRACKER_DID) {
    throw new Error(`logged in as ${agent.session!.did}, expected ${TRACKER_DID}`);
  }

  const avatar = await agent.uploadBlob(fs.readFileSync(AVATAR_PATH), {
    encoding: "image/png",
  });
  await agent.com.atproto.repo.putRecord({
    repo: TRACKER_DID,
    collection: "app.bsky.actor.profile",
    rkey: "self",
    record: {
      $type: "app.bsky.actor.profile",
      displayName: DISPLAY_NAME,
      description: DESCRIPTION,
      avatar: avatar.data.blob,
    },
  });
  console.log(`✓ profile set for ${TRACKER_HANDLE}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
