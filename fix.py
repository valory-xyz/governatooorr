import re
from pathlib import Path

file_path = Path("packages/valory/contracts/delegate/build/Delegate.json")
with open(file_path, "rb") as file:
    fixed_content = re.sub(b"\r\n", b"\n", file.read(), flags=re.M).decode()

file_path.write_text(fixed_content)
