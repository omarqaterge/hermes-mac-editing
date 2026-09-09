"""Standalone checks for the mac-editing plugin (run with the repo venv python).

Covers: parser sequences decode, select-all/copy/cut/paste/redo handlers
against real prompt_toolkit Buffer objects, and shift-selection natives.
Does not touch the Hermes checkout or iTerm2 preferences.
"""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

try:
    import prompt_toolkit  # noqa: F401
except ImportError:
    candidates = [
        Path.home() / ".hermes" / "hermes-agent" / "venv",
        Path(__file__).resolve().parent / ".venv",
    ]
    for venv in candidates:
        pkgs = next(venv.glob("lib/python*/site-packages"), None)
        if pkgs is not None and (pkgs / "prompt_toolkit").exists():
            sys.path.insert(0, str(pkgs))
            break

sys.path.insert(0, str(Path(__file__).resolve().parent))

from prompt_toolkit.buffer import Buffer  # noqa: E402
from prompt_toolkit.clipboard import InMemoryClipboard  # noqa: E402
from prompt_toolkit.document import Document  # noqa: E402
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES  # noqa: E402
from prompt_toolkit.key_binding import KeyBindings  # noqa: E402
from prompt_toolkit.keys import Keys  # noqa: E402
from prompt_toolkit.selection import SelectionState, SelectionType  # noqa: E402

import iterm_install  # noqa: E402
import mac_keys  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("ok  " if cond else "FAIL") + f" {name} {extra}")


def make_event(text, cursor=None, selected=False):
    buff = Buffer()
    buff.set_document(Document(text, cursor if cursor is not None else len(text)))
    if selected:
        buff.start_selection(selection_type=SelectionType.CHARACTERS)
    fed = []
    event = SimpleNamespace(
        current_buffer=buff,
        app=SimpleNamespace(clipboard=InMemoryClipboard()),
        key_processor=SimpleNamespace(feed=lambda kp, first=False: fed.append(kp)),
    )
    return event, fed


def handler_for(kb, *keys):
    for binding in kb.bindings:
        if tuple(binding.keys) == tuple(keys):
            return binding.handler
    return None


# 1. Parser knows our sequences after registration.
kb = KeyBindings()
mac_keys.register_macos_editing(kb)
for seq, (fkey, name) in mac_keys.CSI_U_SEQUENCES.items():
    check(f"parser:{name}", ANSI_SEQUENCES.get(seq) == (Keys.Escape, fkey))

# 2. Handlers registered on the decoded pairs.
KEYS_BY_NAME = {name: fkey for _, (fkey, name) in mac_keys.CSI_U_SEQUENCES.items()}
for name, fkey in KEYS_BY_NAME.items():
    check(f"bound:{name}", handler_for(kb, "escape", fkey) is not None)

# 3. Terminal mappings emit sequences understood by stock Hermes TUI,
# prompt_toolkit, and zsh without patching Hermes core.
check("mapping:option-shift-left-is-meta-shift",
      iterm_install.MAPPINGS["0xf702-0x2a0000"] == (10, "[1;4D"))
check("mapping:option-shift-right-is-meta-shift",
      iterm_install.MAPPINGS["0xf703-0x2a0000"] == (10, "[1;4C"))
check("mapping:cmd-x-is-copy-then-backspace",
      iterm_install.MAPPINGS["0x78-0x100000-0x7"] ==
      (11, "0x1b 0x5b 0x39 0x39 0x3b 0x39 0x75 0x7f"))
check("mapping:option-delete-is-control-w",
      iterm_install.PROFILE_MAPPINGS.get("0x7f-0x80000") == (11, "0x17"))

# 4. Native shift-selection sequences still parse. The plugin rebinds the
# prompt_toolkit interpretation of Meta+Shift arrows to its word-selection
# key names; stock Hermes TUI decodes the same bytes as Meta+Shift arrows.
for seq, key in [("\x1b[1;2D", Keys.ShiftLeft), ("\x1b[1;2H", Keys.ShiftHome),
                 ("\x1b[1;2F", Keys.ShiftEnd),
                 ("\x1b[1;4D", Keys.ControlShiftLeft),
                 ("\x1b[1;4C", Keys.ControlShiftRight)]:
    check(f"native:{key}", ANSI_SEQUENCES.get(seq) == key, repr(seq))

# 5. Select all.
event, _ = make_event("hello", cursor=2)
handler_for(kb, "escape", KEYS_BY_NAME["mac-select-all"])(event)
b = event.current_buffer
check("select-all:covers-buffer", b.text == "hello"
      and {b.cursor_position, b.selection_state.original_cursor_position} == {0, 5})

# 5. Copy keeps selection and hits the macOS clipboard.
subprocess.run(["pbcopy"], input="", text=True, check=True)
event, _ = make_event("hello world", cursor=5)
event.current_buffer.selection_state = SelectionState(
    original_cursor_position=11, type=SelectionType.CHARACTERS)
handler_for(kb, "escape", KEYS_BY_NAME["mac-copy"])(event)
clip = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
check("copy:pbcopy", clip == "hello world"[5:11], repr(clip))
check("copy:keeps-selection", event.current_buffer.selection_state is not None)
check("copy:internal-clipboard",
      event.app.clipboard.get_data().text == "hello world"[5:11])

# 6. Copy with no selection is a no-op (reserves interrupt/exit for Ctrl+C).
event, fed = make_event("hello", cursor=2)
handler_for(kb, "escape", KEYS_BY_NAME["mac-copy"])(event)
check("copy:no-selection-noop", len(fed) == 0)

# 7. Legacy CSI-u cut removes selection and copies it. The current iTerm2
# mapping performs cut as copy followed by Backspace so stock TUI can handle it.
event, _ = make_event("hello world", cursor=5)
event.current_buffer.selection_state = SelectionState(
    original_cursor_position=0, type=SelectionType.CHARACTERS)
handler_for(kb, "escape", KEYS_BY_NAME["mac-cut"])(event)
check("cut:text", event.current_buffer.text == " world",
      repr(event.current_buffer.text))
check("cut:clipboard",
      subprocess.run(["pbpaste"], capture_output=True, text=True).stdout == "hello")

# 8. Paste replaces an active selection.
subprocess.run(["pbcopy"], input="X", text=True, check=True)
event, _ = make_event("abcdef", cursor=4)
event.current_buffer.selection_state = SelectionState(
    original_cursor_position=1, type=SelectionType.CHARACTERS)
handler_for(kb, "escape", KEYS_BY_NAME["mac-paste"])(event)
check("paste:replaces-selection", event.current_buffer.text == "aXef",
      repr(event.current_buffer.text))

# 9. Redo delegates to the buffer (live undo stack is populated by the app).
calls = []
event, _ = make_event("ab")
event.current_buffer.redo = lambda: calls.append("redo")
handler_for(kb, "escape", KEYS_BY_NAME["mac-redo"])(event)
check("redo:delegates", calls == ["redo"])

# 10. Cmd+Z CSI-u decodes to ControlUnderscore (stock emacs c-_ undo fires).
check("undo:decodes-to-ctrl-underscore",
      ANSI_SEQUENCES.get(mac_keys.UNDO_SEQUENCE) == Keys.ControlUnderscore)

# 11. End-to-end Cmd+X as iTerm2 sends it: copy (keeps selection) then
# Backspace. Before the selection-aware Backspace binding this left
# "hell" + " world" minus one char; now the whole selection is removed.
subprocess.run(["pbcopy"], input="", text=True, check=True)
event, _ = make_event("hello world", cursor=5)
event.current_buffer.selection_state = SelectionState(
    original_cursor_position=0, type=SelectionType.CHARACTERS)
handler_for(kb, "escape", KEYS_BY_NAME["mac-copy"])(event)
c_h = next((b for b in kb.bindings if tuple(b.keys) == ("c-h",)), None)
check("cut-seq:backspace-binding-registered", c_h is not None)
check("cut-seq:backspace-binding-needs-selection", c_h is not None and c_h.filter is not None)
assert c_h is not None
c_h.handler(event)
check("cut-seq:text", event.current_buffer.text == " world",
      repr(event.current_buffer.text))
check("cut-seq:clipboard",
      subprocess.run(["pbpaste"], capture_output=True, text=True).stdout == "hello")

# 12. Standalone Backspace with a selection removes the whole selection.
event, _ = make_event("abcdef", cursor=4)
event.current_buffer.selection_state = SelectionState(
    original_cursor_position=1, type=SelectionType.CHARACTERS)
c_h.handler(event)
check("backspace:removes-selection", event.current_buffer.text == "aef",
      repr(event.current_buffer.text))

# 13. Profile links: every Hermes profile (-p, e.g. `dean`) resolves plugins
# from its own dir, so mac-editing must be symlinked there or CSI-u leaks as
# literal "[99;9u". Uses a fake home so the real ~/.hermes is untouched.
import tempfile
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    src = home / ".hermes" / "plugins" / "mac-editing"
    src.mkdir(parents=True)
    for prof in ("dean", "kbai-tutor"):
        (home / ".hermes" / "profiles" / prof / "plugins").mkdir(parents=True)
    # A real directory at the destination must never be clobbered.
    real = home / ".hermes" / "profiles" / "realdir" / "plugins" / "mac-editing"
    real.mkdir(parents=True)
    linked = iterm_install.ensure_profile_links(home=home)
    check("profiles:links-missing", sorted(linked) == ["dean", "kbai-tutor"], repr(linked))
    for prof in ("dean", "kbai-tutor"):
        dest = home / ".hermes" / "profiles" / prof / "plugins" / "mac-editing"
        check(f"profiles:{prof}-is-symlink", dest.is_symlink() and dest.resolve() == src.resolve())
    check("profiles:real-dir-preserved", real.is_dir() and not real.is_symlink())
    check("profiles:second-run-idempotent",
          iterm_install.ensure_profile_links(home=home) == [])
    # realdir keeps a real directory (never clobbered), so status must name it.
    check("profiles:status-names-unlinked",
          iterm_install.profile_link_status(home=home) == [
              "profiles: mac-editing missing in: realdir (run `hermes mac-editing install`)."],
          repr(iterm_install.profile_link_status(home=home)))

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
sys.exit(1 if FAIL else 0)
