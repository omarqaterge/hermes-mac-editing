"""Installer for the iTerm2 + zsh side of Mac-style terminal editing.

iTerm2 mappings (GlobalKeyMap, written via ``defaults`` while iTerm2 picks
them up on restart)::

  Shift+Left / Right          ESC [1;2D / [1;2C   char select
  Cmd+Shift+Left / Right      ESC [1;2H / [1;2F   line select
  Option+Shift+Left / Right   ESC [1;4D / [1;4C   word select
  Cmd+A / C / V              ESC [97/99/118;9u
  Cmd+X                      Ctrl+X              cut (stock TUI-compatible)
  Option+Backspace           Ctrl+W              delete previous word
  Cmd+Shift+Z                ESC [90;10u          redo

Untouched on purpose: Cmd+Left/Right (0x01/0x05 line nav), Option+Left/Right
(ESC b/f word nav), Cmd+Z (0x1f undo), all deletions, Cmd+C/V menu behaviour
outside the terminal grid is unchanged because these are key sends, not menu
rebinds. Note: with Cmd+C remapped, copying scrollback/output text must use
right-click > Copy or the Edit menu via mouse; Cmd+C now serves the editable
input (copy selection, or interrupt when there is none).
"""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import time
from pathlib import Path

DOMAIN = "com.googlecode.iterm2"

# key -> (action, text). Action 10 = Send Escape Sequence, 11 = Send Hex Codes.
MAPPINGS: dict[str, tuple[int, str]] = {
    "0xf702-0x220000": (10, "[1;2D"),
    "0xf703-0x220000": (10, "[1;2C"),
    "0xf702-0x320000": (10, "[1;2H"),
    "0xf703-0x320000": (10, "[1;2F"),
    "0xf702-0x2a0000": (10, "[1;4D"),
    "0xf703-0x2a0000": (10, "[1;4C"),
    "0x61-0x100000-0x0": (10, "[97;9u"),
    "0x63-0x100000-0x8": (10, "[99;9u"),
    "0x78-0x100000-0x7": (11, "0x18"),
    "0x76-0x100000-0x9": (10, "[118;9u"),
    "0x5a-0x100000-0x6": (10, "[90;10u"),
}

# Profile-level overrides. Profile mappings win over GlobalKeyMap, so Cmd+Z
# (pre-existing profile entry sending 0x1f, which the Hermes TUI does not
# recognize as undo) must be overridden here, not globally.
PROFILE_MAPPINGS: dict[str, tuple[int, str]] = {
    "0x7a-0x100000-0x6": (10, "[122;9u"),
    # Stock Hermes TUI recognizes Ctrl+W as delete-word-backward. Sending it
    # here avoids the ESC+DEL tokenizer ambiguity without patching Hermes.
    "0x7f-0x80000": (11, "0x17"),
}
ZSH_MARKER_BEGIN = "# >>> mac-editing (Hermes mac-editing plugin) >>>"
ZSH_MARKER_END = "# <<< mac-editing (Hermes mac-editing plugin) <<<"

ZSH_SNIPPET = """\
# >>> mac-editing (Hermes mac-editing plugin) >>>
# Standard macOS editing for the zsh command line (iTerm2 sends the sequences).
_mac_anchor() { (( REGION_ACTIVE )) || { MARK=$CURSOR; REGION_ACTIVE=1; } }
mac-select-left() { _mac_anchor; zle .backward-char; }; zle -N mac-select-left
mac-select-right() { _mac_anchor; zle .forward-char; }; zle -N mac-select-right
mac-select-line-left() { _mac_anchor; zle .beginning-of-line; }; zle -N mac-select-line-left
mac-select-line-right() { _mac_anchor; zle .end-of-line; }; zle -N mac-select-line-right
mac-select-word-left() { _mac_anchor; zle .backward-word; }; zle -N mac-select-word-left
mac-select-word-right() { _mac_anchor; zle .forward-word; }; zle -N mac-select-word-right
mac-select-all() { MARK=0; CURSOR=${#BUFFER}; REGION_ACTIVE=1; }; zle -N mac-select-all
mac-copy() {
  if (( REGION_ACTIVE )); then
    local a=$MARK b=$CURSOR
    (( a > b )) && { local t=$a; a=$b; b=$t; }
    print -rn -- "${BUFFER:$a:$((b - a))}" | pbcopy
  else
    zle send-break
  fi
}; zle -N mac-copy
mac-cut() {
  if (( REGION_ACTIVE )); then
    local a=$MARK b=$CURSOR
    (( a > b )) && { local t=$a; a=$b; b=$t; }
    print -rn -- "${BUFFER:$a:$((b - a))}" | pbcopy
    zle kill-region; REGION_ACTIVE=0
  fi
}; zle -N mac-cut
mac-paste() {
  (( REGION_ACTIVE )) && { zle kill-region; REGION_ACTIVE=0; }
  LBUFFER+=$(pbpaste)
}; zle -N mac-paste
mac-self-insert() {
  (( REGION_ACTIVE )) && { zle kill-region; REGION_ACTIVE=0; }
  zle .self-insert
}; zle -N self-insert mac-self-insert
mac-del-region() {
  if (( REGION_ACTIVE )); then zle kill-region; REGION_ACTIVE=0; else zle "$1"; fi
}
mac-backspace() { mac-del-region backward-delete-char; }; zle -N mac-backspace
mac-delete() { mac-del-region delete-char-or-list; }; zle -N mac-delete
mac-kill-word-b() { mac-del-region backward-kill-word; }; zle -N mac-kill-word-b
mac-kill-line-b() { mac-del-region backward-kill-line; }; zle -N mac-kill-line-b
mac-kill-line-f() { mac-del-region kill-line; }; zle -N mac-kill-line-f
# Plain movement must leave highlight mode: zsh keeps REGION_ACTIVE until
# something clears it, so every cursor move below drops the highlight first.
# The dotted call reaches the builtin being overridden; args pass through.
for _mac_w in forward-char backward-char beginning-of-line end-of-line \
    forward-word backward-word emacs-forward-word emacs-backward-word \
    up-line-or-history down-line-or-history; do
  eval "${_mac_w}() { REGION_ACTIVE=0; zle .${_mac_w} \"\$@\"; }"
  zle -N "${_mac_w}"
done
unset _mac_w
bindkey $'\\e[1;2D' mac-select-left
bindkey $'\\e[1;2C' mac-select-right
bindkey $'\\e[1;2H' mac-select-line-left
bindkey $'\\e[1;2F' mac-select-line-right
bindkey $'\\e[1;4D' mac-select-word-left
bindkey $'\\e[1;4C' mac-select-word-right
bindkey $'\\e[97;9u' mac-select-all
bindkey $'\\e[99;9u' mac-copy
# Cmd+X is translated to Ctrl+X so stock Hermes TUI can cut too.
bindkey '^X' mac-cut
# Keep the legacy CSI-u sequence working for existing terminal configs.
bindkey $'\\e[120;9u' mac-cut
bindkey $'\\e[118;9u' mac-paste
bindkey $'\\e[90;10u' redo
bindkey $'\\e[122;9u' undo
bindkey '^?' mac-backspace
bindkey '^H' mac-backspace
bindkey '^D' mac-delete
bindkey '^W' mac-kill-word-b
bindkey '^U' mac-kill-line-b
bindkey '^K' mac-kill-line-f
# <<< mac-editing (Hermes mac-editing plugin) <<<
"""


def _export_prefs() -> dict:
    raw = subprocess.check_output(["defaults", "export", DOMAIN, "-"])
    return plistlib.loads(raw)


def backup_dir() -> Path:
    path = Path.home() / ".config" / "mac-terminal-editing" / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def install_iterm() -> dict[str, dict]:
    """Write the GlobalKeyMap entries via ``defaults import``. Returns changes."""
    current = _export_prefs()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (backup_dir() / f"iterm-{stamp}.plist").write_bytes(plistlib.dumps(current))

    expected = plistlib.loads(plistlib.dumps(current))
    global_map = expected.setdefault("GlobalKeyMap", {})
    for key, (action, text) in MAPPINGS.items():
        global_map[key] = {"Action": action, "Text": text}
    try:
        profile_map = expected["New Bookmarks"][0].setdefault("Keyboard Map", {})
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Default iTerm2 profile not found: {exc}")
    for key, (action, text) in PROFILE_MAPPINGS.items():
        profile_map[key] = {"Action": action, "Text": text}
    # Cmd+Shift+A = iTerm's own Edit > Select All (whole terminal incl.
    # scrollback). Added as a macOS app shortcut so the menu owns it; our
    # Cmd+A mapping keeps serving the editable input. Existing entries kept.
    shortcuts = expected.setdefault("NSUserKeyEquivalents", {})
    shortcuts["Select All"] = "@$a"

    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".plist") as tmp:
        Path(tmp.name).write_bytes(plistlib.dumps(expected))
        subprocess.run(["defaults", "import", DOMAIN, tmp.name], check=True)

    actual = _export_prefs()
    if actual != expected:
        raise RuntimeError("iTerm2 preferences changed unexpectedly during install")
    return {key: actual["GlobalKeyMap"][key] for key in MAPPINGS}


def install_zsh() -> str:
    """Append (or refresh) the snippet block in ~/.zshrc. Returns an action label."""
    zshrc = Path.home() / ".zshrc"
    text = zshrc.read_text() if zshrc.exists() else ""
    if ZSH_MARKER_BEGIN in text:
        shutil.copy2(zshrc, backup_dir() / "zshrc.pre-mac-editing")
        before, _, rest = text.partition(ZSH_MARKER_BEGIN)
        _, _, after = rest.partition(ZSH_MARKER_END)
        zshrc.write_text(before + ZSH_SNIPPET + after)
        return "refreshed"
    with zshrc.open("a") as handle:
        if text and not text.endswith("\n"):
            handle.write("\n")
        handle.write(ZSH_SNIPPET)
    return "appended"


def status() -> list[str]:
    """Human-readable lines describing install state."""
    lines: list[str] = []
    try:
        prefs = _export_prefs()
        current = prefs.get("GlobalKeyMap", {})
        try:
            profile_current = prefs["New Bookmarks"][0].get("Keyboard Map", {})
        except (KeyError, IndexError):
            profile_current = {}
    except Exception as exc:
        return [f"iTerm2 preferences unreadable: {exc}"]
    missing = [
        key
        for key, (action, text) in MAPPINGS.items()
        if current.get(key) != {"Action": action, "Text": text}
    ]
    missing += [
        f"profile:{key}"
        for key, (action, text) in PROFILE_MAPPINGS.items()
        if profile_current.get(key) != {"Action": action, "Text": text}
    ]
    total = len(MAPPINGS) + len(PROFILE_MAPPINGS)
    if missing:
        lines.append(f"iTerm2: {len(missing)}/{total} mappings missing: {' '.join(missing)}")
    else:
        lines.append(f"iTerm2: all {total} mappings installed (restart iTerm2 to load).")
    shortcuts = prefs.get("NSUserKeyEquivalents", {})
    if shortcuts.get("Select All") == "@$a":
        lines.append("iTerm2: Cmd+Shift+A selects the whole terminal (Edit > Select All).")
    else:
        lines.append("iTerm2: Cmd+Shift+A shortcut NOT installed.")
    zshrc = Path.home() / ".zshrc"
    if zshrc.exists() and ZSH_MARKER_BEGIN in zshrc.read_text():
        lines.append("zsh: snippet installed in ~/.zshrc.")
    else:
        lines.append("zsh: snippet NOT in ~/.zshrc.")
    lines.append("Hermes CLI: active when this plugin is loaded (no core files touched).")
    lines.append("Hermes TUI/Ink: Cmd+Z/A/C/X/V + arrows via iTerm mappings (no core change).")
    return lines
