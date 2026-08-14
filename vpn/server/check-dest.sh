#!/usr/bin/env bash
# =============================================================================
# Reality 위장 도메인 후보 검사기
#
#   Reality 는 실존하는 사이트를 "빌려" 위장한다.
#   아무 사이트나 되는 게 아니라 조건이 있다:
#
#     - TLS 1.3 지원          (필수)
#     - HTTP/2 (h2) 지원      (필수에 가까움)
#     - X25519 키교환 지원    (필수)
#     - 중국에서 차단돼 있지 않을 것   ← 이게 제일 중요한데 서버에서는 확인 불가
#     - 너무 유명하지 않을 것  (apple.com 같은 건 이미 많이 쓰여 표적이 되기도 함)
#
#   서버가 한국에 있다면, 한국에 실제로 호스팅된 사이트를 고르는 편이
#   "한국 IP 로 가는 한국 사이트 트래픽" 이라 그림이 자연스럽다.
#
#   사용법:  bash check-dest.sh                    (기본 후보군 일괄 검사)
#            bash check-dest.sh www.example.com    (특정 도메인 검사)
# =============================================================================
set -euo pipefail

CANDIDATES=(
  "www.samsung.com"
  "www.lge.co.kr"
  "www.hyundai.com"
  "www.naver.com"
  "www.apple.com"
  "www.microsoft.com"
  "www.bing.com"
  "www.cloudflare.com"
)

[[ $# -gt 0 ]] && CANDIDATES=("$@")

printf '%-26s %-9s %-6s %-9s %s\n' "도메인" "TLS1.3" "h2" "X25519" "판정"
printf '%s\n' "────────────────────────────────────────────────────────────────────"

for host in "${CANDIDATES[@]}"; do
  out="$(echo | timeout 10 openssl s_client -connect "${host}:443" \
          -servername "$host" -tls1_3 -alpn h2 -groups X25519 2>/dev/null || true)"

  if [[ -z "$out" ]]; then
    printf '%-26s %-9s %-6s %-9s %s\n' "$host" "-" "-" "-" "접속 실패"
    continue
  fi

  tls13="X"; h2="X"; x25519="X"
  grep -q "TLSv1.3"             <<<"$out" && tls13="O"
  grep -q "ALPN protocol: h2"   <<<"$out" && h2="O"
  grep -qE "Negotiated TLS1.3 group: (X25519|x25519)" <<<"$out" && x25519="O"

  # X25519 그룹 표시는 openssl 버전에 따라 안 나올 수 있다.
  # -groups X25519 로 핸드셰이크가 성공했다면 지원하는 것으로 본다.
  [[ "$x25519" == "X" && "$tls13" == "O" ]] && x25519="O?"

  if [[ "$tls13" == "O" && "$h2" == "O" ]]; then
    verdict="사용 가능"
  elif [[ "$tls13" == "O" ]]; then
    verdict="가능하나 h2 없음"
  else
    verdict="사용 불가"
  fi

  printf '%-26s %-9s %-6s %-9s %s\n' "$host" "$tls13" "$h2" "$x25519" "$verdict"
done

cat <<'EOF'

────────────────────────────────────────────────────────────────────
 [반드시 직접 확인해야 하는 것]

 위 검사는 "서버에서 그 사이트에 붙을 수 있는가" 만 봅니다.
 정작 중요한 "중국에서 그 사이트가 막혀 있지 않은가" 는 확인할 수 없습니다.

 중국 출장 중에 폰으로 해당 도메인을 열어보고, 정상적으로 열리는 걸
 확인한 뒤에 그 도메인을 쓰세요. 중국에서 차단된 도메인을 위장에 쓰면
 오히려 눈에 띕니다.

 google / facebook / youtube 계열은 중국에서 차단되어 있으므로 쓰면 안 됩니다.
EOF
