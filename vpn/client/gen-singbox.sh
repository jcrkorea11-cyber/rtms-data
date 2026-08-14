#!/usr/bin/env bash
# =============================================================================
# sing-box 프로파일 생성기 — 스플릿 터널링
#
#   VPN 을 켰다 껐다 할 필요를 없애는 부분이다.
#   목적지 도메인/IP 를 보고 알아서 경로를 나눈다.
#
#   프로파일 2개:
#     china  = 중국 출장 중에 쓴다
#              중국 사이트 → 직결 (현지에서 빠르게)
#              그 외 전부  → 서울 노드 (한국 프로그램·구글·카톡 등)
#
#     korea  = 한국에서 쓴다
#              중국 사이트 → 홍콩 노드 (한국에서 안 열리는 중국 서비스)
#              그 외 전부  → 직결 (평소 인터넷은 VPN 안 탐 → 느려지지 않음)
#
#   sing-box 1.12 이상 기준. (앱: Windows/macOS sing-box, iOS/Android sing-box)
#
#   사용법:  bash gen-singbox.sh china <서울.env>
#            bash gen-singbox.sh korea <홍콩.env>
# =============================================================================
set -euo pipefail

PROFILE="${1:?사용법: bash gen-singbox.sh <china|korea> <node-*.env>}"
ENV_FILE="${2:?사용법: bash gen-singbox.sh <china|korea> <node-*.env>}"

case "$PROFILE" in
  china|korea) ;;
  *) echo "[x] 프로파일은 china 또는 korea 여야 합니다" >&2; exit 1 ;;
esac
[[ -f "$ENV_FILE" ]] || { echo "[x] 파일 없음: $ENV_FILE" >&2; exit 1; }

# shellcheck disable=SC1090
source "$ENV_FILE"
: "${SERVER_IP:?env 파일에 SERVER_IP 가 비어 있습니다}"

OUT_DIR="$(dirname "$ENV_FILE")/out"
mkdir -p "$OUT_DIR"; chmod 700 "$OUT_DIR"
OUT_FILE="${OUT_DIR}/sing-box-${PROFILE}.json"

# 자체 서명 인증서를 JSON 문자열 배열로 변환한다.
# sing-box 는 지문(pinSHA256) 대신 인증서 자체를 고정하므로 insecure 를 켤 필요가 없다.
if [[ -n "${HY2_CERT_B64:-}" ]]; then
  CERT_JSON="$(printf '%s' "$HY2_CERT_B64" | base64 -d \
    | jq -R -s 'split("\n") | map(select(length > 0))')"
else
  echo "[!] HY2_CERT_B64 가 없습니다. Hysteria2 아웃바운드를 생략합니다." >&2
  CERT_JSON=""
fi

# ─────────────────────────────────────────────────────────────
# 프로파일별 라우팅 규칙
# ─────────────────────────────────────────────────────────────
if [[ "$PROFILE" == "china" ]]; then
  # 중국 안: 중국 사이트만 직결, 나머지는 전부 프록시
  ROUTE_RULES='
      { "action": "sniff" },
      { "protocol": "dns", "action": "hijack-dns" },
      { "ip_is_private": true, "outbound": "direct" },
      { "rule_set": ["geosite-cn", "geoip-cn"], "outbound": "direct" }'
  ROUTE_FINAL='proxy'
  DNS_RULES='
      { "rule_set": "geosite-cn", "server": "dns-direct" }'
  DNS_FINAL='dns-proxy'
  # 중국 안에서는 중국 도메인을 중국 DNS 로 직접 물어봐야 현지 CDN 을 제대로 받는다.
  # 나머지는 DoH 로 프록시를 태운다(평문 UDP 로 물으면 DNS 응답이 오염된다).
  DNS_SERVERS='
      { "type": "https", "tag": "dns-proxy",  "server": "1.1.1.1",   "detour": "proxy"  },
      { "type": "udp",   "tag": "dns-direct", "server": "223.5.5.5", "detour": "direct" }'
  # 중국에서는 raw.githubusercontent.com 이 막히므로 규칙셋도 프록시로 받아야 한다
  RULESET_DETOUR='proxy'
else
  # 한국 안: 중국 사이트만 프록시(홍콩), 나머지는 전부 직결
  ROUTE_RULES='
      { "action": "sniff" },
      { "protocol": "dns", "action": "hijack-dns" },
      { "ip_is_private": true, "outbound": "direct" },
      { "rule_set": ["geosite-cn", "geoip-cn"], "outbound": "proxy" }'
  ROUTE_FINAL='direct'
  DNS_RULES='
      { "rule_set": "geosite-cn", "server": "dns-proxy" }'
  DNS_FINAL='dns-direct'
  # 한국에서는 일반 도메인을 한국 DNS 로 물어야 국내 CDN 이 제대로 잡힌다.
  # 중국 도메인만 중국 DNS(AliDNS)로 묻되, 홍콩 노드를 경유시켜
  # 중국 서비스가 기대하는 위치의 응답을 받는다.
  DNS_SERVERS='
      { "type": "udp", "tag": "dns-direct", "server": "168.126.63.1", "detour": "direct" },
      { "type": "udp", "tag": "dns-proxy",  "server": "223.5.5.5",    "detour": "proxy"  }'
  RULESET_DETOUR='direct'
fi

# ─────────────────────────────────────────────────────────────
# 아웃바운드
# ─────────────────────────────────────────────────────────────
OUTBOUND_REALITY=$(cat <<EOF
    {
      "type": "vless",
      "tag": "${NODE_NAME}-reality",
      "server": "${SERVER_IP}",
      "server_port": 443,
      "uuid": "${XRAY_UUID}",
      "flow": "xtls-rprx-vision",
      "packet_encoding": "xudp",
      "tls": {
        "enabled": true,
        "server_name": "${REALITY_SNI}",
        "utls": { "enabled": true, "fingerprint": "chrome" },
        "reality": {
          "enabled": true,
          "public_key": "${REALITY_PUBLIC_KEY}",
          "short_id": "${REALITY_SHORT_ID}"
        }
      }
    }
EOF
)

PROXY_MEMBERS="\"${NODE_NAME}-reality\""
OUTBOUND_HY2=""
if [[ -n "$CERT_JSON" ]]; then
  OUTBOUND_HY2=",
$(cat <<EOF
    {
      "type": "hysteria2",
      "tag": "${NODE_NAME}-hy2",
      "server": "${SERVER_IP}",
      "server_port": 443,
      "password": "${HY2_PASSWORD}",
      "tls": {
        "enabled": true,
        "server_name": "${REALITY_SNI}",
        "certificate": ${CERT_JSON}
      }
    }
EOF
)"
  PROXY_MEMBERS+=", \"${NODE_NAME}-hy2\""
fi

# ─────────────────────────────────────────────────────────────
cat >"$OUT_FILE" <<EOF
{
  "log": { "level": "warn", "timestamp": true },

  "dns": {
    "servers": [${DNS_SERVERS}
    ],
    "rules": [${DNS_RULES}
    ],
    "final": "${DNS_FINAL}",
    "independent_cache": true
  },

  "inbounds": [
    {
      "type": "tun",
      "tag": "tun-in",
      "address": [ "172.19.0.1/30", "fdfe:dcba:9876::1/126" ],
      "auto_route": true,
      "strict_route": true,
      "stack": "mixed"
    }
  ],

  "outbounds": [
$(printf '%s' "$OUTBOUND_REALITY")${OUTBOUND_HY2},
    {
      "type": "urltest",
      "tag": "auto",
      "outbounds": [ ${PROXY_MEMBERS} ],
      "url": "https://www.gstatic.com/generate_204",
      "interval": "3m",
      "tolerance": 100
    },
    {
      "type": "selector",
      "tag": "proxy",
      "outbounds": [ "auto", ${PROXY_MEMBERS} ],
      "default": "auto"
    },
    { "type": "direct", "tag": "direct" }
  ],

  "route": {
    "rules": [${ROUTE_RULES}
    ],
    "rule_set": [
      {
        "type": "remote",
        "tag": "geosite-cn",
        "format": "binary",
        "url": "https://raw.githubusercontent.com/SagerNet/sing-geosite/rule-set/geosite-cn.srs",
        "download_detour": "${RULESET_DETOUR}",
        "update_interval": "7d"
      },
      {
        "type": "remote",
        "tag": "geoip-cn",
        "format": "binary",
        "url": "https://raw.githubusercontent.com/SagerNet/sing-geoip/rule-set/geoip-cn.srs",
        "download_detour": "${RULESET_DETOUR}",
        "update_interval": "7d"
      }
    ],
    "final": "${ROUTE_FINAL}",
    "auto_detect_interface": true
  },

  "experimental": {
    "cache_file": { "enabled": true, "store_rdrc": true },
    "clash_api": { "external_controller": "127.0.0.1:9090" }
  }
}
EOF

chmod 600 "$OUT_FILE"

# 문법 검증 (jq 로 최소한의 JSON 유효성 확인)
if command -v jq >/dev/null 2>&1; then
  jq empty "$OUT_FILE" || { echo "[x] 생성된 JSON 이 깨졌습니다: $OUT_FILE" >&2; exit 1; }
fi

echo "생성 완료: ${OUT_FILE}"
if [[ "$PROFILE" == "china" ]]; then
  cat <<'EOF'

  [중국 출장용]
    중국 사이트 → 직결,  나머지 전부 → 서울 노드

  [!] 반드시 출국 전에 한국에서 한 번 접속 테스트를 하세요.
      중국에 도착해서 처음 설정하려고 하면, 설정에 필요한 사이트들이
      이미 막혀 있어서 손을 못 씁니다.
EOF
else
  cat <<'EOF'

  [한국 상시용]
    중국 사이트 → 홍콩 노드,  나머지 전부 → 직결

  평소 인터넷은 VPN 을 안 타므로 속도에 영향이 없습니다.
  중국 사이트를 열 때만 자동으로 홍콩을 경유합니다.
EOF
fi
