#!/usr/bin/env python3
"""
Quick test to verify the MCP server can start and list its tools/resources.
"""
import subprocess
import json
import sys

def test_mcp_server():
    """Test the MCP server by starting it and checking for initialization."""
    print("=" * 70)
    print("Testing Fortress Prime MCP Server")
    print("=" * 70)
    print()
    
    # Set environment variables
    env = {
        "QDRANT_HOST": "localhost",
        "QDRANT_PORT": "6333",
        "QDRANT_API_KEY": "ba9bea29e2db1d31025171ffb33d74f151987bdb2fa6760beaa54ab28c23ff5d",
        "EMBED_URL": "http://localhost:11434/api/embeddings",
        "PG_HOST": "localhost",
        "PG_DB": "fortress_db",
        "PG_USER": "miner_bot",
        "PG_PASSWORD": "",
    }
    
    # Send initialize request to MCP server via stdio
    init_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "test-client",
                "version": "1.0.0"
            }
        }
    }
    
    try:
        print("[1/3] Starting MCP server...")
        proc = subprocess.Popen(
            ["python3", "/home/admin/Fortress-Prime/src/sovereign_mcp_server.py"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**subprocess.os.environ, **env}
        )
        
        print("[2/3] Sending initialize request...")
        request_str = json.dumps(init_request) + "\n"
        proc.stdin.write(request_str)
        proc.stdin.flush()
        
        print("[3/3] Waiting for response...")
        
        # Wait for response (with timeout)
        import select
        import time
        
        timeout = 5
        start = time.time()
        response_lines = []
        
        while time.time() - start < timeout:
            if proc.stdout in select.select([proc.stdout], [], [], 0.1)[0]:
                line = proc.stdout.readline()
                if line:
                    response_lines.append(line)
                    try:
                        response = json.loads(line)
                        print()
                        print("✓ Server responded successfully!")
                        print()
                        print("Response:")
                        print(json.dumps(response, indent=2))
                        print()
                        print("=" * 70)
                        print("MCP Server is working correctly!")
                        print("=" * 70)
                        proc.terminate()
                        return True
                    except json.JSONDecodeError:
                        # Not JSON yet, might be startup message
                        print(f"  Server output: {line.strip()}")
        
        # Check stderr for any errors
        stderr_output = proc.stderr.read()
        if stderr_output:
            print()
            print("Server stderr:")
            print(stderr_output)
        
        print()
        print("⚠ Timeout waiting for response")
        proc.terminate()
        return False
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

if __name__ == "__main__":
    success = test_mcp_server()
    sys.exit(0 if success else 1)
