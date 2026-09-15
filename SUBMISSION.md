# CommonTable - Good food. Better connections.

**Global Innovation Build Challenge V2 / Track 03: Open**

CommonTable is a local-first, explainable planning lab that connects surplus food batches to community receiving hubs. It demonstrates a complete technical prototype: editable inputs, exact allocation, a visible constraint graph, baseline comparison, persistent scenario snapshots and portable exports.

## Inspiration

A surplus batch and an unmet need can exist a few kilometers apart and still fail to connect. Compatibility matters: a hub may only accept bakery food, another may lack cold storage, and a nearby batch may expire before arrival. A nearest-destination rule can consume the flexible capacity that another batch needs.

We wanted to make that invisible matching problem visible. The aim is not another opaque recommendation or a claim of real food rescued, but a small, inspectable tool for exploring how community infrastructure could share limited resources.

## What it does

CommonTable lets someone model a fictional neighborhood with up to 20 surplus batches and 20 receiving hubs. Batches declare category, quantity, location, readiness and expiry; hubs declare accepted categories, cold storage, opening windows, demand and receiving capacity.

The planner finds the maximum number of compatible servings that can be assigned, then minimizes serving-kilometers among those maximum-coverage plans. The interface shows the transfer network, hub-level coverage, direct-trip times and loads, unassigned supply, and an explanation for every possible batch-to-hub connection.

The same inputs are also run through an expiry-ordered nearest-first baseline. In the supplied synthetic neighborhood, CommonTable assigns **230 servings compared with 170** for the baseline. Reducing the maximum direct leg from 5.5 km to 2 km drops coverage to **120 servings**, making the constraint's effect immediately visible.

Scenarios can be edited, saved as anonymous browser-session snapshots, reloaded, deleted, exported to JSON and imported again. A spreadsheet-safe CSV contains the current handoff plan. Stale results are clearly labeled, and the application blocks CSV export until changed inputs have been recomputed.

## How we built it

The backend is Python and SQLite, with no third-party runtime dependencies. An original min-cost maximum-flow implementation connects a source to batch nodes, eligible hub nodes and a sink. Successive shortest augmenting paths, reduced-cost potentials and residual reverse edges allow earlier choices to be reconsidered. Sorted IDs make the result reproducible.

The frontend uses JavaScript ES modules, HTML, CSS and an SVG schematic. No maps API, hosted AI inference, model weights or remote database is required. It can run without internet access after obtaining the source.

The distinctive engineering is the combination of eligibility rules, a capacity-conserving optimizer, a same-constraints baseline and an inspectable explanation layer. We do not claim to have invented min-cost flow. The contribution is making its consequences understandable and usable in a cross-disciplinary community-planning prototype.

## Challenges we ran into

**Preserving options rather than choosing the nearest destination.** The synthetic bakery counterexample required residual edges, not a nearest-neighbor heuristic, to recover the maximum-coverage assignment.

**Making honest metrics.** Serving-kilometers, vehicle loads and distance driven are different quantities. We separated them, disclosed parallel-vehicle assumptions, and avoided invented emissions or nutrition conversions. The higher-coverage sample actually uses more one-way distance than the baseline.

**Keeping explanations and results consistent.** Editing inputs invalidates the displayed plan until recomputation. Loading a snapshot reruns the algorithm; imports receive the same strict validation as interactive edits.

**Working under minimal runtime requirements.** The application uses Python's standard library. Real-browser verification and recording use workspace-local development dependencies rather than becoming runtime prerequisites.

## Accomplishments

The project is a runnable end-to-end application, not a template or slide deck. It includes **24 automated backend tests**, with **180 exhaustive small-network oracle comparisons**, exact fixture checks, a 20-by-20 conservation test, and API/persistence validation.

Real-browser verification covers editing, adding/removing locations, what-if recomputation, invalid imports, untrusted HTML labels, snapshot isolation and reload, CSV/JSON export, and a mobile viewport. It verifies that the application makes no external requests.

Four real interface screenshots and a **roughly 2-minute-38-second demo with burned-in English captions** document the running system. A portable archive build launches and exercises the extracted application, rather than only checking file syntax.

## What we learned

The useful part of optimization is often the constraint that prevents a match, not just the final score. Seeing why chilled food has no eligible hub or why a bakery-only hub needs a particular batch suggests much more actionable questions than an unexplained total.

We also learned to resist overclaiming. A synthetic allocation improvement is not evidence of meals delivered, emissions avoided, or equitable community impact. A trustworthy prototype should expose these boundaries as clearly as its successes.

## What's next

A future version could investigate declared minimum-coverage policies and show how they trade off against distance and total allocation. Road-network distances, limited-fleet scheduling and food-handling verification would require separate engineering and validation. The current application deliberately does not simulate those capabilities or operate real deliveries.

## Built With

Python 3.11, SQLite, Python standard-library HTTP/JSON/CSV/heap-based graph utilities and unittest, JavaScript ES modules, HTML5, CSS, SVG, Node.js 22, npm, Playwright 1.58.2, Chromium 145, Playwright's bundled FFmpeg, and an original synthetic scenario fixture. Optional browser-evidence tooling uses Debian bookworm shared libraries and DejaVu fonts.

**AI disclosure:** GitHub Copilot CLI, powered by GPT-6 Astra, assisted the design, code, tests, documentation and demo automation. There is no model inference in the application and no external dataset or paid API. Verification ran on CPU-only ARM64 Linux.

## Prototype boundaries

This is an **Open-track planning simulation**, not a medical or financial system, dispatch product or food-safety tool. Names and coordinates are fictional. Servings are abstract units, demand is pooled across accepted categories, and same-day direct trips assume sufficient parallel vehicles. The objective maximizes aggregate coverage, not equitable per-hub distribution. No impact on real communities has been measured.

## Project materials

The [README](README.md) contains setup, usage, schema, API, algorithm and reproduction instructions. The [media guide](docs/MEDIA.md) links the actual screenshots and local captioned recording. All application source, the original synthetic fixture and development scripts are included in this repository.


## Try it out

- [Live application](https://devpost-global-innovation-build-challenge-v2-30408.gilbertcv.com)
- [Public source](https://github.com/gil906/devpost-global-innovation-build-challenge-v2-30408)
