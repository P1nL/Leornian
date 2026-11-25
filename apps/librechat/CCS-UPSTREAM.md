# CC Switch model-configuration components

Source: `farion1231/cc-switch`

Revision: `b184a88c99428571d718d10d1a1403e9502cd28b`

License: MIT, reproduced in `CCS-LICENSE.txt` and distributed as
`licenses/CC-Switch.txt` in connected/native frontend builds.

Only selected upstream files were fetched for this adaptation.

| Local file | Upstream source | Reused behavior |
| --- | --- | --- |
| `CCSProviderPresetSelector.tsx` | `src/components/providers/forms/ProviderPresetSelector.tsx` | Two-step picker/bar, provider rows, search, clear and custom entry |
| `CCSApiKeyInput.tsx` | `src/components/providers/forms/ApiKeyInput.tsx` | Controlled secret field, optional help/link, reveal/hide |
| `CCSModelPicker.tsx` | `src/components/providers/forms/FetchedModelPicker.tsx` | Draft selection, query, selected-only filter, add/remove on Apply and cancel |

Local adaptations replace CCS design tokens with scoped LibreChat tokens, use
Chinese labels, and remove CLI families, account login, routing, Tauri calls,
models.dev requests, model fetching, capacity footnotes and redundant subtitles.
The small provider catalog needs neither the multi-family navigation nor
portal/step context. Empty secrets are rejected by the host form; clearing a
secret also resets its reveal state.

`NativeModelProviders.tsx` is the Leornian host adapter. It reads the authoritative
model catalog, account region and key-management link from the Leornian API.
DeepSeek's official endpoint and `deepseek-flash` preset agree with the inspected
CCS `src/config/codexProviderPresets.ts` entry. Qwen retains Leornian's DashScope
Beijing contract and its dedicated OCR/Embedding/Rerank profiles; CCS's Codex
Responses configuration and newer Qianwen account catalog are not imported.

The host groups providers into teaching/planning and material processing. Each
group supports presets and a custom-provider form. Presets apply only the models
and roles in the selected group. Custom creation atomically saves the connection,
profile and matching role assignments through Leornian's existing configuration
owner; material setup preserves teaching assignments. Existing connections are
selected by ID; updating a Key only patches the credential.

Role assignment has its own settings tab. Provider rows retain direct editing
and explicit tests without an advanced-settings mode. Group headers use full-width
disclosures, pointer clicks omit the large focus ring, and controls retain
keyboard focus. Configuration writes do not invoke a model or create a test.
