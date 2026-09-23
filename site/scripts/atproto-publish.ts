#!/usr/bin/env pnpm exec tsx
// Publish the tracker corpus to the atproto network, as the apsaitracker
// account (did:plc:yhnshyrc2iev6z65u3uraon4). Reads the exporter's JSON from
// src/generated/ (run `uv run --group export export` at the repo root first)
// and syncs four kinds of record — see src/lib/atproto.ts for the identifier
// scheme and lexicons/ at the repo root for the custom schemas:
//
//   site.standard.publication/{tid}                   the tracker site
//   site.standard.document/{tid}                      current statement text
//   me.benswift.transparencyStatement/{abbr}          tracked-statement metadata
//   me.benswift.transparencyStatementRevision/{rkey}  one immutable observation
//                                                     per revision in the timeline
//
// The site.standard.* lexicons are `key: tid` and the PDS enforces it, so those
// two rkeys are allocated once and recorded in the state file rather than
// derived from the abbr. Losing that mapping is still safe: allocateRkeys()
// re-adopts the live records by matching their `path` field before minting
// anything new.
//
// Idempotent: every desired record is built deterministically from the corpus
// and hashed; only records whose hash differs from atproto-state.json (repo
// root, committed) are put. Deleting the state file forces a full — safe —
// re-put of everything.
//
// With --crosspost, new substantive revisions are also announced as skeets
// (one per agency per run, capped), and so is each published news post in
// src/content/news/ (drafts never; ledger key `news:{slug}`). Announcements
// are tracked in the separate, durable atproto-syndication.json ledger —
// deliberately NOT the state file, so a state reset/backfill can never
// re-announce the back catalogue. --seed marks every current corpus revision
// as already-announced (used once after the initial backfill, or after manual
// corpus surgery).
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
import { TID } from "@atproto/common-web";
import {
  announcementText,
  ATPROTO_SERVICE,
  buildDocumentRecord,
  buildPublicationRecord,
  buildRevisionRecord,
  buildStatementRecord,
  DOCUMENT_COLLECTION,
  documentPath,
  isTid,
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
import {
  newsLedgerKey,
  newsPostText,
  newsToAnnounce,
  parseNewsPost,
  type NewsPost,
} from "../src/lib/news";
import { statementSchema } from "../src/lib/schemas";

// Work around node's IPv6-first happy-eyeballs stalls against bsky.social.
net.setDefaultAutoSelectFamily(true);
net.setDefaultAutoSelectFamilyAttemptTimeout(500);

const WRITE = process.argv.includes("--write");
const PRUNE = process.argv.includes("--prune");
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
const NEWS_DIR = path.join(SITE_DIR, "src", "content", "news");
const OG_PATH = path.join(SITE_DIR, "public", "og.png");

interface State {
  did: string;
  handle: string;
  publication?: string;
  /** TID rkey of the site.standard.publication record. */
  publicationRkey?: string;
  /** abbr -> TID rkey of its site.standard.document record. */
  documentRkeys: Record<string, string>;
  statements: Record<string, string>;
  revisions: Record<string, string>;
}

function sha256(data: string | Buffer): string {
  return crypto.createHash("sha256").update(data).digest("hex");
}

// Write-to-temp-then-rename: a hard kill (systemd timeout, OOM, power loss)
// mid-write can therefore never leave a truncated state/ledger file. That
// matters because loadState/loadLedger JSON.parse these bare — a torn file
// would fail every subsequent nightly run until someone repaired it by hand.
function writeFileAtomic(filePath: string, data: string) {
  const tmp = `${filePath}.tmp`;
  fs.writeFileSync(tmp, data);
  fs.renameSync(tmp, filePath);
}

function loadState(): State {
  if (!fs.existsSync(STATE_PATH)) {
    return {
      did: TRACKER_DID,
      handle: TRACKER_HANDLE,
      documentRkeys: {},
      statements: {},
      revisions: {},
    };
  }
  const state = JSON.parse(fs.readFileSync(STATE_PATH, "utf8")) as State;
  state.documentRkeys ??= {};
  return state;
}

function saveState(state: State) {
  const sorted = {
    did: state.did,
    handle: state.handle,
    publication: state.publication,
    publicationRkey: state.publicationRkey,
    documentRkeys: Object.fromEntries(Object.entries(state.documentRkeys).toSorted()),
    statements: Object.fromEntries(Object.entries(state.statements).toSorted()),
    revisions: Object.fromEntries(Object.entries(state.revisions).toSorted()),
  };
  writeFileAtomic(STATE_PATH, `${JSON.stringify(sorted, null, 2)}\n`);
}

function loadLedger(): Ledger {
  if (!fs.existsSync(LEDGER_PATH)) return {};
  return JSON.parse(fs.readFileSync(LEDGER_PATH, "utf8")) as Ledger;
}

function saveLedger(ledger: Ledger) {
  const sorted = Object.fromEntries(Object.entries(ledger).toSorted());
  writeFileAtomic(LEDGER_PATH, `${JSON.stringify(sorted, null, 2)}\n`);
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
    // Parse through the exporter's zod schema — the same contract the site
    // build validates against — so a shape drift in export.py fails loudly
    // here instead of publishing records full of undefineds.
    const doc = statementSchema.parse(JSON.parse(fs.readFileSync(path.join(dir, file), "utf8")));
    const { sourceUrl } = doc;
    if (!sourceUrl) {
      console.warn(`  ! ${doc.abbr}: no sourceUrl, skipping`);
      continue;
    }
    if (!doc.timeline.length) {
      console.warn(`  ! ${doc.abbr}: empty timeline, skipping`);
      continue;
    }
    statements.push({ ...doc, sourceUrl });
  }
  return statements;
}

function loadNews(): NewsPost[] {
  if (!fs.existsSync(NEWS_DIR)) return [];
  return fs
    .readdirSync(NEWS_DIR)
    .filter((f) => f.endsWith(".md"))
    .map((f) => parseNewsPost(f.slice(0, -3), fs.readFileSync(path.join(NEWS_DIR, f), "utf8")));
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

/** Stands in for an unallocated rkey in a dry run, which never logs in. */
const PENDING_RKEY = "(to be allocated)";

/** Every rkey in a collection, paired with its record, following the cursor. */
async function listAll(
  agent: AtpAgent,
  collection: string,
): Promise<{ rkey: string; value: Record<string, unknown> }[]> {
  const out: { rkey: string; value: Record<string, unknown> }[] = [];
  let cursor: string | undefined;
  do {
    const res = await agent.com.atproto.repo.listRecords({
      repo: TRACKER_DID,
      collection,
      limit: 100,
      cursor,
    });
    for (const r of res.data.records) {
      out.push({ rkey: r.uri.slice(r.uri.lastIndexOf("/") + 1), value: r.value as never });
    }
    cursor = res.data.cursor;
  } while (cursor);
  return out;
}

/**
 * Give every statement (and the publication) a site.standard.* rkey. These are
 * TIDs, so unlike our own rkeys they cannot be recomputed from the corpus and
 * live in the state file instead. A missing entry is first matched against the
 * live records by `path` — the durable human-readable identifier — so a lost
 * state file re-adopts what is already published rather than duplicating it.
 * Legacy abbr-keyed records are skipped: the PDS rejects writes to them, which
 * is what this whole scheme exists to fix.
 */
async function allocateRkeys(agent: AtpAgent, state: State, statements: StatementInput[]) {
  const unallocated = statements.filter((st) => !state.documentRkeys[st.abbr]);
  if (unallocated.length) {
    const byPath = new Map<string, string>();
    for (const { rkey, value } of await listAll(agent, DOCUMENT_COLLECTION)) {
      const p = value.path;
      if (isTid(rkey) && typeof p === "string") byPath.set(p, rkey);
    }
    for (const st of unallocated) {
      const found = byPath.get(documentPath(st.abbr));
      state.documentRkeys[st.abbr] = found ?? TID.nextStr();
      console.log(
        `  + ${st.abbr}: ${found ? "adopted" : "minted"} document rkey ${state.documentRkeys[st.abbr]}`,
      );
    }
  }
  if (!state.publicationRkey) {
    const live = (await listAll(agent, PUBLICATION_COLLECTION)).find((r) => isTid(r.rkey));
    state.publicationRkey = live?.rkey ?? TID.nextStr();
    console.log(
      `  + publication: ${live ? "adopted" : "minted"} rkey ${state.publicationRkey}` +
        (live ? "" : " — will be published on this run"),
    );
    // A minted publication is a record that does not exist yet, whatever hash
    // the state file remembers from its predecessor at another rkey.
    if (!live) state.publication = undefined;
  }
  saveState(state);
}

/** Log in as the tracker, refusing any other identity. */
async function connect(): Promise<AtpAgent> {
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
  return agent;
}

async function main() {
  const statements = loadStatements();
  const state = loadState();
  const ledger = loadLedger();

  if (SEED) {
    seed(statements, ledger);
    return;
  }

  // site.standard.* rkeys have to exist before any record can be built, and
  // allocating them needs the network. Only connect when something is actually
  // unallocated, so an ordinary no-op run never logs in.
  let agent: AtpAgent | undefined;
  const unallocated =
    !state.publicationRkey || statements.some((st) => !state.documentRkeys[st.abbr]);
  if (WRITE && unallocated) {
    agent = await connect();
    await allocateRkeys(agent, state, statements);
  }
  const pubRkey = state.publicationRkey ?? PENDING_RKEY;

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
    const docRkey = state.documentRkeys[st.abbr] ?? PENDING_RKEY;
    const doc = buildDocumentRecord(st, pubRkey, latestPostRef(ledger, st.abbr));
    const stmt = buildStatementRecord(st, contentHash, docRkey);
    const hash = sha256(JSON.stringify([doc, stmt]));
    byAbbr.set(st.abbr, { st, stmt, hash });
    if (state.statements[st.abbr] !== hash) {
      statementPuts.push({ collection: DOCUMENT_COLLECTION, rkey: docRkey, record: doc, hash });
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

  // Records for statements that have left the corpus (an agency dropped, or a
  // duplicate removed). Revision rkeys are `{abbr}-{compact UTC}` and the
  // timestamp never contains a dash, so the abbr is everything before the last.
  const staleStatements = Object.keys(state.statements).filter((abbr) => !byAbbr.has(abbr));
  const staleRevisions = Object.keys(state.revisions).filter(
    (rkey) => !byAbbr.has(rkey.slice(0, rkey.lastIndexOf("-"))),
  );
  const stale = staleStatements.length * 2 + staleRevisions.length;
  const plan = CROSSPOST ? planAnnouncements(statements, ledger) : { announce: [], autoSeed: [] };
  const newsPlan = CROSSPOST ? newsToAnnounce(loadNews(), ledger) : [];

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
  if (!WRITE && unallocated) {
    console.log(
      `  note: some site.standard.* rkeys are not allocated yet, so this dry run ` +
        `shows them as ${PENDING_RKEY} and over-counts the puts — re-run with --write`,
    );
  }
  for (const a of plan.announce) {
    console.log(`  will announce: ${announcementText(a)}`);
  }
  for (const post of newsPlan) {
    console.log(`  will announce news: ${post.title}`);
  }
  if (plan.autoSeed.length) {
    console.log(`  auto-seeding ${plan.autoSeed.length} passed-over revision(s)`);
  }
  for (const abbr of staleStatements) {
    const revs = staleRevisions.filter((rkey) => rkey.startsWith(`${abbr}-`)).length;
    console.warn(
      `  ! ${abbr} is in atproto-state.json but not the corpus — ` +
        `${PRUNE ? `will delete 2 records + ${revs} revisions` : "re-run with --prune to delete"}`,
    );
  }

  if (!WRITE) {
    console.log("\n(dry run — re-run with --write to publish)");
    return;
  }
  if (
    total === 0 &&
    plan.announce.length === 0 &&
    newsPlan.length === 0 &&
    plan.autoSeed.length === 0 &&
    !(PRUNE && stale > 0)
  ) {
    console.log("nothing to do");
    return;
  }

  agent ??= await connect();

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

  const del = async (collection: string, rkey: string): Promise<void> => {
    await agent.com.atproto.repo.deleteRecord({ repo: TRACKER_DID, collection, rkey });
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
      pubRef = await put(PUBLICATION_COLLECTION, pubRkey, buildPublicationRecord(iconBlob));
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

    // Prune last: state entries are dropped one record at a time, so a crash
    // mid-prune leaves the rest to be retried rather than orphaned.
    if (PRUNE) {
      for (const rkey of staleRevisions) {
        await del(REVISION_COLLECTION, rkey);
        delete state.revisions[rkey];
      }
      for (const abbr of staleStatements) {
        const docRkey = state.documentRkeys[abbr];
        // A statement published before the TID migration has no mapping; its
        // legacy record is unreachable for writes, so leave it and drop only
        // what we can still address.
        if (docRkey) await del(DOCUMENT_COLLECTION, docRkey);
        await del(STATEMENT_COLLECTION, abbr);
        delete state.documentRkeys[abbr];
        delete state.statements[abbr];
      }
      if (stale) console.log(`  pruned ${stale} stale record(s)`);
    }

    // Announcements: skeet with an external card pointing at the statement
    // page, associatedRefs to the backing records (Bluesky's enhanced link
    // cards), then re-put the document with bskyPostRef closing the loop —
    // same two-write dance as benswift-me. The ledger is persisted to disk
    // straight after every skeet (not just mutated in memory for the finally
    // block, which a hard kill would skip), so the double-announce window is
    // only the instant between the createRecord response and that write.
    for (const a of plan.autoSeed) ledger[a] = { seeded: true };
    const origin = new URL(SITE_URL).origin;
    let thumb: unknown;
    const cardThumb = async () =>
      (thumb ??= fs.existsSync(OG_PATH)
        ? (await agent.uploadBlob(fs.readFileSync(OG_PATH), { encoding: "image/png" })).data.blob
        : undefined);
    if (plan.announce.length) {
      pubRef ??= await getRef(PUBLICATION_COLLECTION, pubRkey);
      await cardThumb();
      for (const a of plan.announce) {
        const entry = byAbbr.get(a.abbr)!;
        const docRkey = state.documentRkeys[a.abbr]!;
        const docRef = docRefs.get(docRkey) ?? (await getRef(DOCUMENT_COLLECTION, docRkey));
        const rt = new RichText({ text: announcementText(a) });
        await rt.detectFacets(agent);
        const external: Record<string, unknown> = {
          uri: `${origin}${documentPath(a.abbr)}`,
          title: `${a.agency} — AI transparency statement`,
          description: `Full text and change history on the APS AI Tracker.`,
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
        saveLedger(ledger);
        console.log(`  ☁ ${skeetRef.uri}`);

        // Close the reference cycle and keep the state hash honest: the next
        // run rebuilds the document with this ledger entry, so hash it now.
        const docWithRef = buildDocumentRecord(entry.st, pubRkey, skeetRef);
        await put(DOCUMENT_COLLECTION, docRkey, docWithRef);
        state.statements[a.abbr] = sha256(JSON.stringify([docWithRef, entry.stmt]));
      }
    }

    // News posts: one skeet each, an external card pointing at the post.
    for (const post of newsPlan) {
      const rt = new RichText({ text: newsPostText(post) });
      await rt.detectFacets(agent);
      const external: Record<string, unknown> = {
        uri: `${origin}/news/${post.slug}`,
        title: post.title,
        description: post.summary,
      };
      const image = await cardThumb();
      if (image) external.thumb = image;
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
      ledger[newsLedgerKey(post.slug)] = {
        uri: res.data.uri,
        cid: res.data.cid,
        syndicatedAt: new Date().toISOString(),
      };
      saveLedger(ledger);
      console.log(`  ☁ news ${res.data.uri}`);
    }
  } finally {
    saveState(state);
    if (CROSSPOST) saveLedger(ledger);
  }
  console.log(
    `✓ ${total} record(s) put, ${plan.announce.length + newsPlan.length} announcement(s) ` +
      `as ${TRACKER_HANDLE} (${TRACKER_DID})`,
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
