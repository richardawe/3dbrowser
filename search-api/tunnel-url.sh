#!/bin/bash
# Prints the current Cloudflare tunnel URL.
# Run: ./tunnel-url.sh

echo "Waiting for tunnel URL..."
for i in $(seq 1 30); do
  URL=$(docker logs search-tunnel 2>&1 | grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' | tail -1)
  if [ -n "$URL" ]; then
    echo ""
    echo "✅ Tunnel URL: $URL"
    echo ""
    echo "Use this as your API URL in the GitHub Pages setup dialog:"
    echo "  https://richardawe.github.io/3dbrowser/"
    echo ""
    exit 0
  fi
  sleep 1
done
echo "❌ Tunnel not ready yet. Check: docker logs search-tunnel"
