"""--host / MCP_HOST and MCP_ALLOWED_HOSTS: local defaults unchanged, protection never off."""

from echr_mcp.__main__ import parse_args, transport_security


def test_bind_options_keep_local_defaults_and_protection_on(monkeypatch):
    monkeypatch.delenv("MCP_HOST", raising=False)
    assert parse_args(["--transport", "http"]).host == "127.0.0.1"
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    assert parse_args(["--transport", "http"]).host == "0.0.0.0"
    assert parse_args(["--transport", "http", "--host", "127.0.0.1"]).host == "127.0.0.1"

    assert transport_security("127.0.0.1") is None  # the SDK's own localhost protection applies
    assert transport_security("localhost", "") is None

    open_bind = transport_security("0.0.0.0")
    assert open_bind.enable_dns_rebinding_protection
    assert "localhost:*" in open_bind.allowed_hosts

    named = transport_security("0.0.0.0", "mcp.example.com, localhost:8103")
    assert named.enable_dns_rebinding_protection
    assert "mcp.example.com" in named.allowed_hosts and "localhost:8103" in named.allowed_hosts
    assert "https://mcp.example.com" in named.allowed_origins
    assert transport_security("127.0.0.1", "mcp.example.com").enable_dns_rebinding_protection
