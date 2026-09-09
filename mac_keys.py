"""Mac-style editing keybindings for the Hermes classic CLI prompt.

iTerm2 side (installed by ``hermes mac-editing install``) sends standard
xterm modified-arrow sequences, CSI-u sequences for Cmd+letter keys, and
stock control bytes where Hermes TUI already has the required action:

  Shift+Left/Right            -> ESC [ 1 ; 2 D/C   (char select, native)
  Cmd+Shift+Left/Right        -> ESC [ 1 ; 2 H/F   (line select, native)
  Option+Shift+Left/Right     -> ESC [ 1 ; 4 D/C   (Meta+Shift word select)
  Cmd+A / C / V               -> ESC [ 97/99/118 ; 9 u
  Cmd+X                       -> Cmd+C, Backspace  (cut)
  Option+Backspace            -> Ctrl+W            (delete previous word)
  Cmd+Shift+Z (redo)          -> ESC [ 90 ; 10 u

Arrow selection needs no custom code: prompt_toolkit's emacs bindings
implement shift-selection (extend, shrink, type-to-replace) natively.
Backspace is the exception: stock ``backward-delete-char`` ignores an
active selection and removes a single character, which also broke Cmd+X
(iTerm2 sends Cmd+C then Backspace: copy kept the selection, Backspace
deleted one char instead of the selection). This module registers the
CSI-u sequences the parser does not know, binds the
clipboard/select-all/redo handlers, and makes Backspace delete the
active selection.
"""

from __future__ import annotations

import subprocess

from prompt_toolkit.keys import Keys

CSI_U_SEQUENCES = {
    "\x1b[97;9u": (Keys.F20, "mac-select-all"),
    "\x1b[99;9u": (Keys.F21, "mac-copy"),
    "\x1b[120;9u": (Keys.F22, "mac-cut"),
    "\x1b[118;9u": (Keys.F23, "mac-paste"),
    "\x1b[90;10u": (Keys.F24, "mac-redo"),
}

# Option+Shift arrows must be Meta+Shift for the Ink TUI, but prompt_toolkit's
# word-selection handlers are named ControlShiftLeft/Right. Normalize only in
# the classic CLI parser; iTerm still sends the TUI-correct Meta+Shift bytes.
WORD_SELECT_SEQUENCES = {
    "\x1b[1;4D": Keys.ControlShiftLeft,
    "\x1b[1;4C": Keys.ControlShiftRight,
}

# Cmd+Z arrives as CSI-u super+z. Decode it straight to ControlUnderscore so
# the stock emacs ``c-_`` undo binding fires with no extra handler.
UNDO_SEQUENCE = "\x1b[122;9u"

# Decoded key pairs below. F20-F24 are unused by real terminals here: the
# pairs only ever arrive via the CSI-u sequences above (a human pressing
# Escape followed by a high function key is not a Hermes editing gesture).


def _ensure_sequences() -> None:
    """Teach prompt_toolkit's ANSI parser our CSI-u sequences (idempotent)."""
    from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
    from prompt_toolkit.keys import Keys

    for sequence, (fkey, _name) in CSI_U_SEQUENCES.items():
        ANSI_SEQUENCES.setdefault(sequence, (Keys.Escape, fkey))
    ANSI_SEQUENCES.update(WORD_SELECT_SEQUENCES)
    ANSI_SEQUENCES.setdefault(UNDO_SEQUENCE, Keys.ControlUnderscore)


def _pbcopy(text: str) -> bool:
    try:
        subprocess.run(["pbcopy"], input=text, text=True, check=True, timeout=5)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _pbpaste() -> str:
    try:
        result = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, check=False, timeout=5
        )
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _selection_text(buff) -> str:
    state = buff.selection_state
    if state is None:
        return ""
    start = min(buff.cursor_position, state.original_cursor_position)
    end = max(buff.cursor_position, state.original_cursor_position)
    return buff.text[start:end]


def register_macos_editing(kb) -> None:
    """Add Mac clipboard/select-all/redo bindings to a prompt_toolkit KeyBindings."""
    from prompt_toolkit.clipboard import ClipboardData
    from prompt_toolkit.filters import has_selection
    from prompt_toolkit.keys import Keys

    _ensure_sequences()

    @kb.add("escape", "f20", eager=True)
    def _select_all(event) -> None:
        buff = event.current_buffer
        if not buff.text:
            return
        buff.cursor_position = 0
        from prompt_toolkit.selection import SelectionType

        buff.start_selection(selection_type=SelectionType.CHARACTERS)
        buff.cursor_position = len(buff.text)

    @kb.add("escape", "f21", eager=True)
    def _copy(event) -> None:
        buff = event.current_buffer
        text = _selection_text(buff)
        if text:
            _pbcopy(text)
            try:
                event.app.clipboard.set_data(ClipboardData(text=text))
            except Exception:
                pass
            # Mac copy keeps the selection active.
        # No selection: no-op on macOS (Cmd+C should never exit or interrupt;
        # Ctrl+C alone handles interrupt/exit).

    @kb.add("escape", "f22", eager=True)
    def _cut(event) -> None:
        buff = event.current_buffer
        text = _selection_text(buff)
        if not text:
            return
        _pbcopy(text)
        try:
            event.app.clipboard.set_data(ClipboardData(text=text))
        except Exception:
            pass
        buff.cut_selection()

    @kb.add("escape", "f23", eager=True)
    def _paste(event) -> None:
        buff = event.current_buffer
        text = _pbpaste()
        if not text:
            return
        if buff.selection_state is not None:
            buff.cut_selection()
        buff.insert_text(text)

    @kb.add("escape", "f24", eager=True)
    def _redo(event) -> None:
        event.current_buffer.redo()

    # DEL (0x7f) arrives as ControlH. Stock backward-delete-char ignores an
    # active selection, so Cmd+X (copy, keep selection, Backspace) copied
    # then removed a single char. With a selection, remove the whole
    # selection instead — standard macOS behaviour. No selection: this
    # binding's filter misses and the stock handler runs untouched.
    # Registered last so it wins over the stock c-h binding when selected
    # (prompt_toolkit picks the last matching binding).
    @kb.add("c-h", filter=has_selection)
    def _delete_selection(event) -> None:
        event.current_buffer.cut_selection()
