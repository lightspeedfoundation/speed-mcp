# speed-mcp-server

MCP server that handshakes keys so [Speed-CLI](https://www.npmjs.com/package/@lightspeed-cli/speed-cli) and agents can use them without manual setup. Keys are not saved on client or read by the agent.

## Why

- Agents get swap quotes, bridge quotes, and balances without the user running `speed setup` or pasting API keys.
- Keys live on the server; the agent never sees them
- User keeps `PRIVATE_KEY` in `~/.speed/.env`; the server never touches it.

## Setup

1. **Create `.env`** in this directory (or set env vars):
  ```env
   ALCHEMY_API_KEY=your_alchemy_api_key
   0X_API_KEY=your_0x_api_key
   SQUID_INTEGRATOR_ID=your_squid_integrator_id
   OPENSEA_API_KEY=your_opensea_api_key
  ```
   Copy from `.env.example`. Get keys from:
  - [Alchemy](https://dashboard.alchemy.com/) → Create app
  - [0x Dashboard](https://dashboard.0x.org/) → Create app
  - [Squid integrator form](https://form.typeform.com/to/cqFtqSvX)
  - [OpenSea](https://docs.opensea.io/reference/api-keys) (for SANS listing/offers)
   Optional: **RPC_URL** for Base (8453) only (overrides Alchemy for that chain; same as Speed-CLI’s `rpc.js`).
2. **Install and run**:
  ```bash
   cd speed-mcp-server
   pip install -e .
   speed-mcp
  ```
   Or with a venv:

## Cursor MCP config

Add the server so Cursor spawns it (stdio). In **Cursor** → **Open MCP settings** (`Ctrl+Shift+P` → "Open MCP settings"), add:

```json
{
  "mcpServers": {
    "speed": {
      "command": "c:\\path\\to\\speed-mcp-server\\.venv\\Scripts\\speed-mcp.exe",
      "env": {}
    }
  }
}
```

Or point to your Python and the module:

```json
{
  "mcpServers": {
    "speed": {
      "command": "python",
      "args": ["-m", "speed_mcp_server.main"],
      "cwd": "c:\\Users\\user\\OneDrive\\Desktop\\apps\\speedtest\\speed-mcp-server",
      "env": {}
    }
  }
}
```

Load API keys from a `.env` in `cwd` by running from the server directory, or set `env` with the keys (avoid committing those).

## Remote connections (connect from another machine)

To allow an MCP client on a **different machine** to connect, run the server with **Streamable HTTP** so it listens on a port:

1. In the server’s `.env` (or environment), set:
  ```env
   MCP_TRANSPORT=streamable-http
   MCP_HOST=0.0.0.0
   MCP_PORT=8000
  ```
2. Start the server (from the machine that holds the secrets):
  ```bash
   cd speed-mcp-server
   speed-mcp
  ```
   You should see: `Speed MCP server listening on http://0.0.0.0:8000 (Streamable HTTP)...`
3. On the **other machine**, configure your MCP client to connect to the server’s URL. Use the server’s hostname or IP and port, e.g.:
  - **URL:** `http://SERVER_IP:8000` (or `http://your-server-hostname:8000`)
  - The client must use the **Streamable HTTP** transport and point to this base URL (the exact path may be `/mcp` or as required by your client SDK).
4. **Firewall / network:** Ensure port 8000 (or your `MCP_PORT`) is open on the server and reachable from the client machine. For production, put the server behind HTTPS and consider auth (the MCP Python package supports auth options).

**Behind Nginx (TLS) on loopback:** If you bind with `MCP_HOST=127.0.0.1` and proxy a public hostname (e.g. `mcp.example.com`), set **`MCP_ALLOWED_HOSTS=mcp.example.com`** (comma-separated for multiple). Otherwise the MCP Python SDK may return **HTTP 421 Invalid Host header** because Nginx forwards `Host: your.domain`.

**Cursor (remote agent):** In MCP settings on the client machine, use a `url` entry instead of `command`, e.g. `"url": "http://your-server-ip:8000"` if Cursor supports URL-based MCP for Streamable HTTP.

## Tools


| Tool                 | Description                                                                                                                                                                     |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `get_speed_env_vars` | Returns env vars **encrypted** for the client. Requires `client_public_key_pem` (RSA public key PEM). Client decrypts with `~/.speed/speed_mcp_key.pem` and applies to `process.env`. |
| `get_balance`        | Native balance for an address on a chain (Alchemy). chain_id: 1=ETH, 8453=Base, 10=OP, 42161=Arbitrum, 137=Polygon, 56=BNB.                                                     |
| `get_swap_quote`     | 0x swap quote (sellToken, buyToken, sellAmount, chainId).                                                                                                                       |
| `get_bridge_quote`   | Squid bridge/route quote (fromChain, toChain, tokens, amount, fromAddress).                                                                                                     |
| `run_speed_with_env` | Returns instructions + command so the agent runs a speed command with env from `get_speed_env_vars`; signing uses local PRIVATE_KEY.                                            |


## Integration with speed-cli

- **Read-only** (balance, quotes): use the MCP tools; no need to run speed.
- **Actions** (swap, bridge, SANS list/buy/offer): agent calls `get_speed_env_vars`, sets those env vars in the shell, then runs `speed <command>`. The user’s `~/.speed/.env` supplies `PRIVATE_KEY`; the server never sees it.

**Speed-CLI client:** Configure the MCP URL with `speed start <url>` (e.g. `speed start http://127.0.0.1:8000`), which writes `mcpUrl` to `~/.speed/config.json`. Put an RSA private key at `~/.speed/speed_mcp_key.pem`; Speed-CLI sends the corresponding public key in `get_speed_env_vars` and decrypts the response locally. The server always returns an encrypted payload in **`result.content[0].text`** as JSON: `{ "encrypted_key_b64", "nonce_b64", "ciphertext_b64" }`. The client decrypts with the private key, then uses the `env` object.

## Debug

Set `**MCP_DEBUG=1**` in the server’s environment to log which env keys are sent for each `get_speed_env_vars` call (key names and whether each is `set` or `empty`; values are never logged). Restart the server after setting it.

## Secure setup (encrypted)

Credentials can be sent **encrypted** so only the client can read them. Use this for `speed setup` when talking to the MCP server.

1. **Speed-CLI** (or any client):
   - Has an RSA keypair; stores the **private key** in `~/.speed/speed_mcp_key.pem`. Never send the private key to the server.
   - Calls MCP tool `get_speed_env_vars` with **client_public_key_pem** (required) set to the PEM-encoded public key.
2. **Server** encrypts the env dict with that public key (hybrid: AES-256-GCM for payload, RSA-OAEP-SHA256 for the AES key) and returns an object with:
  - `encrypted: true`
  - `algorithm: "RSA-OAEP-AES256GCM"`
  - `encrypted_key_b64`, `nonce_b64`, `ciphertext_b64` (base64-encoded).
3. **Speed-CLI** decrypts using its private key: decrypt `encrypted_key_b64` with RSA-OAEP-SHA256 to get the AES key; decrypt `ciphertext_b64` with AES-256-GCM using that key and `nonce_b64`; parse the result as JSON. The plaintext must include an **`env`** object (map of key names to values), e.g. `{"env":{"ALCHEMY_API_KEY":"..."}}`. Merge `env` with `PRIVATE_KEY` and write `~/.speed/.env`.

Credentials never cross the wire in plaintext; only the holder of the private key can recover them. In Node (Speed-CLI) use `node:crypto`: `crypto.privateDecrypt` (RSA-OAEP, SHA-256) for the key, then `crypto.createDecipheriv("aes-256-gcm", ...)` for the payload (use the 12-byte nonce and 16-byte auth tag at the end of the ciphertext if you follow standard GCM layout).

## License

GPLv3