"""Hermes plugin: standard macOS text editing for the classic CLI prompt.

Attaches to the documented ``CLITuiMixin._register_extra_tui_keybindings``
extension hook at runtime (no core files touched) and provides
``hermes mac-editing install|status`` for the iTerm2 + zsh side.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_HOOK_FLAG = "_mac_editing_hook_installed"


def _install_key_hook() -> str:
    try:
        from hermes_cli import cli_tui_mixin as mixin
    except Exception as exc:
        return f"key hook skipped (no CLI mixin available: {exc})"
    if getattr(mixin.CLITuiMixin._register_extra_tui_keybindings, _HOOK_FLAG, False):
        return "key hook already installed"
    original = mixin.CLITuiMixin._register_extra_tui_keybindings

    def _wrapped(self, kb, *args, **kwargs):
        original(self, kb, *args, **kwargs)
        try:
            from mac_keys import register_macos_editing

            register_macos_editing(kb)
        except Exception:
            pass

    setattr(_wrapped, _HOOK_FLAG, True)
    mixin.CLITuiMixin._register_extra_tui_keybindings = _wrapped
    return "key hook installed"


def _setup_argparse(subparser) -> None:
    subs = subparser.add_subparsers(dest="mac_editing_command")
    subs.add_parser("install", help="Install iTerm2 mappings and the zsh snippet")
    subs.add_parser("status", help="Show install state")


def _handle_cli(args) -> int:
    from iterm_install import ensure_profile_links, install_iterm, install_zsh, status

    cmd = getattr(args, "mac_editing_command", None)
    if cmd == "install":
        applied = install_iterm()
        print(f"iTerm2: wrote {len(applied)} key mappings (restart iTerm2 with Cmd+Q to load).")
        print(f"zsh: snippet {install_zsh()} in ~/.zshrc (open a new shell to load).")
        linked = ensure_profile_links()
        if linked:
            print(f"profiles: linked mac-editing into: {' '.join(linked)}.")
        else:
            print("profiles: mac-editing already linked into all profiles.")
        print("Hermes CLI: keybindings attach automatically via this plugin.")
        print("Hermes TUI/Ink: Cmd+Z/A/C/X/V + arrows via iTerm mappings.")
        return 0
    for line in status():
        print(line)
    return 0


def register(ctx) -> None:
    _install_key_hook()
    try:
        from iterm_install import ensure_profile_links

        ensure_profile_links()
    except Exception:
        pass
    ctx.register_cli_command(
        name="mac-editing",
        help="Standard macOS text editing for iTerm2 + zsh + Hermes CLI",
        setup_fn=_setup_argparse,
        handler_fn=_handle_cli,
    )
