# Roam export performance: options and recommendation

Discussion summary — 19 September 2026. No exporter changes have been made.

## Problem

Exporting a small number of Readwise highlights to Roam can take longer than the amount of data seems to justify. A representative update is **20 highlights spread across six daily notes**.

The concern is **total elapsed time**, including repeated network requests, processing and retry delays. HTTP 429 responses are not themselves a reliability problem: exponential backoff is working well. They matter here because waiting to retry increases the time before the export finishes.

This is an optimisation opportunity, not an urgent fault. Any change should justify its implementation and maintenance effort with a meaningful speed improvement.

## Current implementation

The CLI imports `write_batch_to_daily_notes()` from [chatgpt_daily_prototype.py](../../readwise_local_plus/workflows/chatgpt_daily_prototype.py), rather than the older `roam_daily_note.py` writer. It uses the [RoamClient backend API wrapper](../../readwise_local_plus/integrations/roam.py).

For each day, the active writer performs:

| Operation | API calls per day |
| --- | ---: |
| Ensure the daily note exists, if not already known locally | 0–1 |
| Write highlight headings, highlights and notes in a batch | 1 |
| Read the page to discover existing link headings | 1 |
| Write links in a second batch | 1 |
| Read the highlights subtree for the SQLite snapshot | 1 |
| **Total** | **4–5** |

For six days, this means **24–30 application-level API calls**, excluding redirects and retries. The number of days drives the request count; the number of highlights, books and notes drives the number of write actions.

The separate links write has a reason: link text contains references such as `((book-block-uid))`. The current implementation waits for the first write to return permanent block UIDs before constructing those strings.

No timing benchmark was performed during this discussion. Repeated endpoint latency is a plausible contributor, but its share of total runtime has not been measured.

## Option 1: batch across days using the backend API

### Remove separate daily-note creation

Roam documents a `page-title` location parameter that creates a missing target page automatically. For daily notes, the first heading could use:

```json
{
  "action": "create-block",
  "location": {
    "page-title": {"daily-note-page": "09-19-2026"},
    "order": "last"
  },
  "block": {
    "uid": -1,
    "string": "[[Readwise highlights]]",
    "heading": 1
  }
}
```

This uses the existing daily note or creates it when absent. The current code instead targets a `parent-uid`. The feature is documented in the [backend changelog entry for July 29, 2023](https://roamdocs.fyi/developer-documentation/roam-backend-api-change-log).

Always inserting explicit `create-page` actions is unsuitable for mixed existing and missing pages. Our `exists_ok=True` catches an error in Python; it is not a server-side option. A failed action inside a backend batch stops later actions, while earlier actions remain committed. [Backend API documentation](https://roamdocs.fyi/developer-documentation/roam-backend-api)

### Combine writes and reads

Two designs are possible:

| Design | Requests across all days |
| --- | ---: |
| Keep temporary UIDs: write all highlights, read all pages, write all links, read all snapshots | 4 |
| Preassign permanent block UIDs: read existing link structure, write everything, read all snapshots | 3 |

These counts assume the export fits within the applicable quotas without splitting or retries. Existing daily sections and book headings must still be reused.

With preassigned permanent UIDs, link strings can be constructed before the write. Roam accepts supplied block UIDs; the [official backend SDK](https://github.com/Roam-Research/backend-sdks/blob/master/typescript/src/index.ts) exposes that field. This is the basis for the proposed design, not a tested implementation in this repository.

If temporary IDs are retained, they must be unique across the combined batch: each day currently starts its own generator at `-1`. Their documented substitution applies to structural UID fields; substitution inside block text should not be assumed.

The existing `fetch_block_subtrees()` helper can support combined reads. Failure recovery also needs consideration because Roam batches can partially succeed, and the current writer persists export records after processing all days.

### Illustrative timing

Using the same assumptions for both backend designs:

- Two seconds of overhead per API request.
- Five seconds of total content-processing time.
- No throttling, redirects, retries or startup costs included.

| Design | Calculation | Illustrative elapsed time |
| --- | --- | ---: |
| Current six-day export | 24–30 × 2 seconds + 5 seconds | 53–65 seconds |
| Combined export with permanent UIDs | 3 × 2 seconds + 5 seconds | 11 seconds |

That is **88–90% fewer requests**, with roughly a minute becoming eleven seconds under these assumptions. These are comparison figures, not measured performance or a forecast.

### Effect of throttling on speed

Roam documents **100 write actions per minute per graph**. A batch consumes quota for each action, not just its single HTTP request. Twenty highlights can require many more than twenty actions once book headings, subheadings, notes and links are included. [Backend API quotas](https://roamdocs.fyi/developer-documentation/roam-backend-api)

Combining requests reduces network overhead but does not remove quota-related waiting. Faster submission may reach the quota sooner. Action-aware pacing could avoid unnecessary failed attempts, but cannot eliminate the underlying wait imposed by the quota. Existing backoff should remain useful.

This is a moderate refactor involving UID allocation, link construction, read aggregation and recovery.

## Option 2: use Roam's Local API

### How it works

Roam Desktop exposes an HTTP API on the local computer, usually port 3333, for invoking frontend API operations. It requires the desktop app; a normal browser tab does not expose this service. It interacts with the running app rather than directly editing cache files. [Local API documentation](https://roamdocs.fyi/developer-documentation/local-api)

```text
Python exporter
    → localhost HTTP
    → Roam Desktop applies changes to the local graph
    → Roam's normal sync sends changes to the hosted graph
    → changes become available on other devices
```

A hosted graph can contain local changes before they reach the server; offline changes sync when connectivity returns. Therefore, local completion and cloud-sync completion are separate measurements. [Hosted graph documentation](https://roamdocs.fyi/help/hosted-graph)

Current official tooling uses a separate Local API Token approved in Roam Desktop. The Python exporter could implement the HTTP protocol directly; an AI or MCP layer is not necessary. The [official local client](https://github.com/Roam-Research/roam-tools/blob/master/packages/local/src/client.ts) demonstrates authentication and port discovery.

### Potential speed benefits

- Local requests avoid repeated Internet round trips.
- Changes are applied in the app where they will be viewed.
- The frontend API documents a shared budget of **1,500 rate-limited calls per 60 seconds**, including writes and some UI operations. This offers substantially more headroom than the backend write allowance, although the budgets are not identical in scope.

Frontend write promises resolve when Roam has applied the operation, before the UI necessarily re-renders. That should not be treated as confirmation of cloud synchronisation. [Frontend API documentation](https://roamdocs.fyi/developer-documentation/roam-alpha-api)

The Local API could therefore reduce both request latency and time spent waiting for write quota. This is a reason to investigate it, not a measured speed guarantee. No guarantee about internal sync throughput or its limits was established.

### Tradeoffs and implementation work

- Roam Desktop must be running and the target graph accessible on the machine the exporter can reach. This is less convenient for unattended exports on a separate server.
- The backend's batch payloads and temporary-ID response maps are not a drop-in match for the local interface. Writes, UID handling, query responses and errors need an adapter.
- Local writes followed by local snapshots would confirm local state, not that another device can already see it.
- The local integration is evolving, so version compatibility adds maintenance work. [Official Roam tools repository](https://github.com/Roam-Research/roam-tools)

There is not yet enough evidence to give a useful local timing estimate. A benchmark with the actual graph and desktop app is more informative than assuming localhost transport makes all application work instantaneous.

## Recommendation

**If the exporter normally runs on the same computer as Roam Desktop, investigate the Local API before committing to the larger backend batching refactor.** It potentially addresses both sources of avoidable waiting: remote round trips and the backend write quota.

The decision should be based on end-to-end speed, not reducing 429 counts for their own sake. Backoff already handles those responses correctly.

A proportionate next step, if implementation work is authorised, is a small isolated benchmark rather than replacing the current writer:

1. Measure a representative current export: 20 highlights across six days, including realistic headings, notes and links. Separate request time from backoff time.
2. Reproduce the workload through the Local API in a test graph, with Roam Desktop already open. Measure local completion and cloud-sync completion separately.
3. Compare the time saved with the adapter effort and the requirement to have Desktop available.

If the local route is clearly faster and operationally convenient, add it as an optional transport while retaining backend support. If Desktop availability is inconvenient, the combined backend design with preassigned block UIDs is the stronger alternative.

Because the current delay is tolerable, retaining the existing implementation is also reasonable if measurements show that the benefit does not justify the work.

## Evidence and scope

The discussion involved read-only repository inspection and public documentation research. No exporter runs, live graph writes or local API benchmarks were performed. The `roamdocs.fyi` links reproduce Roam's public documentation graph; the SDK and local-client links point to official Roam Research repositories. Documented limits and API behaviour should be rechecked when implementation begins.
