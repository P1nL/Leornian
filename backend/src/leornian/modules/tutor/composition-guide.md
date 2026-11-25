# Learning composition selection

This guide describes presentation proposals, not tools or execution permissions.
Use it only when the host explicitly enables learning_composition.v1.
Keep conceptual explanations and source-backed claims in the assistant's message.
Keep only a short task prompt and current-step observations inside the composition.

## Select a supported recipe

- bfs: teach directed breadth-first traversal with a graph and one shared timeline.
  Add queue to explain discovery versus visiting; add code to relate steps to the
  algorithm; add variables when the learner needs the current values. The graph
  remains required. Node ids, edges and start come from this task, not a fixed example.
  Neighbors are explored in the supplied edge order. Disconnected nodes may remain
  unvisited. Cycles and self-loops are allowed; each node is enqueued once.
- code_review: ask the learner to select code lines, save reasons, then explicitly
  submit all saved annotations. Do not place reference answers or scoring results
  in this proposal. Saved local annotations are not an assessment submission.
- code_repair: provide the original code and public input/expected-output cases.
  The original code also becomes the initial editable draft. Choose diff to let
  the learner compare their draft with that baseline; choose cases to show the
  public examples. The host, not the proposal, decides whether checks are permitted.

## Boundaries

Output one JSON object matching the appended schema. Use only its named recipes
and view options; no React names, JavaScript callbacks, HTML, CSS, endpoints,
arbitrary bindings or model-generated animation frames. Do not put hints,
answers, hidden tests or private review findings into a public task proposal.
Use the existing source/citation mechanism; never invent a source identity.
If the requested visualization is unsupported, explain it in ordinary prose
instead of inventing a component or claiming an execution result.

Graph rendering and BFS snapshots are derived deterministically by the client.
Code strings are inert editable content, not scripts to execute in the UI.
The host must validate the proposal and bind it to exact public content and an
artifact revision before delivery. This schema does not publish a question,
select an assessment identity, permit a Runner action or certify correctness.
Results and per-line feedback arrive separately from the existing business owner.
Never turn an unknown result into a failed result, zero calls or permission to retry.

