#!/usr/bin/env bash
# =============================================================================
# 클라이언트 접속 정보 생성기
#
#   노드 하나에 대해 기기별 접속 수단을 만든다.
#     - VLESS+Reality 링크 (+ QR)   → 폰/노트북 범용
#     - Hysteria2 링크    (+ QR)   → 폰/노트북 범용, 회선 나쁠 때 대안
#     - WireGuard 설정    (+ QR)   → 중국 밖에서 쓰는 단순 채널
#
#   WireGuard 피어 등록은 서버에서 실행해야 한다(서버 설정 파일을 고쳐야 하므로).
#   VLESS/Hysteria2 링크만 필요하면 노트북에서 실행해도 된다.
#
#   사용법:  sudo bash gen-clients.sh <node-*.env> <기기이름>
#   예시:    sudo bash gen-clients.sh /root/vpn-out/node-seoul.env iphone
# =============================================================================
set -euo pipefail

ENV_FILE="${1:?사용법: sudo bash gen-clients.sh <node-*.env> <기기이름>}"
DEVICE="${2:?사용법: sudo bash gen-clients.sh <node-*.env> <기기이름>}"

[[ -f "$ENV_FILE" ]] || { echo "[x] 파일 없음: $ENV_FILE" >&2; exit 1; }
[[ "$DEVICE" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "[x] 기기이름은 영문/숫자/-/_ 만 쓰세요" >&2; exit 1; }

# shellcheck disable=SC1090
source "$ENV_FILE"

: "${SERVER_IP:?env 파일에 SERVER_IP 가 비어 있습니다. 서버 공인 IP 를 직접 채워주세요}"

OUT_DIR="$(dirname "$ENV_FILE")/out/${NODE_NAME}-${DEVICE}"
mkdir -p "$OUT_DIR"
chmod 700 "$(dirname "$ENV_FILE")/out" "$OUT_DIR"

log() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }

have_qr=0
command -v qrencode >/dev/null 2>&1 && have_qr=1

emit() {  # emit <파일이름> <라벨> <URL>
  local name="$1" label="$2" url="$3"
  printf '%s\n' "$url" >"${OUT_DIR}/${name}.txt"
  if (( have_qr )); then
    qrencode -o "${OUT_DIR}/${name}.png" -s 6 -m 2 "$url"
  fi
  echo
  log "$label"
  printf '%s\n' "$url"
  if (( have_qr )); then
    echo
    qrencode -t ANSIUTF8 "$url"
  fi
}

# -----------------------------------------------------------------------------
# 1. VLESS + Reality
# -----------------------------------------------------------------------------
VLESS_URL="vless://${XRAY_UUID}@${SERVER_IP}:443"
VLESS_URL+="?type=tcp&security=reality&encryption=none"
VLESS_URL+="&flow=xtls-rprx-vision"
VLESS_URL+="&sni=${REALITY_SNI}"
VLESS_URL+="&pbk=${REALITY_PUBLIC_KEY}"
VLESS_URL+="&sid=${REALITY_SHORT_ID}"
VLESS_URL+="&fp=chrome"
VLESS_URL+="#${NODE_NAME}-reality"

emit "vless-reality" "VLESS + Reality (TCP 443) — 중국에서 1순위로 쓰세요" "$VLESS_URL"

# -----------------------------------------------------------------------------
# 2. Hysteria2
# -----------------------------------------------------------------------------
# pinSHA256 은 콜론 포함 대문자 16진수 형태를 그대로 넣는다.
HY2_URL="hysteria2://${HY2_PASSWORD}@${SERVER_IP}:443/"
HY2_URL+="?sni=${REALITY_SNI}"
HY2_URL+="&pinSHA256=${HY2_PIN_SHA256}"
HY2_URL+="#${NODE_NAME}-hy2"

emit "hysteria2" "Hysteria2 (UDP 443) — Reality 가 느릴 때 바꿔보세요" "$HY2_URL"

# -----------------------------------------------------------------------------
# 3. WireGuard  (서버에서 실행할 때만)
# -----------------------------------------------------------------------------
WG_CONF="/etc/wireguard/wg0.conf"
if [[ -w "$WG_CONF" ]] && command -v wg >/dev/null 2>&1; then
  umask 077

  # 이미 등록된 기기면 중복 추가하지 않는다.
  if grep -q "^# device: ${DEVICE}\$" "$WG_CONF"; then
    echo
    echo "[!] '${DEVICE}' 는 이미 WireGuard 에 등록되어 있습니다."
    echo "    새 키로 다시 만들려면 ${WG_CONF} 에서 해당 [Peer] 블록을 지운 뒤 다시 실행하세요."
  else
    # 다음 사용 가능한 IP 를 고른다. .1 은 서버가 쓴다.
    last_octet=2
    while grep -q "AllowedIPs *= *${WG_SUBNET}\.${last_octet}/32" "$WG_CONF"; do
      last_octet=$(( last_octet + 1 ))
      (( last_octet < 255 )) || { echo "[x] WireGuard 주소가 가득 찼습니다" >&2; exit 1; }
    done
    CLIENT_IP="${WG_SUBNET}.${last_octet}"

    CLIENT_PRIVATE_KEY="$(wg genkey)"
    CLIENT_PUBLIC_KEY="$(wg pubkey <<<"$CLIENT_PRIVATE_KEY")"
    CLIENT_PSK="$(wg genpsk)"

    cat >>"$WG_CONF" <<EOF

# device: ${DEVICE}
[Peer]
PublicKey           = ${CLIENT_PUBLIC_KEY}
PresharedKey        = ${CLIENT_PSK}
AllowedIPs          = ${CLIENT_IP}/32
EOF

    # 기존 접속을 끊지 않고 새 피어만 반영한다.
    # wg0 이 내려가 있으면 syncconf 가 실패하므로 그때는 올린다.
    if wg show wg0 >/dev/null 2>&1; then
      wg syncconf wg0 <(wg-quick strip wg0)
    else
      echo "[!] wg0 인터페이스가 내려가 있어 새로 올립니다"
      systemctl restart "wg-quick@wg0" || echo "[!] wg0 기동 실패 — 'systemctl status wg-quick@wg0' 로 확인하세요"
    fi

    cat >"${OUT_DIR}/wg-${DEVICE}.conf" <<EOF
[Interface]
PrivateKey = ${CLIENT_PRIVATE_KEY}
Address    = ${CLIENT_IP}/32
DNS        = 1.1.1.1, 8.8.8.8

[Peer]
PublicKey           = ${WG_SERVER_PUBLIC_KEY}
PresharedKey        = ${CLIENT_PSK}
Endpoint            = ${SERVER_IP}:${WG_PORT}
AllowedIPs          = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
EOF
    chmod 600 "${OUT_DIR}/wg-${DEVICE}.conf"

    if (( have_qr )); then
      qrencode -o "${OUT_DIR}/wg-${DEVICE}.png" -s 6 -m 2 <"${OUT_DIR}/wg-${DEVICE}.conf"
    fi

    echo
    log "WireGuard (UDP ${WG_PORT}) — 중국 밖에서 쓰세요. 중국에서는 대부분 막힙니다."
    echo "    설정 파일: ${OUT_DIR}/wg-${DEVICE}.conf   (할당 IP: ${CLIENT_IP})"
    if (( have_qr )); then
      echo
      qrencode -t ANSIUTF8 <"${OUT_DIR}/wg-${DEVICE}.conf"
    fi
  fi
else
  echo
  echo "[i] WireGuard 설정을 건너뜁니다 (서버에서 root 로 실행할 때만 생성됩니다)."
fi

# -----------------------------------------------------------------------------
echo
log "생성 완료: ${OUT_DIR}"
cat <<'EOF'

    폰: QR 을 그대로 스캔하세요.
    노트북: .txt 안의 링크를 클라이언트 앱에 붙여넣으세요.

    [!] 이 파일들에는 접속 비밀키가 들어 있습니다.
        git 에 커밋하지 말고, 카톡/위챗으로 보내지 마세요.
        특히 위챗은 중국 내에서 검열 대상이라 그대로 노출됩니다.
EOF
