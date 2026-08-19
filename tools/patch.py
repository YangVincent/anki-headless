"""Safe source editing. Validate every anchor first, then write once, atomically.

WHY THIS EXISTS. The ad-hoc pattern for editing a file was:

    def sub(old, new, label):
        assert s.count(old) == 1, label
        s = s.replace(old, new); print("ok", label)
    sub(a, b, "one"); sub(c, d, "two"); ...
    open(P, "w").write(s)          # <-- the write is LAST

It failed three times in one session, the same way each time. `sub` prints "ok"
*before* anything reaches disk, and the first bad anchor raises — so the earlier
substitutions are discarded while the transcript says they succeeded. The author then
believes an edit landed that never did. Twice the file was left correct-looking and
wrong; once it left two names undefined, which `py_compile` cannot catch because a
NameError is a runtime error.

This module fixes all three failure modes:

  * NOTHING is written until EVERY anchor is validated. One bad anchor writes nothing,
    and nothing is reported as done.
  * ALL anchor failures are reported together, with a near-miss hint, instead of
    stopping at the first.
  * The result is byte-compiled before it replaces the original, and Python files also
    get an undefined-name scan, which is what catches the NameError class.
  * The write is atomic (temp file + os.replace) and the original is backed up.

Usage:

    from tools.patch import Patch
    p = Patch("bot.py")
    p.sub(old, new, "what this changes")
    p.sub(old2, new2, "and this")
    p.apply()                 # raises PatchError and writes nothing if anything is off
"""
from __future__ import annotations

import ast
import builtins
import difflib
import io
import os
import py_compile
import shutil
import tempfile
from pathlib import Path


class PatchError(RuntimeError):
    """Nothing was written. The message lists every problem found."""


class Patch:
    def __init__(self, path, backup_dir=None):
        self.path = Path(path)
        self.original = io.open(self.path, encoding="utf-8").read()
        self.edits: list[tuple[str, str, str, int]] = []
        self.backup_dir = Path(backup_dir) if backup_dir else None

    # ── recording ─────────────────────────────────────────────────────
    def sub(self, old, new, label, count=1):
        """Record a substitution. `count` is how many matches are REQUIRED."""
        self.edits.append((old, new, label, count))
        return self

    def sub_all(self, old, new, label):
        """Record a substitution that must match at least once, any number of times."""
        self.edits.append((old, new, label, -1))
        return self

    # ── validation ────────────────────────────────────────────────────
    def _hint(self, old):
        """A near-miss line, so a whitespace or wording drift is obvious."""
        needle = old.strip().splitlines()[0][:60]
        if not needle:
            return ""
        best = difflib.get_close_matches(needle, self.original.splitlines(), n=1, cutoff=0.6)
        return f"\n        closest line in file: {best[0].strip()[:90]!r}" if best else ""

    def _validate(self):
        problems, seen = [], self.original
        for old, _new, label, want in self.edits:
            got = seen.count(old)
            if want == -1 and got == 0:
                problems.append(f"  [{label}] matched 0 times, expected at least 1"
                                + self._hint(old))
            elif want != -1 and got != want:
                problems.append(f"  [{label}] matched {got} times, expected {want}"
                                + (self._hint(old) if got == 0 else ""))
        return problems

    @staticmethod
    def _undefined_names(src, path):
        """Names LOADED anywhere but BOUND nowhere in the module.

        Deliberately permissive about scope: a name bound in any function counts as
        bound. Modelling scope properly would need closure and comprehension analysis,
        and getting it wrong produces false positives — the first version flagged a
        nested function's use of its enclosing function's variables and refused a
        correct patch.

        The class this must catch is narrower and simpler: a name that exists NOWHERE,
        which is what a deleted constant leaves behind. `REQUIRED_DECKS` and
        `ALLOWED_DECKS` survived a `py_compile` that way and would have raised
        NameError at startup.
        """
        tree = ast.parse(src, filename=str(path))
        # Python's implicit module globals are bound without an assignment anywhere.
        bound = set(dir(builtins)) | {
            "__file__", "__name__", "__doc__", "__package__", "__spec__",
            "__loader__", "__builtins__", "__debug__", "__path__", "__all__"}
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                bound.add(n.id)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(n.name)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                bound |= {a.asname or a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ExceptHandler) and n.name:
                bound.add(n.name)
            elif isinstance(n, (ast.Global, ast.Nonlocal)):
                bound |= set(n.names)
            elif isinstance(n, ast.arguments):
                bound |= {a.arg for a in n.posonlyargs + n.args + n.kwonlyargs}
                bound |= {a.arg for a in (n.vararg, n.kwarg) if a}
        return sorted({n.id for n in ast.walk(tree)
                       if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
                       and n.id not in bound})

    # ── applying ──────────────────────────────────────────────────────
    def apply(self, dry_run=False, check_names=True):
        """Validate everything, then write once. Raises PatchError and writes nothing
        if any anchor is wrong, the result does not compile, or a name is undefined."""
        problems = self._validate()
        if problems:
            raise PatchError(f"{self.path}: NOTHING WRITTEN — "
                             f"{len(problems)} of {len(self.edits)} anchors are wrong:\n"
                             + "\n".join(problems))

        out, applied = self.original, []
        for old, new, label, want in self.edits:
            n = out.count(old)
            out = out.replace(old, new)
            applied.append((label, n))

        if out == self.original:
            raise PatchError(f"{self.path}: every anchor matched but the text is "
                             "unchanged — the replacements are identical to the originals")

        is_py = self.path.suffix == ".py"
        if is_py:
            with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                             encoding="utf-8") as fh:
                fh.write(out); probe = fh.name
            try:
                py_compile.compile(probe, doraise=True, cfile=probe + "c")
                if check_names:
                    undefined = self._undefined_names(out, self.path)
                    if undefined:
                        raise PatchError(
                            f"{self.path}: NOTHING WRITTEN — the result has "
                            f"{len(undefined)} undefined name(s):\n  "
                            + "\n  ".join(undefined))
            except py_compile.PyCompileError as e:
                raise PatchError(f"{self.path}: NOTHING WRITTEN — the result does not "
                                 f"compile:\n  {e}") from None
            finally:
                for p in (probe, probe + "c"):
                    try: os.unlink(p)
                    except OSError: pass

        if dry_run:
            diff = difflib.unified_diff(self.original.splitlines(True), out.splitlines(True),
                                        f"a/{self.path}", f"b/{self.path}")
            print("".join(diff))
            print(f"DRY RUN — {len(applied)} edit(s) validated, nothing written.")
            return applied

        if self.backup_dir:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, self.backup_dir / (self.path.name + ".bak"))

        # atomic: write beside the target, then rename over it
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        io.open(tmp, "w", encoding="utf-8").write(out)
        os.replace(tmp, self.path)

        width = max(len(l) for l, _ in applied)
        for label, n in applied:
            print(f"  applied  {label:<{width}}  ({n} match{'es' if n != 1 else ''})")
        print(f"  WROTE    {self.path}  ({len(applied)} edit(s))")
        return applied
