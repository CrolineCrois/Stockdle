"""Every test session gets its own data directory, database and mock judge."""

import os
import shutil
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="sip-test-"))
_repo_seed = Path(__file__).resolve().parents[2] / "data" / "seed"
shutil.copytree(_repo_seed, _tmp / "seed")
os.environ["SIP_DATA_DIR"] = str(_tmp)
os.environ["SIP_DB"] = str(_tmp / "test.db")
os.environ["SIP_JUDGE"] = "mock"
os.environ["SIP_METER"] = "style"        # no verifier model download in tests
os.environ["SIP_CHECK_FRESH"] = "0"         # no Google News calls in tests
for _k in ("SIP_SUBMITS_PER_IP_PER_MIN", "SIP_PLAYERS_PER_IP_PER_HOUR", "SIP_SUBMITS_PER_HOUR",
           "SIP_CHECKS_PER_IP_PER_MIN", "SIP_CHECKS_PER_HOUR"):
    os.environ[_k] = "0"                  # 0 = no limit; test_rate_limits turns them on
os.environ.pop("ANTHROPIC_API_KEY", None)
