"""Automatic GitHub backup of groups.json.

After the group list changes, commits ONLY groups.json and pushes it to the
current branch's upstream (e.g. origin/main). Runs in a background thread,
batches rapid changes, and never raises: failures are reported through the
status callback and retried on the next change.

Disable by adding  "git_backup": false  to data/config.json.
"""
import os
import subprocess
import threading
from typing import Callable, List, Optional

DEBOUNCE_SECONDS = 3
GIT_TIMEOUT = 60


class GitBackup:
    def __init__(self, repo_dir: str, file_name: str = "groups.json",
                 on_status: Optional[Callable[[bool, str], None]] = None):
        self.repo_dir = repo_dir
        self.file_name = file_name
        self.on_status = on_status
        self._pending: List[str] = []
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()      # protects _pending/_timer
        self._run_lock = threading.Lock()  # one git sync at a time
        self.enabled = self._is_project_repo()

    # ---- public ---------------------------------------------------------
    def schedule(self, description: str) -> None:
        """Queue a backup; changes within a few seconds become one commit."""
        if not self.enabled:
            return
        with self._lock:
            self._pending.append(description)
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._sync)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        """Run a pending backup immediately (e.g. when the app closes)."""
        with self._lock:
            if not self._timer:
                return
            self._timer.cancel()
            self._timer = None
        self._sync()

    # ---- internals --------------------------------------------------------
    def _is_project_repo(self) -> bool:
        """True only if the project folder is the top of its own git repo.

        Prevents committing into an unrelated parent repository (e.g. one in
        the user's home folder) when the project was copied without .git.
        """
        try:
            top = self._git(["rev-parse", "--show-toplevel"]).strip()
        except RuntimeError:
            return False
        norm = lambda p: os.path.normcase(os.path.realpath(p))
        return norm(top) == norm(self.repo_dir)

    def _sync(self) -> None:
        with self._lock:
            descriptions, self._pending, self._timer = self._pending, [], None
        if not descriptions:
            return
        with self._run_lock:
            try:
                self._commit(descriptions)
                self._push()
            except Exception as e:  # never break the app over a backup
                self._report(False, f"Groups backup failed: {e}")

    def _commit(self, descriptions: List[str]) -> None:
        self._git(["add", "--", self.file_name])
        # Nothing to commit if groups.json matches the last commit
        if self._git_ok(["diff", "--cached", "--quiet", "--", self.file_name]):
            return
        if len(descriptions) == 1:
            message = f"Update groups: {descriptions[0]}"
        else:
            message = f"Update groups ({len(descriptions)} changes)\n\n" + \
                      "\n".join(f"- {d}" for d in descriptions)
        # The pathspec makes sure only groups.json is committed, even if
        # other files happen to be staged.
        self._git(["commit", "-q", "-m", message, "--", self.file_name])

    def _push(self) -> None:
        try:
            upstream = self._git(["rev-parse", "--abbrev-ref", "@{u}"]).strip()
        except RuntimeError:
            self._report(False, "Groups saved and committed, but this branch has no "
                                "GitHub branch to push to")
            return
        remote, _, branch = upstream.partition("/")
        # Push every unpushed commit, including ones from earlier failed attempts
        self._git(["push", "-q", remote, f"HEAD:{branch}"])
        self._report(True, "Groups backed up to GitHub")

    def _report(self, ok: bool, message: str) -> None:
        print(f"[git backup] {message}", flush=True)
        if self.on_status:
            try:
                self.on_status(ok, message)
            except Exception:
                pass

    def _git(self, args: List[str]) -> str:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # never hang on a prompt
        try:
            result = subprocess.run(
                ["git", *args], cwd=self.repo_dir, env=env,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=GIT_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except FileNotFoundError:
            raise RuntimeError("git is not installed")
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"git {args[0]} timed out (no internet?)")
        if result.returncode != 0:
            lines = [l.strip() for l in (result.stderr or result.stdout).splitlines() if l.strip()]
            # Prefer git's "fatal:"/"error:" line over trailing hints
            main = next((l for l in lines if l.startswith(("fatal:", "error:"))),
                        lines[0] if lines else f"git {args[0]} failed")
            raise RuntimeError(main.split(":", 1)[1].strip() if main.startswith(("fatal:", "error:")) else main)
        return result.stdout

    def _git_ok(self, args: List[str]) -> bool:
        try:
            self._git(args)
            return True
        except RuntimeError:
            return False
