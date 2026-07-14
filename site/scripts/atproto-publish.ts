#!/usr/bin/env pnpm exec tsx
// Publish the tracker corpus to the atproto network, as the apsaitracker
// account (did:plc:yhnshyrc2iev6z65u3uraon4). Reads the exporter's JSON from
// src/generated/ (run `uv run --group export export` at the repo root first)
// and syncs four kinds of record — see src/lib/atproto.ts for the identifier
// scheme and lexicons/ at the repo root for the custom schemas:
//
//   site.standard.publication/self                    the tracker site
//   site.standard.document/{abbr}                     current statement text
//   me.benswift.transparencyStatement/{abbr}          tracked-statement metadata
//   me.benswift.transparencyStatementRevision/{rkey}  one immutable observation
//                                                     per revision in the timeline
//
// Idempotent: every desired record is built deterministically from the corpus
// and hashed; only records whose hash differs from atproto-state.json (repo
// root, committed) are put. Deleting the state file forces a full — safe —
// re-put of everything.
//
// With --crosspost, new substantive revisions are also announced as skeets
// (one per agency per run, capped). Announcements are tracked in the separate,
// durable atproto-syndication.json ledger — deliberately NOT the state file,
// so a state reset/backfill can never re-announce the back catalogue. --seed
// marks every current corpus revision as already-announced (used once after
// the initial backfill, or after manual corpus surgery).
//
//   mise exec -- pnpm run atproto:publish                          # dry run
//   mise exec -- pnpm run atproto:publish -- --write --crosspost   # the cron
//   mise exec -- pnpm run atproto:publish -- --seed
//
// Auth: APSAITRACKER_BSKY_TOKEN (app password) from the mise env. The script
// refuses to write to any repo other than the tracker DID, so a credentials
// mix-up (e.g. the personal ATP_* vars) cannot touch the wrong account.

/* oxlint-disable no-await-in-loop -- puts are deliberately serial: revisions
   must land oldest-first (prev links), pairs document-then-statement, and a
   sequential trickle stays inside the PDS write rate limits. */
import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { AtpAgent, RichText } from "@atproto/api";
import {
  announcementText,
  ATPROTO_SERVICE,
  buildDocumentRecord,
  buildPublicationRecord,
  buildRevisionRecord,
  buildStatementRecord,
  DOCUMENT_COLLECTION,
  documentPath,
  latestPostRef,
  planAnnouncements,
  PUBLICATION_COLLECTION,
  REVISION_COLLECTION,
  revisionRkey,
  SITE_URL,
  STATEMENT_COLLECTION,
  TRACKER_DID,
  TRACKER_HANDLE,
  type Ledger,
  type StatementInput,
  type StrongRef,
} from "../src/lib/atproto";

// Work around node's IPv6-first happy-eyeballs stalls against bsky.social.
net.setDefaultAutoSelectFamily(true);
net.setDefaultAutoSelectFamilyAttemptTimeout(500);

const WRITE = process.argv.includes("--write");
const CROSSPOST = process.argv.includes("--crosspost");
const SEED = process.argv.includes("--seed");
const SERVICE = process.argv.includes("--service")
  ? process.argv[process.argv.indexOf("--service") + 1]!
  : ATPROTO_SERVICE;

const SITE_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = path.resolve(SITE_DIR, "..");
const GENERATED_DIR = path.join(SITE_DIR, "src", "generated");
const STATE_PATH = path.join(REPO_ROOT, "atproto-state.json");
const LEDGER_PATH = path.join(REPO_ROOT, "atproto-syndication.json");
const ICON_PATH = path.join(SITE_DIR, "src", "assets", "publication-icon.png");
const OG_PATH = path.join(SITE_DIR, "public", "og.png");

interface State {
  did: string;
  handle: string;
  publication?: string;
  statements: Record<string, string>;
  revisions: Record<string, string>;
}

function sha256(data: string | Buffer): string {
  return crypto.createHash("sha256").update(data).digest("hex");
}

function loadState(): State {
  if (!fs.existsSync(STATE_PATH)) {
    return { did: TRACKER_DID, handle: TRACKER_HANDLE, statements: {}, revisions: {} };
  }
  return JSON.parse(fs.readFileSync(STATE_PATH, "utf8")) as State;
}

function saveState(state: State) {
  const sorted = {
    did: state.did,
    handle: state.handle,
    publication: state.publication,
    statements: Object.fromEntries(Object.entries(state.statements).toSorted()),
    revisions: Object.fromEntries(Object.entries(state.revisions).toSorted()),
  };
  fs.writeFileSync(STATE_PATH, `${JSON.stringify(sorted, null, 2)}\n`);
}

function loadLedger(): Ledger {
  if (!fs.existsSync(LEDGER_PATH)) return {};
  return JSON.parse(fs.readFileSync(LEDGER_PATH, "utf8")) as Ledger;
}

function saveLedger(ledger: Ledger) {
  const sorted = Object.fromEntries(Object.entries(ledger).toSorted());
  fs.writeFileSync(LEDGER_PATH, `${JSON.stringify(sorted, null, 2)}\n`);
}

function loadStatements(): StatementInput[] {
  const dir = path.join(GENERATED_DIR, "statements");
  if (!fs.existsSync(dir)) {
    throw new Error(`${dir} missing — run \`uv run --group export export\` at the repo root first`);
  }
  const statements: StatementInput[] = [];
  for (const file of fs
    .readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .toSorted()) {
    const doc = JSON.parse(fs.readFileSync(path.join(dir, file), "utf8")) as StatementInput & {
      sourceUrl: string | null;
    };
    if (!doc.sourceUrl) {
      console.warn(`  ! ${doc.abbr}: no sourceUrl, skipping`);
      continue;
    }
    if (!doc.timeline.length) {
      console.warn(`  ! ${doc.abbr}: empty timeline, skipping`);
      continue;
    }
    statements.push(doc as StatementInput);
  }
  return statements;
}

/** Mark every current corpus revision as already-announced, write the ledger, done. */
function seed(statements: StatementInput[], ledger: Ledger) {
  let added = 0;
  for (const st of statements) {
    for (const rev of st.timeline) {
      const rkey = revisionRkey(st.abbr, rev.date);
      if (!(rkey in ledger)) {
        ledger[rkey] = { seeded: true };
        added += 1;
      }
    }
  }
  saveLedger(ledger);
  console.log(`✓ seeded ${added} revision(s) into ${path.basename(LEDGER_PATH)}`);
}

interface Put {
  collection: string;
  rkey: string;
  record: Record<string, unknown>;
  hash: string;
}

async function main() {
  const statements = loadStatements();
  const state = loadState();
  const ledger = loadLedger();

  if (SEED) {
    seed(statements, ledger);
    return;
  }

  // Desired records, built deterministically from the corpus (plus, for the
  // document records, the announcement ledger — the latest skeet for an agency
  // becomes its document's bskyPostRef). The publication hash folds in the
  // icon file bytes so an icon change triggers a re-put (blob uploads are
  // content-addressed, so re-uploading is idempotent too).
  const iconBytes = fs.existsSync(ICON_PATH) ? fs.readFileSync(ICON_PATH) : undefined;
  const publicationHash = sha256(
    JSON.stringify(buildPublicationRecord()) + (iconBytes ? sha256(iconBytes) : ""),
  );

  const byAbbr = new Map<
    string,
    { st: StatementInput; stmt: Record<string, unknown>; hash: string }
  >();
  const statementPuts: Put[] = [];
  const revisionPuts: Put[] = [];
  for (const st of statements) {
    const contentHash = sha256(st.body);
    const doc = buildDocumentRecord(st, latestPostRef(ledger, st.abbr));
    const stmt = buildStatementRecord(st, contentHash);
    const hash = sha256(JSON.stringify([doc, stmt]));
    byAbbr.set(st.abbr, { st, stmt, hash });
    if (state.statements[st.abbr] !== hash) {
      statementPuts.push({ collection: DOCUMENT_COLLECTION, rkey: st.abbr, record: doc, hash });
      statementPuts.push({ collection: STATEMENT_COLLECTION, rkey: st.abbr, record: stmt, hash });
    }
    st.timeline.forEach((rev, i) => {
      const record = buildRevisionRecord(st.abbr, rev, sha256(rev.body), st.timeline[i - 1]);
      const rkey = revisionRkey(st.abbr, rev.date);
      const revHash = sha256(JSON.stringify(record));
      if (state.revisions[rkey] !== revHash) {
        revisionPuts.push({ collection: REVISION_COLLECTION, rkey, record, hash: revHash });
      }
    });
  }

  const staleStatements = Object.keys(state.statements).filter((abbr) => !byAbbr.has(abbr));
  const plan = CROSSPOST ? planAnnouncements(statements, ledger) : { announce: [], autoSeed: [] };

  const publicationChanged = state.publication !== publicationHash;
  const total = revisionPuts.length + statementPuts.length + (publicationChanged ? 1 : 0);
  console.log(
    `atproto-publish — ${WRITE ? "WRITE" : "dry run"}${CROSSPOST ? " +crosspost" : ""} — ` +
      `${statements.length} statements, ` +
      `${statements.reduce((n, st) => n + st.timeline.length, 0)} revisions in corpus`,
  );
  console.log(
    `  to put: publication ${publicationChanged ? "1" : "0"}, ` +
      `document+statement pairs ${statementPuts.length / 2}, revisions ${revisionPuts.length}`,
  );
  for (const put of [...statementPuts, ...revisionPuts].slice(0, 10)) {
    console.log(`    ${put.collection}/${put.rkey}`);
  }
  if (total > 10) console.log(`    … and ${total - 10} more`);
  for (const a of plan.announce) {
    console.log(`  will announce: ${announcementText(a)}`);
  }
  if (plan.autoSeed.length) {
    console.log(`  auto-seeding ${plan.autoSeed.length} passed-over revision(s)`);
  }
  for (const abbr of staleStatements) {
    console.warn(`  ! ${abbr} is in atproto-state.json but not the corpus — clean up manually`);
  }

  if (!WRITE) {
    console.log("\n(dry run — re-run with --write to publish)");
    return;
  }
  if (total === 0 && plan.announce.length === 0 && plan.autoSeed.length === 0) {
    console.log("nothing to do");
    return;
  }

  const password = process.env.APSAITRACKER_BSKY_TOKEN;
  if (!password) {
    throw new Error("APSAITRACKER_BSKY_TOKEN required — run via 'mise exec --'");
  }
  const agent = new AtpAgent({ service: SERVICE });
  await agent.login({ identifier: TRACKER_HANDLE, password });
  if (agent.session!.did !== TRACKER_DID) {
    throw new Error(
      `logged in as ${agent.session!.did}, expected ${TRACKER_DID} — refusing to write`,
    );
  }

  const put = async (
    collection: string,
    rkey: string,
    record: Record<string, unknown>,
  ): Promise<StrongRef> => {
    const res = await agent.com.atproto.repo.putRecord({
      repo: TRACKER_DID,
      collection,
      rkey,
      record,
    });
    return { uri: res.data.uri, cid: res.data.cid };
  };

  /** StrongRef of an already-live record (for skeet associatedRefs). */
  const getRef = async (collection: string, rkey: string): Promise<StrongRef> => {
    const res = await agent.com.atproto.repo.getRecord({ repo: TRACKER_DID, collection, rkey });
    return { uri: res.data.uri, cid: res.data.cid! };
  };

  let done = 0;
  const progress = () => {
    done += 1;
    if (done % 25 === 0 || done === total) console.log(`  ${done}/${total}`);
  };

  const docRefs = new Map<string, StrongRef>();
  let pubRef: StrongRef | undefined;
  try {
    if (publicationChanged) {
      let iconBlob: unknown;
      if (iconBytes) {
        const uploaded = await agent.uploadBlob(iconBytes, { encoding: "image/png" });
        iconBlob = uploaded.data.blob;
      }
      pubRef = await put(PUBLICATION_COLLECTION, "self", buildPublicationRecord(iconBlob));
      state.publication = publicationHash;
      progress();
    }
    // Revisions first, oldest-to-newest (revisionPuts preserves corpus order),
    // so a statement record never precedes its history.
    for (const p of revisionPuts) {
      await put(p.collection, p.rkey, p.record);
      state.revisions[p.rkey] = p.hash;
      progress();
    }
    // Each pair arrives document-then-statement; only mark the pair synced in
    // state once the statement record (the second put) has landed, so a crash
    // mid-pair retries both on the next run.
    for (const p of statementPuts) {
      const ref = await put(p.collection, p.rkey, p.record);
      if (p.collection === DOCUMENT_COLLECTION) docRefs.set(p.rkey, ref);
      if (p.collection === STATEMENT_COLLECTION) state.statements[p.rkey] = p.hash;
      progress();
    }

    // Announcements: skeet with an external card pointing at the statement
    // page, associatedRefs to the backing records (Bluesky's enhanced link
    // cards), then re-put the document with bskyPostRef closing the loop —
    // same two-write dance as benswift-me. Ledger entries land immediately
    // after each skeet, so a crash can never double-announce.
    for (const a of plan.autoSeed) ledger[a] = { seeded: true };
    if (plan.announce.length) {
      pubRef ??= await getRef(PUBLICATION_COLLECTION, "self");
      const thumb = fs.existsSync(OG_PATH)
        ? (await agent.uploadBlob(fs.readFileSync(OG_PATH), { encoding: "image/png" })).data.blob
        : undefined;
      const origin = new URL(SITE_URL).origin;
      for (const a of plan.announce) {
        const entry = byAbbr.get(a.abbr)!;
        const docRef = docRefs.get(a.abbr) ?? (await getRef(DOCUMENT_COLLECTION, a.abbr));
        const rt = new RichText({ text: announcementText(a) });
        await rt.detectFacets(agent);
        const external: Record<string, unknown> = {
          uri: `${origin}${documentPath(a.abbr)}`,
          title: `${a.agency} — AI transparency statement`,
          description: `Full text and change history on the APS AI Transparency Tracker.`,
          associatedRefs: [docRef, pubRef],
        };
        if (thumb) external.thumb = thumb;
        const res = await agent.com.atproto.repo.createRecord({
          repo: TRACKER_DID,
          collection: "app.bsky.feed.post",
          record: {
            $type: "app.bsky.feed.post",
            text: rt.text,
            facets: rt.facets,
            langs: ["en"],
            embed: { $type: "app.bsky.embed.external", external },
            createdAt: new Date().toISOString(),
          },
        });
        const skeetRef: StrongRef = { uri: res.data.uri, cid: res.data.cid };
        ledger[a.rkey] = { ...skeetRef, syndicatedAt: new Date().toISOString() };
        console.log(`  ☁ ${skeetRef.uri}`);

        // Close the reference cycle and keep the state hash honest: the next
        // run rebuilds the document with this ledger entry, so hash it now.
        const docWithRef = buildDocumentRecord(entry.st, skeetRef);
        await put(DOCUMENT_COLLECTION, a.abbr, docWithRef);
        state.statements[a.abbr] = sha256(JSON.stringify([docWithRef, entry.stmt]));
      }
    }
  } finally {
    saveState(state);
    if (CROSSPOST) saveLedger(ledger);
  }
  console.log(
    `✓ ${total} record(s) put, ${plan.announce.length} announcement(s) ` +
      `as ${TRACKER_HANDLE} (${TRACKER_DID})`,
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
