"""
Tests for deploy/secrets/fortress-load-secrets.

The script is invoked as a subprocess with PATH overridden to point at
a fake `pass` binary written into a tmp_path. No real `pass` or GPG is
involved.

The fake `pass` honours these env vars per invocation:
  FAKE_PASS_OK_PATHS    — comma-separated pass paths that succeed
  FAKE_PASS_VALUES      — pipe-separated values, one per OK path (in order)
  FAKE_PASS_FAIL_PATHS  — comma-separated pass paths that exit 1
                          (and write a failure message to stderr that
                          INCLUDES a never-real-secret canary so tests
                          can assert it never escapes)
"""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "deploy" / "secrets" / "fortress-load-secrets.sh"
)


# ─────────────────────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────────────────────

# Sentinel that should NEVER appear in stdout or stderr — we plant it
# inside the fake `pass` binary's "pass-failure-mode" stderr so tests
# can assert leak-free error reporting.
_PASS_STDERR_CANARY = "leaked-from-pass-stderr-NOT-OK"


def _write_fake_pass(tmp_path: Path) -> Path:
    """Write a fake `pass` shim into tmp_path/bin and return that bin dir."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake_pass = bin_dir / "pass"
    fake_pass.write_text(textwrap.dedent(f"""\
        #!/usr/bin/env bash
        # Fake `pass` for fortress-load-secrets tests.
        # Usage emulated: `pass show <path>`
        if [[ "$1" != "show" || -z "${{2:-}}" ]]; then
          echo "fake-pass: usage" >&2
          exit 64
        fi
        path="$2"
        ok="${{FAKE_PASS_OK_PATHS:-}}"
        fail="${{FAKE_PASS_FAIL_PATHS:-}}"
        IFS=',' read -ra fail_arr <<< "$fail"
        for f in "${{fail_arr[@]}}"; do
          if [[ "$f" == "$path" ]]; then
            # Pass would normally print a real diagnostic here. Plant a
            # canary so tests can assert the loader never propagates
            # `pass`'s stderr into its own output.
            echo "{_PASS_STDERR_CANARY} ($path)" >&2
            exit 1
          fi
        done
        IFS=',' read -ra ok_arr <<< "$ok"
        IFS='|' read -ra val_arr <<< "${{FAKE_PASS_VALUES:-}}"
        for i in "${{!ok_arr[@]}}"; do
          if [[ "${{ok_arr[$i]}}" == "$path" ]]; then
            printf '%s\\n' "${{val_arr[$i]:-}}"
            exit 0
          fi
        done
        echo "fake-pass: no entry $path" >&2
        exit 1
    """))
    fake_pass.chmod(0o755)
    return bin_dir


def _run_loader(
    tmp_path: Path,
    manifest_text: str,
    *,
    ok_paths: list[str] | None = None,
    ok_values: list[str] | None = None,
    fail_paths: list[str] | None = None,
    output_to_file: bool = True,
) -> subprocess.CompletedProcess:
    """Invoke fortress-load-secrets with a tmp manifest + fake pass."""
    bin_dir = _write_fake_pass(tmp_path)
    manifest = tmp_path / "secrets.manifest"
    manifest.write_text(manifest_text)

    env = {
        # Keep PATH minimal but include our fake `pass`. Need /usr/bin
        # for mktemp/install/printf etc.
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "FAKE_PASS_OK_PATHS": ",".join(ok_paths or []),
        "FAKE_PASS_VALUES": "|".join(ok_values or []),
        "FAKE_PASS_FAIL_PATHS": ",".join(fail_paths or []),
        "HOME": str(tmp_path),
    }
    cmd = ["bash", str(SCRIPT_PATH), "--manifest", str(manifest)]
    if output_to_file:
        cmd += ["--output", str(tmp_path / "out.env")]
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, timeout=20,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadSecretsExportsFromPass:
    def test_load_secrets_exports_from_pass(self, tmp_path: Path):
        """Manifest with N entries → output file has N VAR=value lines."""
        manifest = textwrap.dedent("""\
            MAILPLUS_PASSWORD_LEGAL                fortress/mailboxes/legal-cpanel
            MAILPLUS_PASSWORD_GARY                 fortress/mailboxes/gary-crog
            MAILPLUS_PASSWORD_INFO                 fortress/mailboxes/info-crog
            MAILPLUS_PASSWORD_GARY_GARYKNIGHT_COM  fortress/mailboxes/gary-garyknight
        """)
        result = _run_loader(
            tmp_path,
            manifest,
            ok_paths=[
                "fortress/mailboxes/legal-cpanel",
                "fortress/mailboxes/gary-crog",
                "fortress/mailboxes/info-crog",
                "fortress/mailboxes/gary-garyknight",
            ],
            ok_values=[
                "real-legal-pw",
                "real-gary-pw",
                "real-info-pw",
                "real-gk-pw",
            ],
        )
        assert result.returncode == 0, (
            f"loader exited {result.returncode}: stderr={result.stderr!r}"
        )

        out = (tmp_path / "out.env").read_text()
        # Each var appears exactly once with single-quoted value.
        assert "MAILPLUS_PASSWORD_LEGAL='real-legal-pw'\n" in out
        assert "MAILPLUS_PASSWORD_GARY='real-gary-pw'\n" in out
        assert "MAILPLUS_PASSWORD_INFO='real-info-pw'\n" in out
        assert "MAILPLUS_PASSWORD_GARY_GARYKNIGHT_COM='real-gk-pw'\n" in out
        # Output file is mode 0600 — secrets must not be world-readable.
        mode = (tmp_path / "out.env").stat().st_mode & 0o777
        assert mode == 0o600, f"out.env mode is 0{mode:o}, expected 0600"

    def test_load_secrets_handles_special_chars_in_values(self, tmp_path: Path):
        """A password with a single quote and a space round-trips intact."""
        manifest = "PW    fortress/test/special\n"
        secret = "p'ass with space and \"quote\""
        result = _run_loader(
            tmp_path,
            manifest,
            ok_paths=["fortress/test/special"],
            ok_values=[secret],
        )
        assert result.returncode == 0, result.stderr
        # Re-source the file and confirm the value reaches the env intact.
        env_file = tmp_path / "out.env"
        sourced = subprocess.run(
            ["bash", "-c", f'set -a; source "{env_file}"; printf %s "$PW"'],
            capture_output=True, text=True, timeout=10,
        )
        assert sourced.returncode == 0
        assert sourced.stdout == secret


class TestLoadSecretsFailsOnMissingPassEntry:
    def test_load_secrets_fails_on_missing_pass_entry(self, tmp_path: Path):
        """One failing entry → loader exits 1 and stderr names the var + path."""
        manifest = textwrap.dedent("""\
            VAR_A    fortress/ok/path
            VAR_B    fortress/missing/path
            VAR_C    fortress/ok/other
        """)
        result = _run_loader(
            tmp_path,
            manifest,
            ok_paths=["fortress/ok/path", "fortress/ok/other"],
            ok_values=["a-val", "c-val"],
            fail_paths=["fortress/missing/path"],
        )
        assert result.returncode == 1
        assert "VAR_B" in result.stderr
        assert "fortress/missing/path" in result.stderr
        # Loader gives up on the first failure, so the output file must
        # not exist (or, if mktemp created it, must not contain VAR_C).
        out_path = tmp_path / "out.env"
        if out_path.exists():
            assert "VAR_C" not in out_path.read_text()


class TestLoadSecretsNeverPrintsSecretValues:
    def test_load_secrets_never_prints_secret_values(self, tmp_path: Path):
        """
        Failure path must not echo secret values OR pass's own stderr
        (which can include diagnostic strings the operator never expects
        to see in the journal).
        """
        manifest = "VAR_X    fortress/will/fail\n"
        result = _run_loader(
            tmp_path,
            manifest,
            fail_paths=["fortress/will/fail"],
        )
        assert result.returncode == 1
        # The var name and pass path are OK to print.
        assert "VAR_X" in result.stderr
        # The canary planted in fake-pass's stderr must NOT appear in
        # the loader's stderr — the loader silences `pass` stderr
        # (`2>/dev/null`) so error text stays under our control.
        assert _PASS_STDERR_CANARY not in result.stderr
        assert _PASS_STDERR_CANARY not in result.stdout

    def test_load_secrets_never_prints_value_in_success_stderr(self, tmp_path: Path):
        """Successful resolution → secret value goes to the output file ONLY."""
        secret = "this-is-the-secret-value"
        manifest = "VAR_OK    fortress/ok\n"
        result = _run_loader(
            tmp_path,
            manifest,
            ok_paths=["fortress/ok"],
            ok_values=[secret],
        )
        assert result.returncode == 0
        # Secret value must not leak into stderr.
        assert secret not in result.stderr
        # And not into stdout when we wrote to a file.
        assert secret not in result.stdout
        # It DOES appear in the output file — that's the whole point.
        assert secret in (tmp_path / "out.env").read_text()


class TestManifestParseIgnoresCommentsAndBlanks:
    def test_manifest_parse_ignores_comments_and_blanks(self, tmp_path: Path):
        """Comments + blank lines ignored; mid-line padding/tabs tolerated."""
        manifest = textwrap.dedent("""\
            # File header comment
            #   indented comment

            VAR_ONE\tfortress/one

                # mid-file comment with indent
            VAR_TWO        fortress/two

            \tVAR_THREE\t\tfortress/three
            # trailing comment
        """)
        result = _run_loader(
            tmp_path,
            manifest,
            ok_paths=["fortress/one", "fortress/two", "fortress/three"],
            ok_values=["v1", "v2", "v3"],
        )
        assert result.returncode == 0, result.stderr
        out = (tmp_path / "out.env").read_text()
        # All three resolved — comments and blank lines did not break parsing.
        assert "VAR_ONE='v1'\n" in out
        assert "VAR_TWO='v2'\n" in out
        assert "VAR_THREE='v3'\n" in out
        # And nothing else slipped in (no comment text in output).
        assert "#" not in out
        assert out.count("=") == 3
