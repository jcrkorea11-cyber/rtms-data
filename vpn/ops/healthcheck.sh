#!/usr/bin/env bash
# =============================================================================
# 채널 점검 스크립트 — 노트북에서 실행
#
#   중국에서 "인터넷이 안 된다" 고 할 때, 어디가 막힌 건지 30초 안에 가른다.
#     - 서버 자체가 죽은 건가
#     - IP 가 통째로 차단된 건가
#     - 특정 프로토콜만 막힌 건가 (TCP 는 되는데 UDP 만 죽는 경우가 흔하다)
#
#   사용법:  bash healthcheck.sh <서버IP>
#            bash healthcheck.sh <서버IP> --watch    (30초마다 반복)
# =============================================================================
set -uo pipefail

SERVER="${1:?사용법: bash healthcheck.sh <서버IP> [--watch]}"
WATCH="${2:-}"

ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[1;31m✗\033[0m %s\n' "$*"; }
info() { printf '  \033[1;34mi\033[0m %s\n' "$*"; }

run_check() {
  echo
  echo "══ $(date '+%H:%M:%S')  ${SERVER} 점검 ══"

  # ---- 1. ICMP -------------------------------------------------------------
  # 중국에서는 ICMP 자체가 자주 막히므로, 실패해도 서버가 죽었다는 뜻은 아니다.
  if ping -c 2 -W 2 "$SERVER" >/dev/null 2>&1; then
    ok "ping 응답 있음"
  else
    info "ping 무응답 (중국에서는 정상일 수 있음 — 판단 근거로 쓰지 마세요)"
  fi

  # ---- 2. TCP 443 (Reality) ------------------------------------------------
  if command -v nc >/dev/null 2>&1 && nc -z -w 5 "$SERVER" 443 2>/dev/null; then
    ok "TCP 443 열림 — Reality 채널 살아있음"
    tcp_ok=1
  else
    bad "TCP 443 막힘 — Reality 채널 사용 불가"
    tcp_ok=0
  fi

  # ---- 3. TLS 핸드셰이크 ---------------------------------------------------
  # Reality 가 정상이면 위장 사이트의 진짜 인증서가 돌아온다.
  if (( tcp_ok )); then
    subject="$(echo | timeout 8 openssl s_client -connect "${SERVER}:443" \
                -servername "${REALITY_SNI:-www.apple.com}" 2>/dev/null \
              | grep -m1 '^subject=' || true)"
    if [[ -n "$subject" ]]; then
      ok "TLS 핸드셰이크 성공 — 위장 정상 동작"
      info "  ${subject}"
    else
      bad "TLS 핸드셰이크 실패 — 중간에서 간섭받는 중일 수 있음"
    fi
  fi

  # ---- 4. UDP 443 (Hysteria2) / UDP 51820 (WireGuard) ----------------------
  # UDP 는 응답이 없는 게 정상이라 nc 로 판정이 안 된다.
  # 실제 핸드셰이크를 보내지 않는 한 확신할 수 없으므로 안내만 한다.
  info "UDP 443 / 51820 은 이 스크립트로 판정 불가 — 클라이언트로 직접 붙어보세요"

  # ---- 5. 현재 나가는 IP ---------------------------------------------------
  myip="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || echo '')"
  if [[ -n "$myip" ]]; then
    if [[ "$myip" == "$SERVER" ]]; then
      ok "현재 트래픽이 VPN 을 타고 있음 (출구 IP = ${myip})"
    else
      info "현재 출구 IP = ${myip}  (VPN 미경유 또는 스플릿 터널링 직결 구간)"
    fi
  else
    bad "외부 IP 조회 실패 — 인터넷 자체가 끊겼을 수 있음"
  fi

  # ---- 6. 판정 요약 --------------------------------------------------------
  echo
  if (( tcp_ok )); then
    echo "  → Reality(TCP 443) 로 접속하세요."
  else
    cat <<'EOF'
  → TCP 443 이 막혔습니다. 순서대로 시도하세요:

     1) Hysteria2 (UDP 443) 로 전환    ← TCP 만 막힌 경우가 흔합니다
     2) 그래도 안 되면 IP 가 차단된 것입니다.
        OCI 콘솔에서 인스턴스에 새 공인 IP 를 붙이세요:
          Instance → Attached VNICs → IPv4 Addresses → Edit
          → Ephemeral 이면 삭제 후 재할당하면 새 IP 를 받습니다
        그 뒤 node-*.env 의 SERVER_IP 를 고치고 클라이언트 설정을 다시 만듭니다.
     3) OCI 콘솔 접속 자체가 안 되면, 폰 로밍(중국 이통사 아닌 한국 통신사
        로밍)으로 붙으세요. 로밍 트래픽은 한국망을 타므로 GFW 를 우회합니다.
EOF
  fi
}

if [[ "$WATCH" == "--watch" ]]; then
  while true; do
    run_check
    sleep 30
  done
else
  run_check
fi
