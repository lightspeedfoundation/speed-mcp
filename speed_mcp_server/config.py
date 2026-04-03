from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.transport_security import TransportSecuritySettings


def _apply_ox_key_from_env_file(path: Path) -> None:
    """Apply 0X_API_KEY / OX_API_KEY from a .env file line-by-line.

    python-dotenv (like Node's dotenv) often skips variable names that start with a digit.
    Lightspeed-CLI does the same manual pass — see env.ts applyNumericPrefixedKeys.
    """
    if not path.is_file():
        return
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return
    raw = raw.lstrip("\ufeff")
    for line in raw.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        idx = trimmed.find("0X_API_KEY=")
        idx_alt = trimmed.find("OX_API_KEY=")
        key_start = idx if idx >= 0 else idx_alt if idx_alt >= 0 else -1
        if key_start < 0:
            continue
        eq = trimmed.index("=", key_start)
        rest = trimmed[eq + 1 :].strip()
        if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in "\"'":
            rest = rest[1:-1]
        rest = rest.replace('\\"', '"').replace("\\\\", "\\").strip()
        if rest:
            os.environ["0X_API_KEY"] = rest
            os.environ["OX_API_KEY"] = rest
        return


# Load .env from server directory or current working directory
_env_path = Path(__file__).resolve().parent.parent / ".env"
_apply_ox_key_from_env_file(_env_path)
load_dotenv(_env_path)
load_dotenv()
_apply_ox_key_from_env_file(Path.cwd() / ".env")

ALCHEMY_API_KEY = os.environ.get("ALCHEMY_API_KEY", "").strip()
# Match Speed CLI: OX_API_KEY alias; 0X_API_KEY may only appear via _apply_ox_key_from_env_file above.
OX_API_KEY = os.environ.get("0X_API_KEY", "").strip() or os.environ.get("OX_API_KEY", "").strip()
SQUID_INTEGRATOR_ID = os.environ.get("SQUID_INTEGRATOR_ID", "").strip()
OPENSEA_API_KEY = os.environ.get("OPENSEA_API_KEY", "").strip()
# Optional: override RPC for Base (8453) only, same as Speed CLI's rpc.js
RPC_URL = os.environ.get("RPC_URL", "").strip()

# MCP server transport: stdio (default, for Cursor spawning) or streamable-http (for remote clients)
MCP_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
MCP_HOST = os.environ.get("MCP_HOST", "0.0.0.0").strip()
MCP_PORT = int(os.environ.get("MCP_PORT", "8000").strip() or "8000")
# Comma-separated public hostnames when behind a reverse proxy (e.g. mcp.ispeed.pro).
# Required for Streamable HTTP + loopback bind: Nginx sends Host: your domain; the MCP
# SDK's DNS rebinding protection otherwise returns 421 Invalid Host header.
MCP_ALLOWED_HOSTS = os.environ.get("MCP_ALLOWED_HOSTS", "").strip()


def get_transport_security_settings() -> TransportSecuritySettings | None:
    """When binding to loopback, add MCP_ALLOWED_HOSTS so nginx can forward the real Host header."""
    if MCP_HOST not in ("127.0.0.1", "localhost", "::1"):
        return None
    extra = [x.strip() for x in MCP_ALLOWED_HOSTS.split(",") if x.strip()]
    if not extra:
        return None
    allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    allowed_origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    for h in extra:
        allowed_hosts.append(h)
        allowed_hosts.append(f"{h}:*")
        for scheme in ("https", "http"):
            allowed_origins.append(f"{scheme}://{h}")
            allowed_origins.append(f"{scheme}://{h}:*")
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


# Alchemy: same pattern as Speed CLI — https://${prefix}-mainnet.g.alchemy.com/v2/${apiKey}
ALCHEMY_CHAIN_PREFIX: dict[int, str] = {
    1: "eth-mainnet",
    8453: "base-mainnet",
    10: "opt-mainnet",
    42161: "arb-mainnet",
    137: "polygon-mainnet",
    56: "bnb-mainnet",
}


def get_speed_env() -> dict[str, str]:
    """Env vars to set when running speed-cli. PRIVATE_KEY must remain in ~/.speed/.env."""
    env: dict[str, str] = {}
    if ALCHEMY_API_KEY:
        env["ALCHEMY_API_KEY"] = ALCHEMY_API_KEY
    if OX_API_KEY:
        env["0X_API_KEY"] = OX_API_KEY
    if SQUID_INTEGRATOR_ID:
        env["SQUID_INTEGRATOR_ID"] = SQUID_INTEGRATOR_ID
    if OPENSEA_API_KEY:
        env["OPENSEA_API_KEY"] = OPENSEA_API_KEY
    # Base (8453) override, same as Speed CLI getRpcUrl(8453)
    if RPC_URL:
        env["RPC_URL"] = RPC_URL
    return env


def get_alchemy_rpc_url(chain_id: int) -> str:
    """RPC URL for chain: RPC_URL for Base (8453) when set, else Alchemy. Matches Speed CLI rpc.js."""
    if chain_id == 8453 and RPC_URL:
        return RPC_URL
    prefix = ALCHEMY_CHAIN_PREFIX.get(chain_id)
    if not prefix or not ALCHEMY_API_KEY:
        raise ValueError(f"Unsupported chainId {chain_id} or missing ALCHEMY_API_KEY")
    return f"https://{prefix}.g.alchemy.com/v2/{ALCHEMY_API_KEY}"
