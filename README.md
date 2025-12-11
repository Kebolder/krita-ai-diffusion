## Krita AI Diffusion - Personal Merge Build

This version of the Krita AI Diffusion plugin is a personal merge of all my branches, experiments, and updates. It may change frequently, and parts of it will probably be opened as pull requests to the original plugin over time.

### Updates / releases

This fork no longer talks to the original Interstice server for plugin updates.  
The "Check for updates on startup" option now checks **this repository's latest GitHub release** (`Kebolder/krita-ai-diffusion`) and downloads the ZIP asset from there.

### Versioning

The plugin version uses the format:

`<main-version>-<my-version>`

For example:
- `1.43.0` = upstream/original plugin version  
- `1.0.0` = this fork’s own update version  
- Combined: `1.43.0-1.0.0`

### For original version and info goto https://github.com/Acly/krita-ai-diffusion

### New stuff
* Custom graph slider have inputs
* Resizing can be done from the Krita output node 
* Lora manager tab - A easy way to manage your ComfyUI's loras being able to add trigger words and strength when using prompt auto complete
* Custom graph saving support for overrides.
