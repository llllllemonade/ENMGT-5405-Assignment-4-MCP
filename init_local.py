"""Create a local .env secret once; never print, replace or commit that secret."""

from pathlib import Path

from cryptography.fernet import Fernet

from config import ROOT, load_settings


# Create a local encryption key once or validate and preserve the existing key.
def initialize(root: Path = ROOT) -> bool:
    target = root / ".env"
    if target.exists():
        load_settings(target)
        print("Existing .env validated and preserved; no key was replaced.")
        return False
    # Generate-key usage follows the official Fernet example:
    # https://cryptography.io/en/latest/fernet/
    key = Fernet.generate_key().decode("ascii")
    with target.open("x", encoding="utf-8") as output:
        output.write(
            "# Local secret: do not share or commit this file.\n"
            f"TASK_DATA_KEY={key}\n"
            "TASK_DB_PATH=data/assignments_secure.db\n"
            "TASK_RATE_LIMIT=10\n"
            "TASK_RATE_WINDOW_SECONDS=60\n"
        )
    print("Created .env with a fresh encryption key. The key was not printed.")
    return True


if __name__ == "__main__":
    initialize()
