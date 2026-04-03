"""
MCP server that holds 0x, Alchemy, Squid, OpenSea API keys.
Agents use speed-cli without configuring those keys; PRIVATE_KEY stays in ~/.speed/.env.
"""
from __future__ import annotations

import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from .config import (
    ALCHEMY_API_KEY,
    MCP_HOST,
    MCP_PORT,
    MCP_TRANSPORT,
    OX_API_KEY,
    OPENSEA_API_KEY,
    SQUID_INTEGRATOR_ID,
    get_alchemy_rpc_url,
    get_speed_env,
    get_transport_security_settings,
)
from .crypto_utils import encrypt_env_for_client

# When MCP_TRANSPORT=streamable-http, host/port are used so remote clients can connect
mcp = FastMCP(
    "speed-mcp-server",
    instructions="API keys for speed-cli (0x, Alchemy, Squid, OpenSea). Wallet PRIVATE_KEY stays local in ~/.speed.",
    host=MCP_HOST,
    port=MCP_PORT,
    transport_security=get_transport_security_settings(),
)


@mcp.tool()
async def get_speed_env_vars(client_public_key_pem: str) -> dict[str, Any]:
    """Return the env vars (ALCHEMY_API_KEY, 0X_API_KEY, etc.) encrypted for the client.

    Requires client_public_key_pem (RSA public key in PEM format). The env is encrypted so only
    the client with the matching private key can decrypt it. Speed-CLI sends its public key,
    receives encrypted_key_b64, nonce_b64, ciphertext_b64; decrypts locally with ~/.speed/speed_mcp_key.pem
    and applies to process.env. PRIVATE_KEY must remain only in ~/.speed/.env; never send it to this server.
    """
    if not client_public_key_pem or not client_public_key_pem.strip():
        return {"error": "client_public_key_pem is required (RSA public key PEM). Keys are always returned encrypted."}
    env = get_speed_env()
    _log_env_keys(env, encrypted=True)
    try:
        encrypted = encrypt_env_for_client(env, client_public_key_pem.strip())
        return {
            "message": "Encrypted env for client. Decrypt with the matching RSA private key (e.g. in Speed-CLI).",
            **encrypted,
        }
    except Exception as e:
        return {"error": f"Encryption failed: {e}"}


def _log_env_keys(env: dict[str, Any], *, encrypted: bool) -> None:
    """Log which env keys are present and non-empty (values never logged). Set MCP_DEBUG=1 to enable."""
    if not __import__("os").environ.get("MCP_DEBUG"):
        return
    parts = [f"[get_speed_env_vars] {'encrypted' if encrypted else 'plain'}:"]
    for k, v in env.items():
        status = "set" if (v and len(str(v).strip()) > 0) else "empty"
        parts.append(f" {k}={status}")
    print(" ".join(parts), file=sys.stderr, flush=True)


@mcp.tool()
async def get_balance(chain_id: int, address: str) -> dict[str, Any]:
    """Get native token balance for an address on a chain.

    chain_id: 1=ETH, 8453=Base, 10=OP, 42161=Arbitrum, 137=Polygon, 56=BNB.
    Uses Alchemy; no private key needed.
    """
    url = get_alchemy_rpc_url(chain_id)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_getBalance",
        "params": [address, "latest"],
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
    data = r.json()
    if "error" in data:
        return {"error": data["error"], "chainId": chain_id, "address": address}
    wei_hex = data.get("result", "0x0")
    balance_wei = int(wei_hex, 16)
    balance_native = balance_wei / 1e18
    return {
        "chainId": chain_id,
        "address": address,
        "balanceWei": wei_hex,
        "balanceNative": balance_native,
    }


@mcp.tool()
async def get_swap_quote(
    chain_id: int,
    sell_token: str,
    buy_token: str,
    sell_amount: str,
) -> dict[str, Any]:
    """Get a 0x swap quote. Uses the server's 0x API key.

    chain_id: 1=ETH, 8453=Base, 10=OP, 42161=Arbitrum, 137=Polygon, 56=BNB.
    sell_amount: amount in wei (smallest unit) as decimal string.
    """
    if not OX_API_KEY:
        return {"error": "0X_API_KEY not configured on the server."}
    params = {
        "sellToken": sell_token,
        "buyToken": buy_token,
        "sellAmount": sell_amount,
    }
    url = "https://api.0x.org/swap/v1/quote"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            url,
            params=params,
            headers={
                "0x-api-key": OX_API_KEY,
                "0x-chain-id": str(chain_id),
            },
        )
    if r.status_code != 200:
        return {"error": f"0x API: {r.status_code} {r.text}", "chainId": chain_id}
    return r.json()


@mcp.tool()
async def get_bridge_quote(
    from_chain_id: int,
    to_chain_id: int,
    from_token: str,
    to_token: str,
    from_amount: str,
    from_address: str,
) -> dict[str, Any]:
    """Get a Squid bridge/route quote. Uses the server's Squid integrator ID.

    Chain IDs: 1=ETH, 8453=Base, 10=OP, 42161=Arbitrum, 137=Polygon, 56=BNB.
    from_amount: amount in wei as decimal string.
    """
    if not SQUID_INTEGRATOR_ID:
        return {"error": "SQUID_INTEGRATOR_ID not configured on the server."}
    payload = {
        "fromAddress": from_address,
        "fromChain": str(from_chain_id),
        "fromToken": from_token,
        "fromAmount": from_amount,
        "toChain": str(to_chain_id),
        "toToken": to_token,
        "toAddress": from_address,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            "https://v2.api.squidrouter.com/v2/route",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "x-integrator-id": SQUID_INTEGRATOR_ID,
            },
        )
    if r.status_code != 200:
        return {"error": f"Squid API: {r.status_code} {r.text}"}
    return r.json()


@mcp.tool()
async def run_speed_with_env(command: str) -> dict[str, Any]:
    """Return instructions and env keys so the agent can run a speed-cli command.

    The agent must set the env vars from get_speed_env_vars() and then run the given command.
    The user's PRIVATE_KEY in ~/.speed/.env will be used by speed for signing.
    Example command: 'speed swap -c base --buy USDC -a 0.01 -y' or 'speed sans listings --json'.
    """
    env = get_speed_env()
    env_keys = list(env.keys())
    return {
        "instruction": (
            "Set the env vars from get_speed_env_vars() in your shell, then run the command below. "
            "Keep PRIVATE_KEY only in ~/.speed/.env."
        ),
        "command": command,
        "envKeys": env_keys,
        "note": "Call get_speed_env_vars to get the actual values; then run the command.",
    }


def main() -> None:
    transport = MCP_TRANSPORT if MCP_TRANSPORT in ("stdio", "sse", "streamable-http") else "stdio"
    if transport == "streamable-http":
        print(f"Speed MCP server listening on http://{MCP_HOST}:{MCP_PORT} (Streamable HTTP). Connect from remote with this URL.", file=__import__("sys").stderr)
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
