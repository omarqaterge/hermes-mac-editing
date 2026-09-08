# Hermes Mac Editing

Standard macOS text editing for the terminal: Shift+arrow selection, Cmd+Shift+arrow line selection, Option+Shift+arrow word selection, Cmd+A/C/X/V/Z with the real macOS clipboard, and typing-to-replace — in zsh and in the Hermes classic CLI prompt, all inside iTerm2.

This is a user plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent). It attaches to Hermes through the public plugin surface only. No Hermes source files are modified, so updating Hermes never breaks it.

## How it works

Terminal emulators don't have native text fields, so macOS shortcuts can't work out of the box. This plugin closes the gap in two places.

First, iTerm2 key mappings translate your keypresses into standard terminal sequences. Arrow selection uses the same modified-arrow codes every xterm-compatible program understands. Cmd+letter shortcuts travel as Kitty keyboard-protocol sequences carrying the Cmd modifier.

Second, the receiving ends interpret those sequences. A zsh snippet (installed into your `~/.zshrc`) implements selection with zsh's own highlight engine plus clipboard through `pbcopy`/`pbpaste`. The Hermes side is a small Python module that plugs into the CLI's documented keybinding hook and adds only what's missing there: select-all, copy, cut, paste, and redo. Character, word, and line selection need no custom code because prompt_toolkit already implements shift-selection natively.

The Hermes Ink TUI (`hermes --tui`) needs no plugin code at all: it already understands these sequences, it just needed iTerm2 to actually send them. Cmd+Z was the missing one and is included.

## Requirements

- macOS with iTerm2
- zsh (with emacs keybindings, the default)
- Hermes Agent with prompt_toolkit-based classic CLI

## Install

Copy this directory to your Hermes user plugins and enable it:

```bash
cp -r hermes-mac-editing ~/.hermes/plugins/mac-editing
hermes plugins enable mac-editing
```

Then install the iTerm2 mappings and the zsh snippet:

```bash
hermes mac-editing install
```

Finally restart iTerm2 with Cmd+Q and reopen it, and open a fresh shell so the zsh snippet loads. You can verify everything with:

```bash
hermes mac-editing status
```

## Shortcuts

All shortcuts act on the line you're editing.

| Shortcut | Action |
|---|---|
| Shift+Left / Right | Select one character |
| Cmd+Shift+Left / Right | Select to start / end of line |
| Option+Shift+Left / Right | Select one word |
| Cmd+Left / Right | Move to start / end of line |
| Option+Left / Right | Move one word |
| Cmd+A | Select all |
| Cmd+C | Copy selection (interrupts when nothing is selected) |
| Cmd+X | Cut selection |
| Cmd+V | Paste, replacing any selection |
| Cmd+Z / Cmd+Shift+Z | Undo / redo |
| Typing or Backspace | Replaces the active selection |

## Known trade-offs

Remapping Cmd+C means it now serves the text you're editing: it copies the highlight, or sends an interrupt when there is no highlight (so Ctrl+C behavior is preserved). Copying older terminal output with Cmd+C no longer works; use right-click and Copy for scrollback instead.

These mappings live in iTerm2's settings, so they apply to iTerm2 sessions only. Other terminals are unaffected and won't gain these shortcuts.

## Uninstall

```bash
hermes plugins disable mac-editing
```

Then remove the `mac-editing` block from your `~/.zshrc`, and in iTerm2 delete the installed entries under Settings, or restore your backed-up preferences from `~/.config/mac-terminal-editing/backups/`. Restart iTerm2 afterwards.

## Files

- `plugin.yaml` — plugin manifest for Hermes discovery
- `__init__.py` — plugin entry point: attaches the key hook and provides `hermes mac-editing install|status`
- `mac_keys.py` — prompt_toolkit bindings (clipboard, select-all, redo)
- `iterm_install.py` — iTerm2 mapping writer and zsh snippet installer
- `test_mac_keys.py` — standalone checks, run with `python3 test_mac_keys.py`

## License

MIT. See LICENSE.
