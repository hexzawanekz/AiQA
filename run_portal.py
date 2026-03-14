#!/usr/bin/env python
"""Start the AiQA web portal (agentchattr fork with QA routes)."""

import sys
from pathlib import Path

# Ensure AiQA root is on path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "portal"))

# Run from portal directory so agentchattr imports work
import os
os.chdir(ROOT / "portal")

# Delegate to portal's run.py
from run import main

if __name__ == "__main__":
    main()
