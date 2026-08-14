# 개인 VPN 노드 구축

상용 VPN 구독을 대체하기 위한 자가 구축 설정. 오라클 클라우드 프리티어 기준.

목적은 두 가지다.

1. **중국 출장 중** 한국에서만 열리는 프로그램·서비스에 접속한다.
2. **한국에 있을 때** 한국에서 막히는 중국 서비스에 접속한다.

---

## 0. 먼저 알아야 할 것

### 돈은 별로 안 아낀다

오라클 프리티어를 쓰면 서울 노드는 **월 0원**이다. 여기까지는 확실한 절감이다.
하지만 홍콩 노드는 프리티어로 못 만든다(아래 §6 참고). 결국 상용 VPN 대비
절감액은 월 몇 달러 수준이다.

**진짜 이득은 다른 데 있다.**

| | 상용 VPN | 자가 구축 |
|---|---|---|
| IP | 수백 명이 공유 | 나 혼자 |
| 한국 은행·정부 사이트 | 공유 IP라 자주 차단·캡차 | 정상 통과 |
| 로그 | 업체를 믿어야 함 | 내 서버 |
| 막혔을 때 | 업체가 고쳐줌 | **내가 고쳐야 함** |
| 속도 | 서버 혼잡에 좌우 | 나 혼자 씀 |

마지막 줄이 진짜 비용이다. 중국 출장 중에 IP가 막히면 직접 복구해야 하는데,
중국 안에서 이 작업을 하는 게 상당히 번거롭다. 그래서 이 설정은 **채널 3개를
동시에** 올린다. 하나가 막혀도 나머지로 붙기 위해서다.

### 평범한 WireGuard·OpenVPN은 중국에서 막힌다

GFW가 핸드셰이크 지문을 잡아낸다. 그래서 중국용 채널은 다른 걸 쓴다.

| 채널 | 포트 | 용도 |
|---|---|---|
| **VLESS + XTLS-Reality** | TCP 443 | 중국에서 1순위. 실제 사이트의 TLS 인증서를 빌려 위장 |
| **Hysteria2** | UDP 443 | 손실 많은 회선에서 훨씬 빠름. TCP가 막혔을 때의 대안 |
| **WireGuard** | UDP 51820 | 중국 밖에서 쓰는 단순·고속 채널 |

### 법적 사항

중국에서는 국가 인가를 받은 VPN만 합법이고, 미인가 국경 간 VPN은 규정 위반이다.
출장자 개인에 대한 단속은 드물지만 실재한다.

**회사 업무 데이터가 오간다면** 인가 통신사의 IPLC 전용회선이나 라이선스된
클라우드 VPN 게이트웨이가 규정에 맞는 경로다. 개인 용도면 아래대로 진행하되,
회사 계정·자산이 오간다면 IT 담당과 한 번 확인하는 편이 좋다.

### 이 저장소는 public이다

**생성되는 키·서버 IP는 절대 커밋하면 안 된다.** `.gitignore`가 막고 있지만,
`git add -f` 같은 걸로 강제하지 말 것. 가능하면 private 저장소로 옮기는 게 좋다.

---

## 1. 오라클 클라우드 계정 만들기

https://www.oracle.com/kr/cloud/free/

가입 시 카드 인증이 필요하지만 **Always Free 리소스는 과금되지 않는다.**

### ⚠️ 홈 리전을 반드시 `한국 중부(서울)`로 고를 것

Always Free 리소스는 **홈 리전에서만** 만들 수 있고, **홈 리전은 나중에 바꿀 수 없다.**

중국 출장 중 한국 접속이 더 급한 용도이므로 서울을 고른다.
(춘천 리전도 한국이지만 서울이 중국발 경로가 대체로 낫다.)

---

## 2. 인스턴스 만들기

Compute → Instances → Create Instance

### 이미지·형태

- **Image**: Canonical Ubuntu 24.04
- **Shape**: 아래 둘 중 하나

| Shape | 사양 | 대역폭 | 비고 |
|---|---|---|---|
| `VM.Standard.A1.Flex` (ARM) | 최대 4 OCPU / 24GB 무료 | 1 Gbps/OCPU | **권장.** 다만 자리 없을 때가 많음 |
| `VM.Standard.E2.1.Micro` (AMD) | 1/8 OCPU / 1GB | 50 Mbps | 거의 항상 생성됨. VPN엔 충분하나 영상은 답답 |

> **"Out of host capacity" 오류가 뜨면** ARM 자리가 없는 것이다. 흔한 일이다.
> 몇 시간~며칠 간격으로 재시도하거나, 일단 AMD micro로 만들어 쓰다가
> 나중에 ARM으로 옮기면 된다. 1 OCPU / 6GB 정도로 낮춰 요청하면 붙을 확률이 올라간다.

### SSH 키

"Save private key"로 개인키를 받아 안전한 곳에 보관한다. 이게 없으면 서버에 못 들어간다.

### 접속

```bash
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<인스턴스_공인IP>
```

---

## 3. 서버 설치

### 3-1. 위장 도메인 고르기

Reality는 실존 사이트의 인증서를 빌려 위장한다. 조건이 있다.

```bash
sudo apt update && sudo apt install -y git
git clone --depth 1 https://github.com/jcrkorea11-cyber/rtms-data.git
cd rtms-data/vpn
bash server/check-dest.sh
```

`사용 가능` 으로 나오는 것 중에서 고른다. 서버가 한국에 있으므로 **한국에 실제로
호스팅된 사이트**를 고르면 "한국 IP로 가는 한국 사이트 트래픽"이라 그림이 자연스럽다.

⚠️ **google / facebook / youtube 계열은 쓰면 안 된다.** 중국에서 차단된 도메인을
위장에 쓰면 오히려 눈에 띈다.

### 3-2. 설치

```bash
sudo bash server/setup.sh seoul www.samsung.com
```

3~5분 걸린다. 끝나면 `/root/vpn-out/node-seoul.env` 에 접속 정보가 생긴다.

### 3-3. ⚠️ OCI 방화벽 열기 — 이걸 빼먹으면 절대 안 붙는다

OCI는 방화벽이 2겹이다. `setup.sh`가 인스턴스 안쪽(iptables)은 처리했지만,
**클라우드 레벨의 Security List는 콘솔에서 따로 열어야 한다.**

```bash
bash server/open-ports.sh          # OCI CLI 있으면 자동
bash server/open-ports.sh --help   # 콘솔에서 수동으로 하는 방법
```

열어야 할 포트: **TCP 443 / UDP 443 / UDP 51820** (소스 `0.0.0.0/0`)

> UDP 규칙을 빼먹으면 Hysteria2와 WireGuard가 **에러 없이 조용히 실패한다.**
> 원인 찾기 제일 어려운 유형이니 꼭 확인할 것.

---

## 4. 클라이언트 설정

### 4-1. 기기별 접속 정보 생성

```bash
sudo bash client/gen-clients.sh /root/vpn-out/node-seoul.env iphone
sudo bash client/gen-clients.sh /root/vpn-out/node-seoul.env macbook
```

터미널에 QR이 바로 뜬다. 폰은 그대로 스캔하면 된다.

### 4-2. 스플릿 터널링 프로파일 (핵심)

VPN을 켰다 껐다 할 필요를 없애는 부분이다. 목적지를 보고 알아서 경로를 나눈다.

```bash
bash client/gen-singbox.sh china /root/vpn-out/node-seoul.env
bash client/gen-singbox.sh korea /root/vpn-out/node-hongkong.env   # 홍콩 노드 만든 뒤
```

| 프로파일 | 중국 사이트 | 그 외 |
|---|---|---|
| `china` (출장 중) | 직결 — 현지에서 빠르게 | 서울 노드 경유 |
| `korea` (한국) | 홍콩 노드 경유 | **직결** — 평소 인터넷 속도에 영향 없음 |

### 4-3. 앱

| 기기 | 앱 | 설정 방식 |
|---|---|---|
| iPhone | **sing-box** (App Store) / Shadowrocket | `sing-box-china.json` 임포트 |
| Android | **sing-box** (GitHub Releases) | 동일 |
| macOS | **sing-box** / V2rayU | 동일 |
| Windows | **sing-box** / v2rayN | 동일 |

sing-box 하나로 전 기기를 통일하면 프로파일 파일이 그대로 호환된다. **sing-box 1.12 이상**이 필요하다.

⚠️ **중국 앱스토어에서는 이 앱들이 내려가 있다.** 반드시 **출국 전에 설치**할 것.

---

## 5. 출장 전 체크리스트

중국에 도착해서 처음 설정하려고 하면, 설정에 필요한 사이트들이 이미 막혀 있어서
손을 못 쓴다. 아래는 **반드시 출국 전에** 끝낸다.

- [ ] 폰·노트북에 sing-box 설치 완료
- [ ] `sing-box-china.json` 임포트 완료
- [ ] **한국에서 실제로 켜서 접속 테스트** (`whatismyip` 로 서울 노드 IP 확인)
- [ ] Hysteria2 채널로도 전환해서 붙어보기 (1순위가 막혔을 때 쓸 것)
- [ ] `node-seoul.env` 파일을 폰에도 사본 보관 (재설정용, 암호화된 메모앱에)
- [ ] OCI 콘솔 로그인이 폰에서 되는지 확인 (IP 교체할 때 필요)
- [ ] 한국 통신사 로밍 활성화 — **최후의 보루**

> **로밍은 진짜 최후의 보루다.** 한국 통신사 로밍 트래픽은 한국망을 타므로
> GFW를 우회한다. VPN이 전부 죽어도 로밍으로는 OCI 콘솔에 붙어서 복구할 수 있다.

---

## 6. 홍콩 노드 (2단계)

한국에서 중국 서비스에 접속하는 용도. **오라클 프리티어로는 만들 수 없다** —
Always Free는 홈 리전(서울) 전용이기 때문이다.

선택지:

| 방법 | 비용 | 비고 |
|---|---|---|
| 오라클 홍콩 유료 ARM | 약 $5/월 | 같은 콘솔에서 관리. 1 OCPU/6GB |
| 알리클라우드 홍콩 경량 | 약 $5~8/월 | **중국 본토 경로가 제일 좋음** |
| 텐센트클라우드 홍콩 경량 | 약 $4~7/월 | 위와 비슷 |

만드는 방법은 서울과 동일하다.

```bash
sudo bash server/setup.sh hongkong www.apple.com
```

> **먼저 서울 노드만 만들어서 써보길 권한다.** 급한 건 출장 문제고, 한국에서
> 중국 서비스 접속은 실제로 얼마나 자주 필요한지 겪어본 뒤 결정해도 늦지 않다.

---

## 7. 문제 해결

### 중국에서 갑자기 안 될 때

```bash
bash ops/healthcheck.sh <서버IP>
```

순서대로 시도한다.

1. **Hysteria2(UDP 443)로 전환** — TCP만 막히는 경우가 흔하다
2. 그래도 안 되면 **IP가 차단된 것**이다. OCI 콘솔에서 새 공인 IP를 받는다.
   `Instance → Attached VNICs → IPv4 Addresses → Edit`
   (Ephemeral IP는 해제 후 재할당하면 새 IP를 받는다)
   그다음 `node-seoul.env`의 `SERVER_IP`를 고치고 클라이언트 설정을 다시 만든다.
3. OCI 콘솔 접속조차 안 되면 **한국 통신사 로밍**으로 붙는다.

### 프리티어 인스턴스가 회수됐을 때

오라클은 **7일간 유휴 상태인 Always Free 인스턴스를 회수한다.** 출장을 안 다니는
동안 VPN을 안 쓰면 그대로 날아갈 수 있다.

**해결책: 계정을 Pay As You Go로 업그레이드한다.** Always Free 리소스는 계속
무료로 유지되면서 회수 대상에서 빠진다. 실제 청구는 발생하지 않는다.

### 속도가 느릴 때

- AMD micro 인스턴스는 **50 Mbps 상한**이 있다. ARM으로 옮기면 1 Gbps/OCPU다.
- 중국↔한국 국제 회선은 **저녁 시간대(현지 20~24시)에 심하게 혼잡하다.** 서버 문제가 아니다.
- Hysteria2로 바꿔본다. 손실률이 높은 구간에서 TCP 기반보다 훨씬 낫다.

### 무료 트래픽 한도

월 **10 TB** 아웃바운드. 개인 용도로는 넘길 일이 없다.

---

## 8. 파일 구성

```
vpn/
├── server/
│   ├── setup.sh          서버 설치 (Reality + Hysteria2 + WireGuard)
│   ├── open-ports.sh     OCI Security List 개방
│   └── check-dest.sh     Reality 위장 도메인 후보 검사
├── client/
│   ├── gen-clients.sh    기기별 접속 링크·QR·WireGuard 설정 생성
│   └── gen-singbox.sh    스플릿 터널링 프로파일 생성
├── ops/
│   └── healthcheck.sh    채널 점검 (막혔을 때 원인 판별)
└── .gitignore            키·IP 커밋 방지
```

**커밋되는 것은 스크립트뿐이다.** 서버 IP·키·클라이언트 설정은 전부 `.gitignore`에
걸려 있고 서버에서만 생성된다.
