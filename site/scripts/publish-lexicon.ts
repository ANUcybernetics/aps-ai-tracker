#!/usr/bin/env pnpm exec tsx
// Publish the tracker's lexicon schemas (lexicons/ at the repo root) as
// com.atproto.lexicon.schema records. Ported from benswift-me.
//
// The schemas are me.benswift.* NSIDs, so their authority is benswift.me: the
// records must live in Ben's personal repo (the DID that the DNS TXT record at
// _lexicon.benswift.me points to), NOT the apsaitracker account. That's why
// this script uses the personal ATP_IDENTIFIER/ATP_APP_PASSWORD credentials
// while atproto-publish.ts (which writes the data records) uses the tracker's.
//
//   mise exec -- pnpm run atproto:lexicon            # dry run
//   mise exec -- pnpm run atproto:lexicon -- --write
//
// Idempotent: putRecord overwrites in place, so re-running with an edited
// lexicon just updates the schema record.

/* oxlint-disable no-await-in-loop -- a handful of schemas, published serially
   so the log reads in order. */
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { AtpAgent } from "@atproto/api";
import { ATPROTO_SERVICE } from "../src/lib/atproto";

net.setDefaultAutoSelectFamily(true);
net.setDefaultAutoSelectFamilyAttemptTimeout(500);

const WRITE = process.argv.includes("--write");
const SERVICE = process.argv.includes("--service")
  ? process.argv[process.argv.indexOf("--service") + 1]!
  : ATPROTO_SERVICE;

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const LEXICON_DIR = path.join(REPO_ROOT, "lexicons");
const SCHEMA_NSID = "com.atproto.lexicon.schema";

/** Every *.json under lexicons/, recursively. */
function discoverLexicons(dir: string): string[] {
  return fs
    .readdirSync(dir, { withFileTypes: true })
    .flatMap((e) =>
      e.isDirectory()
        ? discoverLexicons(path.join(dir, e.name))
        : e.name.endsWith(".json")
          ? [path.join(dir, e.name)]
          : [],
    );
}

async function main() {
  const files = discoverLexicons(LEXICON_DIR).toSorted();
  console.log(`publish-lexicon — mode: ${WRITE ? "WRITE" : "dry run"} — ${files.length} schema(s)`);

  let put: (nsid: string, record: Record<string, unknown>) => Promise<string>;
  if (WRITE) {
    const identifier = process.env.ATP_IDENTIFIER;
    const password = process.env.ATP_APP_PASSWORD;
    if (!identifier || !password) {
      throw new Error(
        "ATP_IDENTIFIER and ATP_APP_PASSWORD (the PERSONAL account — lexicon authority " +
          "is _lexicon.benswift.me) required — run via 'mise exec --'",
      );
    }
    const agent = new AtpAgent({ service: SERVICE });
    await agent.login({ identifier, password });
    const did = agent.session!.did;
    console.log(`  publishing as ${did}`);
    put = async (nsid, record) => {
      const res = await agent.com.atproto.repo.putRecord({
        repo: did,
        collection: SCHEMA_NSID,
        rkey: nsid,
        record,
      });
      return res.data.uri;
    };
  } else {
    put = async (nsid, record) => {
      console.log(`    ${SCHEMA_NSID}/${nsid}: ${JSON.stringify(record).slice(0, 120)}…`);
      return `at://did:plc:UNKNOWN/${SCHEMA_NSID}/${nsid}`;
    };
  }

  for (const file of files) {
    const lexicon = JSON.parse(fs.readFileSync(file, "utf8")) as { id?: string };
    const nsid = lexicon.id;
    if (!nsid) throw new Error(`${file} has no "id" — not a lexicon document`);
    const record = { $type: SCHEMA_NSID, ...lexicon };
    const uri = await put(nsid, record);
    console.log(`  ${WRITE ? "✓" : "·"} ${nsid} -> ${uri}`);
  }

  if (!WRITE) console.log("\n(dry run — re-run with --write to publish the schema records)");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
