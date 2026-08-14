#!/usr/bin/env bash
# =============================================================================
# Oracle Cloud 포트 개방 도우미
#
#   OCI 에서 VPN 이 "안 붙는" 원인의 90% 는 여기다.
#   방화벽이 2겹이라, 인스턴스 안에서 iptables 만 열어서는 소용이 없다.
#
#     1겹) OCI 콘솔의 Security List / NSG   ← 클라우드 레벨. 이걸 자주 빼먹는다.
#     2겹) 인스턴스 안의 iptables            ← setup.sh 가 이미 처리함
#
#   OCI CLI 가 설치·설정되어 있으면 1겹을 자동으로 열어준다.
#   없으면 콘솔에서 수동으로 하는 방법을 안내한다.
#
#   사용법:  bash open-ports.sh          (자동 시도 → 실패 시 수동 안내)
#            bash open-ports.sh --help   (수동 안내만 보기)
# =============================================================================
set -euo pipefail

PORTS_TCP=(443)
PORTS_UDP=(443 51820)

manual_guide() {
  cat <<'EOF'
─────────────────────────────────────────────────────────────────────
 OCI 콘솔에서 직접 여는 방법
─────────────────────────────────────────────────────────────────────

 1. https://cloud.oracle.com  로그인
 2. 좌측 메뉴 → Networking → Virtual Cloud Networks
 3. 인스턴스가 속한 VCN 클릭
 4. 좌측 Subnets → 사용 중인 서브넷 클릭
 5. Security Lists → "Default Security List for ..." 클릭
 6. [Add Ingress Rules] 를 눌러 아래 3개를 추가

    ┌──────────────────────────────────────────────────────────┐
    │ Stateless        : 체크 안 함                             │
    │ Source Type      : CIDR                                   │
    │ Source CIDR      : 0.0.0.0/0                              │
    │ IP Protocol      : TCP                                    │
    │ Destination Port : 443                                    │
    └──────────────────────────────────────────────────────────┘
    ┌──────────────────────────────────────────────────────────┐
    │ Source CIDR      : 0.0.0.0/0                              │
    │ IP Protocol      : UDP                                    │
    │ Destination Port : 443                                    │
    └──────────────────────────────────────────────────────────┘
    ┌──────────────────────────────────────────────────────────┐
    │ Source CIDR      : 0.0.0.0/0                              │
    │ IP Protocol      : UDP                                    │
    │ Destination Port : 51820                                  │
    └──────────────────────────────────────────────────────────┘

 [주의] UDP 규칙을 빼먹으면 Hysteria2 와 WireGuard 가 조용히 실패합니다.
        (에러가 안 뜨고 그냥 연결이 안 됩니다 — 원인 찾기 제일 어려운 유형)

─────────────────────────────────────────────────────────────────────
 확인 방법 (노트북에서)
─────────────────────────────────────────────────────────────────────

   TCP 443 :  nc -vz <서버IP> 443
   UDP     :  UDP 는 nc 로 확인이 안 됩니다. 클라이언트로 직접 붙어보세요.

EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  manual_guide
  exit 0
fi

if ! command -v oci >/dev/null 2>&1; then
  echo "[i] OCI CLI 가 없습니다. 수동으로 여세요."
  echo
  manual_guide
  exit 0
fi

echo "==> OCI CLI 로 자동 개방을 시도합니다"

# 인스턴스 메타데이터에서 VNIC → 서브넷 → Security List 를 역추적한다.
INSTANCE_ID="$(curl -fsS -H 'Authorization: Bearer Oracle' \
  http://169.254.169.254/opc/v2/instance/id 2>/dev/null || true)"

if [[ -z "$INSTANCE_ID" ]]; then
  echo "[!] 인스턴스 메타데이터를 못 읽었습니다 (OCI 인스턴스 안에서 실행해야 합니다)."
  echo
  manual_guide
  exit 0
fi

COMPARTMENT_ID="$(curl -fsS -H 'Authorization: Bearer Oracle' \
  http://169.254.169.254/opc/v2/instance/compartmentId)"

SUBNET_ID="$(oci compute instance list-vnics \
  --instance-id "$INSTANCE_ID" --query 'data[0]."subnet-id"' --raw-output 2>/dev/null || true)"

if [[ -z "$SUBNET_ID" ]]; then
  echo "[!] 서브넷을 조회하지 못했습니다. OCI CLI 인증(oci setup config)이 필요합니다."
  echo
  manual_guide
  exit 0
fi

SL_ID="$(oci network subnet get --subnet-id "$SUBNET_ID" \
  --query 'data."security-list-ids"[0]' --raw-output)"

echo "    Security List: ${SL_ID}"

# 기존 규칙을 읽어와 필요한 것만 덧붙인다 (기존 규칙을 날리지 않도록).
EXISTING="$(oci network security-list get --security-list-id "$SL_ID" \
  --query 'data."ingress-security-rules"' --raw-output)"

NEW_RULES="$EXISTING"
add_rule() {  # add_rule <proto-num> <port>   (6=TCP, 17=UDP)
  local proto="$1" port="$2" key
  key=$([[ "$proto" == "6" ]] && echo tcpOptions || echo udpOptions)
  if jq -e --arg p "$proto" --argjson port "$port" --arg k "$key" \
       'any(.[]; .protocol == $p and .[$k].destinationPortRange.min == $port)' \
       <<<"$NEW_RULES" >/dev/null; then
    echo "    이미 열림: proto=${proto} port=${port}"
    return
  fi
  NEW_RULES="$(jq --arg p "$proto" --argjson port "$port" --arg k "$key" \
    '. + [{
        protocol: $p,
        source: "0.0.0.0/0",
        sourceType: "CIDR_BLOCK",
        isStateless: false,
        ($k): { destinationPortRange: { min: $port, max: $port } }
     }]' <<<"$NEW_RULES")"
  echo "    추가: proto=${proto} port=${port}"
}

for p in "${PORTS_TCP[@]}"; do add_rule 6  "$p"; done
for p in "${PORTS_UDP[@]}"; do add_rule 17 "$p"; done

if [[ "$NEW_RULES" == "$EXISTING" ]]; then
  echo "==> 변경 사항 없음. 이미 전부 열려 있습니다."
  exit 0
fi

TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
printf '%s' "$NEW_RULES" >"$TMP"

oci network security-list update \
  --security-list-id "$SL_ID" \
  --ingress-security-rules "file://${TMP}" \
  --force >/dev/null

echo "==> 완료. 포트가 열렸습니다."
