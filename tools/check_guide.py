"""Check the guide's shell snippets without executing the documented actions."""
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
guides = sorted((ROOT / "docs").glob("*.md"))
text = '\n'.join(guide.read_text(encoding="utf-8") for guide in guides)
blocks = re.findall(r"```(bash|powershell)\n(.*?)```", text, re.S)
git_bash = Path("C:/Program Files/Git/bin/bash.exe")

with tempfile.TemporaryDirectory(prefix="mpp_guide_check_") as tmp:
    for index, (language, code) in enumerate(blocks, 1):
        suffix = ".sh" if language == "bash" else ".ps1"
        snippet = Path(tmp) / f"snippet_{index}{suffix}"
        snippet.write_text(code, encoding="utf-8-sig" if language == "powershell" else "utf-8")
        if language == "bash":
            if not git_bash.is_file():
                raise RuntimeError("Install Git for Windows or adapt git_bash for Bash syntax checks")
            command = [str(git_bash), "--noprofile", "--norc", "-n", snippet.as_posix()]
        else:
            parser = (
                "$parseErrors=$null; $parseTokens=$null; "
                "[System.Management.Automation.Language.Parser]::ParseFile("
                "'" + str(snippet).replace("'", "''") + "',"
                "[ref]$parseTokens,[ref]$parseErrors) | Out-Null; "
                "if ($parseErrors.Count) { $parseErrors | ForEach-Object { $_.Message }; exit 1 }"
            )
            command = ["powershell.exe", "-NoProfile", "-Command", parser]
        checked = subprocess.run(command, capture_output=True)
        if checked.returncode:
            raise RuntimeError(f"{language} block {index}: " + checked.stderr.decode(errors="replace") + checked.stdout.decode(errors="replace"))

for document in [ROOT / "README.md"] + guides:
    for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
        if "://" not in target and not target.startswith("#"):
            assert (document.parent / target.split("#", 1)[0]).exists(), target

print(f"OK: {len(blocks)} Bash/PowerShell snippets parse; Markdown links exist")
