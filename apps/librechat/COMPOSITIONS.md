# Learning composition integration

## Initial V1 boundary

`LearningComposition.tsx` is a configuration-driven renderer, not a business
runtime. It reuses the existing learning components and `LearningUI.tsx`.
Its dependency graph does not import the demo store or make network calls.
`DemoUI.tsx` is now a compatibility export plus the demo-specific `useDemo` hook.
Existing UI consumers keep the same appearance and motion.

The initial contract is `learning_composition.v1`, with three recipes.
The separate V2 renderer and native host described later do not replace it:

| Recipe | Input | Composition |
| --- | --- | --- |
| `bfs` | node ids, directed edges in traversal order, starting node, view selection | graph plus optional queue, code and variables; a single player |
| `code_review` | short prompt and inert code | inline saved annotations plus explicit whole-review submission |
| `code_repair` | short prompt, original code, public cases, view selection | editor plus optional baseline diff and cases; explicit check intent |

This is not arbitrary composition of all 31 primitives. Other algorithm views
and component examples remain available in the gallery, but are not advertised
as configurable recipes until they have input contracts and implementations.

The gallery's `?view=compositions` tab contains four configurations, including
two BFS graphs. Its configuration editor validates before replacing the current
scene. Invalid configuration preserves the existing draft and scene. Applying
valid configuration or selecting another example explicitly resets the local
preview session.

## Single contract source and model guidance

- Authoritative DTOs: `backend/src/leornian/modules/tutor/composition_contracts.py`.
- Guide: `backend/src/leornian/modules/tutor/composition-guide.md`.
- Context helper: `composition_guidance.py::composition_guidance()` appends the
  current JSON Schema to that guide. It is opt-in, not automatically injected
  into existing Tutor roles or frozen runs.
- Export: `backend/src/leornian/entrypoints/export_composition.py`.
- Generated client files: `composition-schema.json`,
  `composition-validator.generated.mjs`, `composition-types.generated.ts`.
- Cross-field checks: Pydantic validators and `composition-runtime.mjs`, covered
  by tests against the same example configurations.

Run from the repository root:

```text
node apps/librechat/generate-composition.mjs
node apps/librechat/generate-composition.mjs --check
node --test apps/librechat/composition.test.mjs
uv run --frozen --directory backend pytest -q tests/test_learning_compositions.py
```

Generation uses already installed pinned Ajv and OpenAPI TypeScript tooling,
without modifying upstream or installing dependencies. The browser consumes a
precompiled validator, not runtime `eval`/`new Function`. The type-generation
OpenAPI document has no paths and is not added to the live API.

The proposal excludes endpoints, callbacks, permissions, results and answers.
Schema validation is structural only: it cannot establish that model-authored
code, prompts or test expectations are correct or safe to publish.

## Host interface

Use `LearningCompositionProps`, `CompositionDraft`, `CompositionIntent` and
`CompositionReceipt` exported by `LearningComposition.tsx`.

- `definition`: validated public presentation data. The renderer also rejects
  invalid or unsupported definitions instead of partially rendering them.
- `draft` / `onDraftChange`: controlled code and saved/pending annotation state.
  Saving a reason is a local draft change, not a backend submission.
- `onAction`: optional event callback; without it check/submit buttons are
  disabled. Emits `submit_review` with saved annotations, or `check_code` with
  current code. These are UI intents, **not existing HTTP action DTOs**.
- `status`: `ready`, `busy`, `submitted`, or `unknown`, supplied by the host.
  Only ready permits editing/submitting. A click alone never marks submission
  completed. Unknown locks actions and never schedules a retry.
- `receipt`: separately supplied public feedback. Review feedback is shown
  only after submitted status. Code results are displayed only when their
  exact code snapshot matches the current draft; otherwise a stale-result
  notice replaces the result table.
- `readOnly`: host permission state. `active`: whether this scene is visible;
  leaving the gallery tab or hiding the document pauses playback.

The host must key the component/session by its server-owned artifact identity
and immutable content version, replace the associated draft and receipt together
when that content binding changes, and reject receipts for another binding.
Do not use the action/status revision as a React key: ordinary running/completed
updates must not reset code, annotations or playback. Retain the current action
revision separately for optimistic concurrency. Do not key by model-supplied
title or overwrite learner drafts on unrelated rerenders. Keep the definition
object stable while processing draft changes.

The preview host is isolated in `CompositionGallery.tsx`. Its review message
and code checks are explicitly offline fixture receipts; custom configurations
do not gain fixture results or execution rights. They are not persisted to
learning records.

## Initial V1 backend handoff

At that frontend-only handoff, no changes were made to the tool registry, existing `LearningReply`,
`LearningArtifactView`, candidate acceptance, API endpoints or migrations.
That slice only delivered the existing knowledge-check and
code-workspace presentations. Merely importing this contract does not enable
new presentations for old clients or grant model capabilities.

The backend integration owner should:

1. Decide the versioned candidate/presentation envelope for these public
   configurations, retaining server-owned identity, revision, content reference
   and permissions. Keep model proposals separate from accepted delivery.
2. Enable the guide only for clients and frozen roles that support the contract.
   The existing `LearningReply` cannot currently carry this proposal. Connect
   through the existing controlled preparation/candidate flow, rather than
   silently extending `exact_handle` to mean model-authored content.
3. Reuse the existing exact-handle selection and delivery checks, including
   node scope, current content and publication status.
4. Map permitted check intents to existing assessment/Runner ownership with
   revision and idempotency checks. Do not invent a new evaluator. Review
   annotation submission needs an explicit supported business contract; it is
   not the current single-choice `RespondAction`. The existing Python IO owner
   locks one submission; repeated edit/check cycles need its explicit multi-Attempt
   support, not a new client action id to bypass the lock. Presentation code can
   contain 20,000 characters, but current `Submission` permits at most 12,000
   characters AND 12,000 UTF-8 bytes. Validate against that execution contract
   before enabling/submitting a real check; the display contract grants no exception.
5. Return public receipts to the host adapter with their artifact/revision and
   action/Attempt and code binding; matching code alone is not enough.
   Distinguish content version from action/status revision.
   Preserve unknown outcomes and explicit retry authorization.

On 2026-11-05 the fourth-phase backend chat accepted this as the WP05/06
independent presentation layer, without claiming backend integration complete.
The agreed minimal order is versioned content/candidate capability, read-only
BFS delivery, authorized code repair, then learner-review submission. BFS must
not masquerade as an item-bank practice slot or advance mastery on playback.

That initial frontend/contract slice did not claim actual model selection,
backend preparation/persistence, authorized actions, source side-panel API
integration or live grading/execution as complete. No real model or Runner
calls were made there.

## V2 controlled components and native host

The current implementation adds `learning_composition.v2`, with all 31 typed
renderer cases in `LearningCompositionV2.tsx`. It is not a fourth recipe.
Shared states, algorithm inputs, timelines, references and action targets use
the authoritative `composition_catalog.py` and `composition_v2_contracts.py`.

Owner-bound executable `CodeEditor`/`CodeDiff` ports reuse `PracticeWorkbench`.
The native host supplies the original task, fixed environment, public sample,
assistance and attempt history. Typed state and action-target links place the
editor, comparison, explicit run action and result in that existing layout.
File selection and protected contents remain in the original controlled draft;
host action permissions, locks and UNKNOWN handling still govern execution.
Editable single-file examples with an example runner also use `PracticeWorkbench`.
With `learning_example_runs.v2` the editor sits above a live terminal. Run starts
one local isolated program. Its output appears as it is written; pressing Enter
sends one line to that same process. Stop ends the run and reopening restores
its transcript. Published practice retains its test cases and assessment results.
Local HTML/CSS previews keep their sandbox and refresh action.

With `learning_templates.v1`, `prepare_learning_template` takes content for a
code workspace, web preview, walkthrough, choice, ordering, reflection or code
annotation and returns a checked-delivery candidate. The underlying V2 component
definition remains readable by composition clients. Code templates include
`presentation.example_workspace` with the editor, description, language and
optional example inputs shown as suggestions. Published prompts, actions and scores still belong to their
original question; a template's local inputs never submit a response.

Generation produces the V2 schema, CSP-safe static validator, types and directory:

```text
node apps/librechat/generate-composition.mjs --v2
node apps/librechat/generate-composition.mjs --v2 --check
pnpm librechat:test
node apps/librechat/check-native.mjs
pnpm librechat:build-native
```

The native Runtime exposes directory/preparation tools only for newly frozen
Runs whose client explicitly declares V2. Preparation persists an immutable
presentation and server-owned exact handle. The independent teaching check and
atomic message/CAS/artifact publication remain mandatory. No composition uses
a fake item-bank pack or practice slot.

After a `prepare_learning_*` tool returns a completed candidate in an interactive
Run, the final answer must contain one complete `LearningReply` JSON. It either
selects the exact returned handle or explicitly chooses `interaction.type=none`
and explains the omission in `text`. A plain-text ending returns to the original
author for format repair before independent review; it cannot silently become
an accepted no-interaction reply. Repair reuses the existing preparation receipt.
The repair instruction follows the actual tool transcript as the latest message,
so the author corrects that completed preparation rather than responding again
to an older tool result.
This format-only correction uses the existing JSON response mode without tools;
semantic revisions retain the original preparation tools and independent checks.
Mixed prose/JSON and malformed interaction syntax retain a framing-specific
diagnostic. Their repair also closes tools and uses JSON output mode, carrying
the latest known reply separately from any older rejected candidate.
Runs without a prepared candidate retain ordinary text replies, and legacy
frozen roles retain their original interaction capabilities.

For capable guided turns, the author and independent reviewer select the surface
from the learner's activity, even when the learner does not name an artifact.
Practice uses a matching published owner, or queues the original supply chain
when none exists; a Markdown question does not replace its submit action.
Step-by-step or relational explanations can use a small checked visual
composition. Brief clarifications remain text-only, and free-reading, read-only
questions, pauses and existing permissions still apply. Executable candidates
follow their owner's exact environment contract: legacy Python IO, Python
projects and SQL may have qualified fixed runtimes without a release binding;
`project-stdio.v1` and `web-check.v1` require an authorized course release.

Execution packs contain three distinct cases: the exact public sample and two
private cases. Including the sample in `tests` is required by the owner contract;
the other cases remain hidden. Author and review instructions use this same
boundary. SQL `sql-table.v1` cells are canonical text with a parallel `types`
matrix, so `"35"` with kind `integer` differs from `"35"` with kind `text`.
Reviewers check the SQL-derived kind and canonical value together, alongside
boundary coverage and remediation alignment.

An explicit `set_topic` control starts a new teaching topic even when the selected
node is unchanged. Pending artifacts from earlier topics remain in history and
keep their own actions, but do not force the new topic into a read-only question
branch. Pause, resume and return-to-main retain the existing anchor behavior.

An `IsolatedPreview` uses the host's restricted iframe to render inert HTML/CSS
locally. Display and explicit preview updates do not require a Runner release or
environment authorization. Assessed web projects and executable workspaces keep
their original environment and execution-owner requirements.

The backend admits 24 local components, including all eight bounded
algorithm forms, code/file editing, HTML/CSS preview, structured data,
tree/relation/sequence views, parameters/playback, exact sources and cancel.
An additional explicit practice-action capability binds ordinary single-choice
`ChoiceAnswer`/`AnswerFeedback` and Python `ResultFeedback` to their original owners.
The separate response capability binds text, ordering, learner line-review and
review findings through the original item-bank and Assessment contracts. All 31
components now have an admission path, not exhaustive scenario acceptance. An
exhaustive renderer is not permission to grade, publish or execute.

V2 playback states are zero-based observation indices. The V2 adapter converts
them to the incumbent `StepPlayer` revealed-item count so a shared sequence and
step player identify the same observation. Old terminal-count drafts display the
last observation instead of losing their selection. Cancellation pauses local
autoplay without producing an execution or assessment result; the shared UI and
V1 count semantics remain unchanged.

`native-server.mjs` serves a separate full-client build and proxies only the
loopback Leornian public API. `native-overlay.mjs` leaves pinned upstream source
and the existing 5180 readonly preview unchanged. The host uses actual
Leornian anonymous sessions in an HttpOnly/SameSite cookie, owner-scoped
snapshots and SSE; frontend Authorization cannot choose a different actor.
Upstream business writes remain disabled. Start it explicitly with:

```text
# Provide a local, migrated Leornian API separately; this does not upgrade it.
$env:LEORNIAN_API_URL = 'http://127.0.0.1:8091'
node apps/librechat/native-server.mjs 5181
```

The host reads the build's entry document at startup. After rebuilding,
restart only the native host process you own, then reload its tab. The original
client `/health` check maps to actual local API readiness, including failures;
it is not an unconditional successful display fixture.

`NativeLearning.tsx` maps the accepted messages and native artifact identities
into the original client. Legacy single-choice/Python actions still delegate
to the existing owner and preserve one-shot V1 semantics. New explicitly bound
ordinary practice can use the V2 actions described below. Composition preview
remains local. Unsupported assessment events stay disabled, not simulated by
the preview store.
An existing conversation confirmed empty by the native snapshot shows the
input-ready empty state, not the upstream assumption that a persisted empty
conversation is still loading. Unknown or loading conversations keep their
original loading state.

`native-client.mjs` stores a command before dispatch and preserves uncertainty
across reloads. Recovery reads the original action or Turn-request receipt
using GET only, never automatically repeating POST. Drafts use actor, artifact
and immutable content identity, not action revision. Source/file identities
and readonly code are restored from accepted server content, while oversized
learner drafts remain recoverable but cannot be executed.

The source endpoint reads only the accepted component's exact citation and
current purpose/permission, with its real use/retention deadline. Committed
material permission events clear the displayed source before re-reading;
expiry also clears it. A failed read never switches to document head.
If the artifact itself is unreadable, its public summary can still expose the
original cancel command without rendering cached private content.

The native source host reserves reading width only while its actual reader is
open. It uses the incumbent reader classes and motion, not permanent dock space
when no source is being displayed.

## Original-owner practice actions

A new client declares both capabilities:

```json
{
  "presentation_capabilities": {
    "versions": ["learning_composition.v2"],
    "actions": ["learning_practice.v2"]
  }
}
```

Only that new Run receives `prepare_learning_practice_composition`. The
existing preparation tool remains local-only; old frozen Runs never acquire
this action tool. The model must first call `list_learning_artifact_candidates`
and propose `owner_bindings` with exact returned candidate IDs and component
IDs. The server supplies immutable public question/task metadata and verifies
original options, starter code, baseline, focus, publication and current scope.
Distinct owners cannot share a response state. Preparation is not publication
or exposure; the original independent check and atomic delivery remain required.

`NativePractice.tsx` renders server-owned prose and samples through trusted
before/after component slots. `native-practice.ts` maps only the permitted
ordinary `respond_component`/`run_component` intents; the host also supplies an
explicit `cancel_component_run` control bound to the exact current Attempt.
The payload cannot select another pack, slot, scorer, test set or runtime.
Component locks remain independent while the shared artifact revision provides
CAS. A direct original-owner update may have no artifact action ID; receipts
keep that null instead of fabricating an identity.

The original Assessment/Execution pipeline supports explicit
`python-practice.v2`: each changed program has an immutable Attempt, sequence,
exact previous Attempt, original test set and original Runner result. Pending
Attempts cannot fork. Identical code requires an explicit retry after an error;
cancellation records that error and does not resend or revive the old job.
Older grades, feedback exposures and V1 artifact result identities remain
unchanged. Qualification, transfer and formal Gate retain their original
one-shot policies. Closing a presentation does not upgrade a legacy in-flight
V1 job to V2 cancellation semantics.

The host restores the exact immutable-content draft, or the actual latest
submitted code when no draft exists. Changing code hides the old current-result
display but retains history. Only original owner receipts can display grades.
Refresh/SSE and history pagination are GET-only; no request is automatically
replayed. The attempt history retains cancelled, failed and successful versions,
and a completed practice does not write formal node progress.

Final host checks pass 67 Node tests, 19 DOM tests, strict TypeScript and the
full pinned-client build; the original desktop entry retains its 36 passing
tests. The native reader state no longer reserves dock width while closed,
and the final actual page has no horizontal document overflow.

Final focused backend evidence is 22 PostgreSQL/offline-model tests and two
additional real Docker tests, with overlapping batches not added together.
The in-app browser also exercised a two-owner composition through the actual
API, independent choice while Python queued, real Runner feedback, changed-code
draft isolation, refresh, cancellation and explicit retry. The history remained
`not_passed -> error -> passed`; the actual latest result was 3/3 with no node
progress. Model/question preparation used explicit offline fixtures, and Runner
claim/report used the original worker-shared use cases, not a broker test.
At that slice, four more owner paths were pending. Their subsequent response
integration is described next; SQL/multifile execution, full settings/old-feature
migration, genuine model quality, all scenarios and Tauri remain incomplete.

## Response formats and reader compatibility

New clients additionally declare `learning_responses.v1` in
`presentation_capabilities.actions`. Only those new Runs freeze
`list_learning_response_candidates` and `prepare_learning_response_composition`.
Existing listing/preparation tools and frozen Runs retain their original formats.
The original ItemBank author, public-only blind response, six reviews and
publication chain owns `kind=response` packs; the original Assessment owns locked
results. The V2 guide derives all 31 names/categories/ports from the same directory,
not from a three-recipe switch.

Published sources bind multiple `ChoiceAnswer`, prediction/reference `TextAnswer`,
`OrderingAnswer` and `LineRangeAnswer`; `ReviewFinding` displays only the committed
owner's corresponding line references after submission. Option/item ids, initial
order and immutable review code are checked. `answer_component` accepts only the
bound component's closed typed response, never caller pack/slot/gold/scorer/grade.
Original single-choice/Python bindings still require their separate capability.

Multiple selections compare exact id sets; prediction uses the published
`lines-rstrip.v1` rule, with an explicit empty-output confirmation; ordering
compares a complete permutation. Short answers keep `correct=null` and reference
feedback rather than fabricating semantic grading. Line location comparison does
not grade annotation reasons. The original Gate endpoints reject response packs.
Completion means the interaction ended, not mastery or node progress.

Detail GETs declare `?response_capability=learning_responses.v1`. An older reader
gets a clear 409 and can retain the public summary/cancel command; it is not given
a new question shape that its old renderer would interpret as Python or choice.
The native host restores locked owner text/order/annotations, preserves unsubmitted
drafts across SSE action revisions and refresh, and never resends on read.
Background item-author/reviewer turns remain in original task/audit history,
not in the learner message chain; actual user/assistant parent links are retained.

Final response evidence: 38 focused backend tests after the reader fix, 68 Node
and 23 DOM tests, strict native TypeScript and full client build pass. An earlier
67-test affected backend batch and intervening 37-test batch overlap and are not
added. The original entry retains its passing type check and 36 tests.
The in-app browser submitted all five owners, retained a deliberately incorrect
empty-output prediction and an ungraded short response, refreshed saved/pending
drafts and locked results, and displayed actual line findings only after submit.
Exactly five actions and five original results remain; node progress is zero.
Question/model preparation used explicit offline fixtures with persisted Runtime
checks and publication, not genuine provider quality, new Docker/broker or Tauri
acceptance. Migration 0037 is frozen only in the owned temporary database.
At that slice the composition tools consumed only already-published sources.

## Queued source supply (2026-11-05)

New teaching Runs supporting either original practice action capability freeze
`request_learning_practice_supply` and `get_learning_practice_supply`. The kind
must also match the Run's separate practice/response capability. The request is
bound to the exact confirmed node, not a guessed node in a goal/attempt context.
It accepts a command key, instruction and kind; a response request additionally
fixes `response_formats.practice_1` and `response_formats.practice_2`. It accepts
no question document, answer, test, grade or execution command.

The tool records the original ItemBank supply task and returns its real task/pack
identity. It does not start a second conversation Run while teaching is active.
The original coordinator yields to foreground work, then schedules author,
public-only blind solving, six reviews, repairs/revisions and publication.
Requested ordinary response formats survive revisions; old NULL requests keep
their original interpretation. The task preserves the initiating Run's model
configuration scope; user-owned profiles never require a shared developer key.
Parent cancellation fences a queued author. UNKNOWN never grants a resend.

The item author and all six reviewers receive the exact requested item kind and
learner instruction. Review checks this requested scope against the node and
sources; a single-kind pack does not have to implement every other artifact in a
broad node objective. Correctness, difficulty, independence, remediation and
security checks still apply. The blind solver receives public questions only,
without these instructions or private author/reviewer context.

Revision reviewers also receive the exact predecessor document as
`revision_baseline`. Preservation checks compare with that version, not a
same-named slot from an unrelated exposed pack. Exposure history still governs
answer-leakage checks; other reviewers' reports and blind answers remain private.

Authors and reviewers receive `revision_scope` with the actual predecessor ID,
publication fact, automatic policy and whether the instruction was inherited.
An unpublished private predecessor is not itself learner exposure. Automatic
quality repairs preserve sound, unaffected slots and address concrete findings;
the initial freshness request does not require redesigning every internal draft.
Actual exposure, explicit new revision instructions and all six quality checks
still govern the revised pack. Blind solving receives neither revision context
nor private predecessor content.

After a successor route is confirmed, already-published standalone supply
without a remediation/transfer supply demand remains completed. New consumption
uses the new route's own supply; an old ready but unpublished pack cannot be
published against the successor route.

The model must finish the current turn rather than polling and blocking its own
task. A later learner turn can read status, list actual published source handles,
prepare a composition and select only its checked exact_handle. A task id is not
a candidate and publication is not delivery or progress. This is not proactive
background teaching or automatic answering.

The existing native task panel groups original task versions in the current goal,
uses snapshot/SSE for status, and delegates cancel/explicit recovery to the
original pack endpoints. A browser scenario cancelled one queued task with zero
author stages, published another through all eight stages, introduced its two
actual candidates through Runtime checks, submitted prediction, restored an
unsubmitted ordering draft after refresh and explicitly submitted it. Exactly two
actions/results remain, with no node progress. Preparation/review used offline
HTTP fixtures. After a temporary screenshot-service failure on the task panel,
the final submitted composition was captured and visually inspected. This is a
scoped browser scenario, not all-scene, provider, broker, Runner or Tauri acceptance.

Migration 0038 is installed/frozen only in the owned temporary database.
The affected backend batch has 97 passes/one disabled Docker test; the final
tool/boundary batch after the BYOK admission adjustment has 24 passes. Counts
overlap, not add. Native 68 Node + 26 DOM, strict TypeScript and final build pass.

## Submitted Python code review (2026-11-05)

This is distinct from the published line-location exercise. A new client
explicitly declares `learning_code_review.v1`; only its new Run freezes
`prepare_learning_code_review_composition`. The exact `attempt` focus must
identify an already-public completed ordinary Python submission, not a pending
job, private qualification or guessed node. The server fills a read-only
`CodeBlock` with the entire original program and records the original public
task, Attempt and evaluation identity in the immutable presentation. Proposed
findings must quote the exact source line, including indentation.

The original teaching delivery independently checks the complete source,
task/result, locations and explanations. Its actual prepared handle must be
selected before atomic message/CAS/artifact publication. Only this accepted
delivery records assistance in the original exposure ledger; unselected,
cancelled or merely prepared comments are not delivered assistance. No original
evaluation document or grade is overwritten, and no new scorer, task engine or
code execution is created by reading a review.

Readers explicitly send `code_review_capability=learning_code_review.v1`.
Unsupported readers receive 409 while keeping summary/cancel. The native menu
lists current-node public submissions without submitting or calling a model.
The next explicit message uses that exact focus. The host renders one inline
annotated source view, with the owner's original result and no editable review
copy; repairs/runs remain in the original workspace. New Attempts and restored
drafts do not rebase an older review.

The in-app browser selected the original first failed submission, sent the
request through the real API, and received three full source lines plus two
comments on line 3 via snapshot/SSE. Its original result remained 1/3. An explicit
workspace edit then used the original Docker Runner's three cases and produced
a separate passed 3/3 Attempt; the review retained the old code/result, the
original evaluation stayed unchanged, one review assistance fact remained, and
node/execution progress stayed zero. The effective narrow viewport was 391 CSS
pixels with no page overflow. Model preparation/checking used offline HTTP
fixtures, not real provider quality; this was not broker or Tauri acceptance.

The affected backend batch recorded 51 passes; the final review/boundary/readiness
batch after the public-contract import correction recorded 13 passes, overlapping
rather than adding. Native 68 Node + 32 DOM, strict TypeScript, Ruff, contract
generation and final full build pass. Migration 0039 is frozen only in the owned
temporary database. SQL/multifile owner/Runner integration, other scenes and
provider/native acceptance remain unfinished; 31/31 admission is not full exit.
