"""Exercise the installed wheel outside the checkout, including private outputs."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    import classeur_nutrition
    if Path(classeur_nutrition.__file__).resolve().is_relative_to(ROOT):
        raise AssertionError("run with python -I after installing the wheel")
    with tempfile.TemporaryDirectory() as temp:
        outside = Path(temp)
        repository = outside / "checkout"
        repository.mkdir()
        subprocess.run(["git", "init", "--quiet", str(repository)], check=True)
        shutil.copyfile(ROOT / ".gitignore", repository / ".gitignore")

        def cli(*args, code=0):
            result = subprocess.run([sys.executable, "-I", "-m", "classeur_nutrition", *map(str, args)],
                                    cwd=outside, capture_output=True, text=True, encoding="utf-8", timeout=30)
            if result.returncode != code:
                raise AssertionError(result.stdout + result.stderr)
            return json.loads(result.stdout)

        source = repository / "dossiers" / "source"
        cli("init", "--dir", source, "--id", "fixture_client")
        example = ROOT / "examples/generaliste/quotidien_famille"
        shutil.copyfile(example / "profile.yaml", source / "profile.yaml")
        shutil.copytree(example / "weeks", source / "weeks", dirs_exist_ok=True)
        target = repository / "examples" / "client_fixture"
        commands = [("init", "--dir", target), ("clone", "--dir", target, "--source", source),
                    ("search", "--dir", source, "--output", target),
                    ("archive", "--dir", source, "--output", target)]
        for command in commands:
            result = cli(*command, code=2)
            if "destination privée refusée" not in result["erreur"] or target.exists():
                raise AssertionError("public destination was not rejected before writing")
        cli("clone", "--dir", repository / "dossiers" / "copy", "--source", source)
        visible = subprocess.check_output(["git", "-C", str(repository), "ls-files", "--others", "--exclude-standard", "-z"])
        if visible != b".gitignore\0":
            raise AssertionError("private files visible to Git")
    print("Installed package verified outside checkout: init, clone, private search/archive destinations.")


if __name__ == "__main__":
    main()
