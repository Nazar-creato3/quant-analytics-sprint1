#!/usr/bin/env python3
"""Remove backend host port 8000 binding — caddy uses internal docker network."""
from pathlib import Path
import re

p = Path("/home/user1/myapp/docker-compose.yml")
text = p.read_text(encoding="utf-8")
text = re.sub(r"\n    ports:\n      # - \"8000:8000\".*\n", "\n", text)
text = re.sub(r"\n    ports:\n      - \"8000:8000\"\n", "\n", text)
text = re.sub(r"\n    ports:\n      - \"5432:5432\"\n", "\n", text)
text = re.sub(r"\n    ports:\n      - \"6379:6379\"\n", "\n", text)
p.write_text(text, encoding="utf-8")
print("patched ports")
