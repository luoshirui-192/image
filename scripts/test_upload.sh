#!/bin/sh
set -e
TOKEN=$(wget -qO- --post-data='{"username":"admin","password":"admin123"}' \
  --header='Content-Type: application/json' \
  http://backend:8000/api/auth/login/ | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
echo "token ok len=${#TOKEN}"

# minimal PNG (1x1)
printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82' > /tmp/test.png

wget -S -O /tmp/upload_resp.txt \
  --header="Authorization: Bearer $TOKEN" \
  --post-file=/tmp/test.png \
  --header='Content-Type: image/png' \
  "http://backend:8000/api/images/upload/?category_id=1" 2>/tmp/upload_headers.txt || true
echo "--- response ---"
head -c 500 /tmp/upload_resp.txt
echo
echo "--- status ---"
grep -i "HTTP/" /tmp/upload_headers.txt | tail -1
