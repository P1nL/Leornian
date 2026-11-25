# LibreChat Source Adaptation

Source repository: `https://github.com/LibreChat-AI/LibreChat.git`

Pinned commit: `f4154b649efa37e1345ccc517a4d8d1ed2178c82` (2026-10-31).

`ChatPane.tsx` adapts the slot-based pane/column/composer structure from
`packages/chat/src/components/pane/ChatPane.tsx` and the view selection from
`packages/chat/src/components/pane/view.ts`. Leornian uses its existing CSS
tokens and public state. It removes the upstream Jotai composer-lift state,
package imports and generation/data-provider assumptions. An existing empty
Leornian conversation is a valid landing state, not an indefinitely loading
generation.

No upstream backend, transport, credentials, Agent Runtime, execution or preview
implementation is included. The independent, unchanged source checkout is in
the ignored `.local/upstream/LibreChat-f4154b6` directory.

The source root LICENSE contains the MIT notice reproduced below. The root and
client package metadata separately declare ISC; that discrepancy is recorded,
not rewritten. This notice does not claim a license audit of unimported upstream
packages or their dependencies.

## Original Root License

MIT License

Copyright (c) 2026 LibreChat

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
