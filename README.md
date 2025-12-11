## Experimental lora Manager Tab

This branch is an experimental **lora Manager** tab that is not part of the main plugin.

In this tab you can:
- Browse all discovered lora (from the ComfyUI server) with folder filtering and search.
- Edit per-lora trigger words, which are automatically appended when using lora autocomplete in the prompt.
- Configure a default strength for each lora; autocomplete inserts `<lora:name:strength>` using this value.

Notes:
- Still working on this will improve and make changes over time.
- Behavior and data format (`lora_triggers`, `lora_strength` metadata) are designed to remain compatible with the existing style/lora settings UI.>