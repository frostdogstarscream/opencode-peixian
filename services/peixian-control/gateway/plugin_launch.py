"""Apply process limits before replacing this process with the fixed Bun probe."""
import os
from pathlib import Path
import sys

if os.name == "posix":
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # Bun's JS engine reserves a large virtual address arena. The gateway
    # container cgroup is its hard memory boundary; RLIMIT_AS is for the parser.
bun = sys.argv[1]
os.execv(bun, [bun, str(Path(__file__).with_name("plugin_probe.mjs"))])
