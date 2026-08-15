#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/.env"

read -r -p "GNS3 host [localhost]: " host
host="${host:-localhost}"
read -r -p "GNS3 port [3080]: " port
port="${port:-3080}"
read -r -p "GNS3 username [admin]: " username
username="${username:-admin}"
read -r -s -p "GNS3 password: " password
echo

umask 077
cat > "$ENV_FILE" <<EOF
GNS3_HOST=$host
GNS3_PORT=$port
GNS3_USERNAME=$username
GNS3_PASSWORD=$password
GNS3_TIMEOUT=10
EOF

chmod 600 "$ENV_FILE"
printf 'GNS3 configuration written to %s\n' "$ENV_FILE"
printf 'The file is git-ignored and must not be committed.\n'
