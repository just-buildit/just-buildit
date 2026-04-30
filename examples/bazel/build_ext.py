import os
import shutil
import subprocess
from pathlib import Path

out = Path(os.environ["JUST_BUILDIT_OUTPUT_DIR"])
name = os.environ["JUST_BUILDIT_NAME"]
ext_suffix = os.environ["JUST_BUILDIT_EXT_SUFFIX"]

cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang") or "cc"

subprocess.run(
    [
        "bazel", "build", "//:greeter_so",
        f"--action_env=CC={cc}",
        f"--action_env=JUST_BUILDIT_INCLUDE_DIR={os.environ['JUST_BUILDIT_INCLUDE_DIR']}",
        f"--action_env=JUST_BUILDIT_LDFLAGS={os.environ['JUST_BUILDIT_LDFLAGS']}",
        f"--action_env=JUST_BUILDIT_LIBS={os.environ.get('JUST_BUILDIT_LIBS', '')}",
    ],
    check=True,
)

shutil.copy2("bazel-bin/greeter.so", out / (name + ext_suffix))
