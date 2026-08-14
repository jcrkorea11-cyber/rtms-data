#!/usr/bin/env bash
# =============================================================================
# 개인 VPN 노드 설치 스크립트
#
#   3개 채널을 동시에 올린다. 하나가 막혀도 나머지로 붙기 위함이다.
#     1) VLESS + XTLS-Reality   (TCP 443)  ← 중국에서 가장 잘 버티는 채널
#     2) Hysteria2              (UDP 443)  ← 패킷 손실 많은 회선에서 훨씬 빠름
#     3) WireGuard              (UDP 51820) ← 중국 밖에서 쓰는 단순·고속 채널
#
#   대상 OS: Ubuntu 22.04 / 24.04 (Oracle Cloud 기본 이미지 기준)
#   아키텍처: ARM(aarch64) / AMD(x86_64) 자동 판별
#
#   사용법:  sudo bash setup.sh <노드이름> [Reality위장도메인]
#   예시:    sudo bash setup.sh seoul www.samsung.com
#            sudo bash setup.sh hongkong www.apple.com
#
#   완료 후 /root/vpn-out/node-<노드이름>.env 에 접속 정보가 생성된다.
#   이 파일을 클라이언트 생성 스크립트(client/gen-clients.sh)에 넘긴다.
# =============================================================================
set -euo pipefail

NODE_NAME="${1:?사용법: sudo bash setup.sh <노드이름> [Reality위장도메인]}"
REALITY_DEST_HOST="${2:-www.apple.com}"

OUT_DIR="/root/vpn-out"
ENV_FILE="${OUT_DIR}/node-${NODE_NAME}.env"
WG_SUBNET="10.66.66"
WG_PORT="51820"

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "root 로 실행해야 합니다:  sudo bash $0 $*"

# -----------------------------------------------------------------------------
# 0. 위장 도메인 검증
#    Reality 는 실제로 존재하는 사이트의 TLS 인증서를 빌려 쓴다.
#    그 사이트가 TLS 1.3 과 HTTP/2 를 지원하지 않으면 위장이 깨진다.
# -----------------------------------------------------------------------------
log "위장 도메인 검증: ${REALITY_DEST_HOST}"
if ! command -v openssl >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq openssl
fi
DEST_CHECK="$(echo | timeout 10 openssl s_client -connect "${REALITY_DEST_HOST}:443" \
                -servername "${REALITY_DEST_HOST}" -tls1_3 -alpn h2 2>/dev/null || true)"
if ! grep -q "TLSv1.3" <<<"$DEST_CHECK"; then
  die "${REALITY_DEST_HOST} 가 TLS 1.3 을 지원하지 않습니다. 다른 도메인을 쓰세요.
     확인용:  bash server/check-dest.sh <도메인>"
fi
if ! grep -q "ALPN protocol: h2" <<<"$DEST_CHECK"; then
  warn "${REALITY_DEST_HOST} 가 HTTP/2(h2) 를 광고하지 않습니다. 위장 품질이 떨어질 수 있습니다."
fi
log "위장 도메인 OK (TLS 1.3 확인됨)"

# -----------------------------------------------------------------------------
# 1. 기본 패키지 + 커널 튜닝
# -----------------------------------------------------------------------------
log "패키지 설치"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates qrencode wireguard-tools \
                       iptables iptables-persistent jq

log "커널 튜닝 (BBR + UDP 버퍼 + IP 포워딩)"
cat >/etc/sysctl.d/99-vpn-node.conf <<'EOF'
# BBR 혼잡제어 — 한국↔중국처럼 지연·손실이 큰 구간에서 체감 차이가 크다
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# Hysteria2(QUIC) 는 UDP 버퍼가 작으면 성능이 급락한다
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216

# WireGuard 라우팅용
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
sysctl -q --system

if [[ "$(sysctl -n net.ipv4.tcp_congestion_control)" != "bbr" ]]; then
  warn "BBR 활성화 실패 — 커널이 지원하지 않을 수 있습니다. 동작에는 지장 없습니다."
fi

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

# -----------------------------------------------------------------------------
# 2. Xray (VLESS + Reality)  — TCP 443
# -----------------------------------------------------------------------------
log "Xray 설치"
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install >/dev/null

XRAY_UUID="$(xray uuid)"
REALITY_SHORT_ID="$(openssl rand -hex 8)"

# xray x25519 의 출력 형식이 버전마다 다르다.
#   v1.8.x  : "Private key: ..." / "Public key: ..."
#   v25.x   : "PrivateKey: ..."  / "Password: ..."   (공개키를 Password 로 개명)
X25519_OUT="$(xray x25519)"
REALITY_PRIVATE_KEY="$(grep -iE '^ *private ?key' <<<"$X25519_OUT" | sed 's/.*: *//' | tr -d '[:space:]')"
REALITY_PUBLIC_KEY="$(grep -iE '^ *(public ?key|password)' <<<"$X25519_OUT" | sed 's/.*: *//' | tr -d '[:space:]')"
[[ -n "$REALITY_PRIVATE_KEY" && -n "$REALITY_PUBLIC_KEY" ]] \
  || die "Reality 키 생성 실패. 'xray x25519' 출력:\n${X25519_OUT}"

log "Xray 설정 작성"
cat >/usr/local/etc/xray/config.json <<EOF
{
  "log": { "loglevel": "warning" },
  "inbounds": [
    {
      "tag": "vless-reality",
      "listen": "0.0.0.0",
      "port": 443,
      "protocol": "vless",
      "settings": {
        "clients": [
          { "id": "${XRAY_UUID}", "flow": "xtls-rprx-vision" }
        ],
        "decryption": "none"
      },
      "streamSettings": {
        "network": "tcp",
        "security": "reality",
        "realitySettings": {
          "show": false,
          "dest": "${REALITY_DEST_HOST}:443",
          "xver": 0,
          "serverNames": [ "${REALITY_DEST_HOST}" ],
          "privateKey": "${REALITY_PRIVATE_KEY}",
          "shortIds": [ "${REALITY_SHORT_ID}" ]
        }
      },
      "sniffing": {
        "enabled": true,
        "destOverride": [ "http", "tls", "quic" ]
      }
    }
  ],
  "outbounds": [
    { "protocol": "freedom", "tag": "direct" },
    { "protocol": "blackhole", "tag": "block" }
  ],
  "routing": {
    "rules": [
      {
        "type": "field",
        "ip": [ "geoip:private" ],
        "outboundTag": "block"
      }
    ]
  }
}
EOF

xray run -test -c /usr/local/etc/xray/config.json >/dev/null \
  || die "Xray 설정 검증 실패"
systemctl enable --now xray >/dev/null 2>&1
systemctl restart xray

# -----------------------------------------------------------------------------
# 3. Hysteria2  — UDP 443
# -----------------------------------------------------------------------------
log "Hysteria2 설치"
bash <(curl -fsSL https://get.hy2.sh/) >/dev/null

HY2_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)"

# Hysteria2 는 도메인이 없어도 되도록 자체 서명 인증서를 쓰고,
# 클라이언트는 인증서 지문(pinSHA256)으로 검증한다. 도메인·갱신이 필요 없다.
openssl req -x509 -nodes -days 3650 \
  -newkey ec -pkeyopt ec_paramgen_curve:prime256v1 \
  -keyout /etc/hysteria/private.key \
  -out    /etc/hysteria/cert.crt \
  -subj "/CN=${REALITY_DEST_HOST}" 2>/dev/null

HY2_PIN="$(openssl x509 -noout -fingerprint -sha256 -in /etc/hysteria/cert.crt \
            | sed 's/.*=//')"

chown hysteria:hysteria /etc/hysteria/private.key /etc/hysteria/cert.crt 2>/dev/null || true
chmod 600 /etc/hysteria/private.key

cat >/etc/hysteria/config.yaml <<EOF
listen: :443

tls:
  cert: /etc/hysteria/cert.crt
  key: /etc/hysteria/private.key

auth:
  type: password
  password: "${HY2_PASSWORD}"

# 인증 없이 들어온 요청은 진짜 웹사이트를 그대로 보여준다.
# 능동 탐침(active probing)에 대해 평범한 웹서버처럼 보이게 하는 장치.
masquerade:
  type: proxy
  proxy:
    url: https://${REALITY_DEST_HOST}/
    rewriteHost: true

quic:
  initStreamReceiveWindow: 8388608
  maxStreamReceiveWindow: 8388608
  initConnReceiveWindow: 20971520
  maxConnReceiveWindow: 20971520
EOF

systemctl enable --now hysteria-server >/dev/null 2>&1
systemctl restart hysteria-server

# -----------------------------------------------------------------------------
# 4. WireGuard  — UDP 51820
# -----------------------------------------------------------------------------
log "WireGuard 설정"
umask 077
WG_SERVER_PRIVATE_KEY="$(wg genkey)"
WG_SERVER_PUBLIC_KEY="$(wg pubkey <<<"$WG_SERVER_PRIVATE_KEY")"

WAN_IF="$(ip -4 route show default | awk '{print $5; exit}')"
[[ -n "$WAN_IF" ]] || die "기본 네트워크 인터페이스를 찾지 못했습니다"

cat >/etc/wireguard/wg0.conf <<EOF
[Interface]
Address    = ${WG_SUBNET}.1/24
ListenPort = ${WG_PORT}
PrivateKey = ${WG_SERVER_PRIVATE_KEY}

# 피어(클라이언트)는 client/gen-clients.sh 가 아래에 추가한다.
EOF
chmod 600 /etc/wireguard/wg0.conf

systemctl enable --now "wg-quick@wg0" >/dev/null 2>&1 || true
systemctl restart "wg-quick@wg0"

# -----------------------------------------------------------------------------
# 5. 방화벽
#    Oracle Cloud 의 Ubuntu 이미지는 INPUT 체인 끝에 REJECT 규칙이 박혀 있다.
#    그래서 -A(추가)가 아니라 -I 1(맨 앞 삽입)로 넣어야 실제로 열린다.
#    ※ 이것만으로는 부족하다. OCI 콘솔의 Security List 도 반드시 열어야 한다.
#      → server/open-ports.sh 참고
# -----------------------------------------------------------------------------
log "인스턴스 방화벽(iptables) 개방"
ensure_accept() {
  local proto="$1" port="$2"
  iptables -C INPUT -p "$proto" --dport "$port" -j ACCEPT 2>/dev/null \
    || iptables -I INPUT 1 -p "$proto" --dport "$port" -j ACCEPT
}
ensure_accept tcp 443
ensure_accept udp 443
ensure_accept udp "$WG_PORT"

# WireGuard NAT
iptables -t nat -C POSTROUTING -s "${WG_SUBNET}.0/24" -o "$WAN_IF" -j MASQUERADE 2>/dev/null \
  || iptables -t nat -A POSTROUTING -s "${WG_SUBNET}.0/24" -o "$WAN_IF" -j MASQUERADE
iptables -C FORWARD -i wg0 -j ACCEPT 2>/dev/null || iptables -I FORWARD 1 -i wg0 -j ACCEPT
iptables -C FORWARD -o wg0 -j ACCEPT 2>/dev/null || iptables -I FORWARD 1 -o wg0 -j ACCEPT

netfilter-persistent save >/dev/null 2>&1 || warn "iptables 영구 저장 실패 — 재부팅 후 규칙이 사라질 수 있습니다"

# -----------------------------------------------------------------------------
# 6. 접속 정보 저장
# -----------------------------------------------------------------------------
PUBLIC_IP="$(curl -fsS --max-time 10 https://api.ipify.org 2>/dev/null \
             || curl -fsS --max-time 10 https://ifconfig.me 2>/dev/null \
             || echo "")"
[[ -n "$PUBLIC_IP" ]] || warn "공인 IP 자동 감지 실패 — env 파일에서 직접 채워주세요"

cat >"$ENV_FILE" <<EOF
# ${NODE_NAME} 노드 접속 정보 — 생성 시각: $(date -u +%FT%TZ)
# !!! 이 파일은 비밀입니다. git 에 커밋하거나 메신저로 보내지 마세요. !!!
NODE_NAME="${NODE_NAME}"
SERVER_IP="${PUBLIC_IP}"

# VLESS + Reality (TCP 443)
XRAY_UUID="${XRAY_UUID}"
REALITY_PUBLIC_KEY="${REALITY_PUBLIC_KEY}"
REALITY_SHORT_ID="${REALITY_SHORT_ID}"
REALITY_SNI="${REALITY_DEST_HOST}"

# Hysteria2 (UDP 443)
HY2_PASSWORD="${HY2_PASSWORD}"
HY2_PIN_SHA256="${HY2_PIN}"
# 자체 서명 인증서 원문(base64). sing-box 는 지문 대신 인증서 자체를 고정하므로 필요하다.
HY2_CERT_B64="$(base64 -w0 </etc/hysteria/cert.crt)"

# WireGuard (UDP ${WG_PORT})
WG_SERVER_PUBLIC_KEY="${WG_SERVER_PUBLIC_KEY}"
WG_PORT="${WG_PORT}"
WG_SUBNET="${WG_SUBNET}"
EOF
chmod 600 "$ENV_FILE"

# -----------------------------------------------------------------------------
# 7. 결과
# -----------------------------------------------------------------------------
echo
log "설치 완료 — 서비스 상태"
for svc in xray hysteria-server wg-quick@wg0; do
  state="$(systemctl is-active "$svc" 2>/dev/null || true)"
  if [[ "$state" == "active" ]]; then
    printf '    \033[1;32m●\033[0m %-20s %s\n' "$svc" "$state"
  else
    printf '    \033[1;31m●\033[0m %-20s %s\n' "$svc" "${state:-unknown}"
  fi
done

cat <<EOF

접속 정보:  ${ENV_FILE}

다음 순서:
  1) OCI 콘솔에서 Security List 에 아래 포트를 여세요 (이거 안 하면 절대 안 붙습니다)
       TCP 443 / UDP 443 / UDP ${WG_PORT}   , 소스 0.0.0.0/0
       자세한 방법:  bash server/open-ports.sh --help
  2) 클라이언트 설정 생성:
       sudo bash client/gen-clients.sh ${ENV_FILE} <기기이름>
EOF
