# compman — Docker Compose 스택 관리 CLI

[ English | [한국어](README.ko.md) ]

**프로젝트 홈페이지:** https://allbegray.github.io/compman/

`compman`은 Docker·Podman Compose 스택을 하나의 CLI로 관리합니다. 서비스
실행과 조회, 볼륨·이미지 백업과 복구, 무인 백업 스케줄링, S3·HTTPS 배포,
그리고 스택 기동 시 슬랙 알림까지 담당합니다.

데몬도, 웹 UI도, 열리는 포트도 없습니다. 이미 가지고 있는 Docker/Podman CLI를
그대로 호출하므로, 관리 플랫폼을 설치할 수 없는 격리 호스트·점프박스·제한된
네트워크에서도 동작합니다.

## 주요 기능

- Docker Compose, Podman Compose, `podman-compose`, `docker-compose` 자동 감지
- 프로파일별 env 변수와 AWS Secrets Manager 주입을 지원하는 프로파일 기반 `compose` 설정
- 프로젝트 범위 `ps`·`stats`, 그리고 CI용 텍스트/JSON `status`·`doctor`
- 타임스탬프 기반 볼륨·이미지 백업, 기본 gzip, `--zstd`로 Zstandard 지원
- 로컬·S3·SSH/SCP 백업 저장소, launchd/systemd/cron/schtasks 스케줄 작업 등록
- SHA-256 고정과 HTTPS 헤더 인증을 갖춘 S3/HTTP 아카이브 배포
- `stack up`/`stack update` 시 장애 서비스와 볼륨 정보를 담은 슬랙 알림
- 한국어·영어 도움말, 셸 완성, Windows/macOS/Linux 지원

## 요구 사항

- Python 3.12 이상 (`--zstd`는 stdlib `compression.zstd`를 제공하는 3.14+ 필요)
- Docker Compose 또는 Podman Compose
- S3 사용 시: 접근 가능한 S3 호환 스토리지와 AWS 자격 증명
- 인증 HTTP 배포 시: HTTPS 아카이브 URL과 환경 변수에 담은 토큰

CI는 Ubuntu·macOS·Windows에서 Python 3.12–3.14를 실행합니다. 태그가 지정된
릴리즈마다 휠이 PyPI에 게시됩니다.

## 설치

```bash
uv tool install compman          # 권장, 자기 완결형
pipx install compman             # 동일하게 동작
```

또는 번들 설치 스크립트를 실행해 CLI를 `PATH`에 올립니다:

```bash
curl -fsSL https://raw.githubusercontent.com/allbegray/compman/main/install.sh | sh          # Linux / macOS
irm https://raw.githubusercontent.com/allbegray/compman/main/install.ps1 | iex               # Windows PowerShell
```

이후 `compman --version`으로 확인합니다. 설치된 도구는 `compman upgrade`로
제자리에서 갱신할 수 있습니다. 설치가 손상되어 `upgrade`가 실행되지 않으면
언제나 고정하지 않은 **동반 버전**의 상위 소스로 재설치하세요. 그래야 이후
`uv tool upgrade`가 새 릴리즈로 계속 이동할 수 있습니다:

```bash
uv tool uninstall compman
uv tool install --managed-python git+https://github.com/allbegray/compman.git
```

개발용 체크아웃에서는 `uv tool install .`을 쓰고 저장소에서 직접 실행하세요.

## 빠른 시작

```bash
cd my-project
compman init --scaffold     # 또는 `compman init` 실행으로 대화형 메뉴
compman stack up
compman status
```

빈 디렉터리에 배포하면 `compman deploy`가 설정 파일까지 만들어 줍니다:

```bash
mkdir my-app && cd my-app
compman deploy --path s3://my-bucket/releases/app.tar.gz --build --tag my-app
compman stack up
```

```
my-app/
├── compman.yml
├── docker-compose.yml
└── project/              # S3/HTTP에서 가져온 소스
```

## 설정

모든 설정은 `compman.yml`의 `compman` 키 아래에 둡니다. JSON 스키마가
[`docs/site/compman.schema.json`](docs/site/compman.schema.json)에 게시되어
있습니다. 이 줄을 맨 위에 추가하면 IDE 자동완성과 검증을 쓸 수 있습니다:

```yaml
# yaml-language-server: $schema=https://allbegray.github.io/compman/compman.schema.json
```

실제 예시: [`examples/compman-config/`](examples/compman-config/)
(목록은 [`examples/README.md`](examples/README.md))

### Compose 프로파일

`compose`는 **필수**이며 **프로파일 매핑**이어야 합니다. 프로파일 하나로도
충분하고, 여러 개를 두면 배포 환경별로 전환할 수 있습니다.

```yaml
compman:
  name: my-stack
  compose:
    base: docker-compose.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: dev.db.example.com
    prod:
      file: docker-compose.prod.yml
      env:
        DATABASE_URL: prod.db.example.com
```

```bash
compman stack up dev
```

프로파일 `file`은 선택 사항입니다. 생략하면 `base`, 그것도 없으면
`docker-compose.yml`을 사용합니다. 덕분에 하나의 Compose 파일을 환경 변수만
바꾸어 재사용할 수 있습니다.

### 키

| 키 | 용도 |
|----|------|
| `name` | 스택 이름. 생략하면 설정 디렉터리 이름 |
| `folder` | Compose 파일이 있는 하위 디렉터리 |
| `compose` | **필수.** 프로파일 매핑. `base:`는 공용 Compose 파일 추가 |
| `dirs.project` | 관리 대상 배포 소스 트리 |
| `dirs.backup` | 아카이브 목적지: 로컬 경로, `s3://bucket/prefix`, `ssh://[user@]host[:port]/path` |
| `dirs.volume` | 호스트↔컨테이너 볼륨 전송용 임시 디렉터리 |
| `deploy` | `deploy`/`update` 기본 소스: `s3://…`, HTTPS 아카이브 URL, 또는 매핑(아래) |
| `secrets` | AWS Secrets Manager 항목. `${secrets:NAME}`으로 참조 |
| `notify.slack` | 슬랙 웹훅 설정([알림](#알림) 참고) |
| `limits.max_archive_mb` | 가져올 배포 소스 크기 상한 |
| `limits.max_backups` | 스택·종류별 최신 N개 아카이브만 유지 |

관리 경로는 설정 디렉터리 기준으로 해석되며 그 밖으로 벗어날 수 없습니다.
`--path`는 한 번의 실행에 대해서만 `deploy` 값을 덮어씁니다.

### 시크릿

`secrets` 아래에 `{ arn, key }` 쌍을 선언하고, 프로파일 `env`에서
`${secrets:NAME}`으로 참조합니다. compman이 compose 컨텍스트를 만들 때 `key`
위치의 값을 치환해 `docker compose` 프로세스 환경으로 넘기므로, Compose 파일은
여전히 `${VAR}`을 사용합니다.

```yaml
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}@db.example.com
  secrets:
    DB_USER:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/user
```

- 마커가 있는 위치에만 주입되며 standalone compose 변수로 전달되지 않습니다. 선언되지 않은 이름을 참조하면 명령이 실패합니다.
- `key`는 slash 경로일 수 있습니다. 부분 치환이 가능하고 마커는 시스템 변수 참조 옆에도 놓일 수 있습니다.
- 프로파일 `secrets` 블록이 최상위 블록보다 우선합니다. 같은 ARN은 실행당 한 번만 가져옵니다.
- 자격 증명이나 region이 없으면 `compman doctor`가 경고합니다.

### 배포 소스와 보장 사항

S3는 **프리픽스**(재귀 다운로드, 디렉터리 구조 유지) 또는 **아카이브**
(`.tar.gz`, `.tgz`, `.zip`, 최상위 디렉터리가 하나면 자동 평탄화)를 받습니다.
공개 HTTP/HTTPS는 아카이브만 지원하며 URL 경로가 해당 확장자로 끝나야 합니다.
같은 이름의 대상만 교체하고 사용자의 파일은 유지합니다.

매핑 형태를 쓰면 무결성 고정과 인증을 추가할 수 있습니다:

```yaml
compman:
  deploy:
    url: s3://my-bucket/releases/app.tar.gz
    sha256: <64-hex-digest>
    auth: { header: Authorization, value_env: DEPLOY_TOKEN }   # HTTPS만
```

- **트랜잙셔널 빌드.** `--build`는 managed-tree swap *이전에* 임시 소스에서 이미지를 빌드하므로, 빌드가 실패해도 기존 트리와 설정은 그대로입니다. swap이 실패하면 롤백됩니다.
- **무결성 고정.** `--sha256 HEX` 또는 `deploy.sha256`은 내려받은 뒤 추출·빌드·swap 전에 검증됩니다. 불일치 시 exit 1로 중단되고 아무 변화도 없습니다. 배포 URL이 설정된 `deploy` URL과 같을 때 적용되므로 `update`가 상속합니다.
- **토큰 처리.** 헤더 값은 fetch 시점에 `value_env`에서 읽히며 저장되거나 출력되지 않고 오류에는 변수 이름만 등장합니다. 그대로 전송되므로 Bearer 인증이라면 `Bearer <token>` 전체를 저장하세요.
- **인증은 HTTPS 필수**이며 cross-host 리디렉션에서 헤더를 제거해 토큰이 새지 않게 합니다. CDN이 리디렉션 후에도 헤더를 요구하면 한 호스트에서 서브하세요.
- `compman rollback`은 직전 성공 배포의 스냅샷을 복원합니다.

## 명령어

```text
compman init [--scaffold | --s3 URI | --seed]
compman deploy [--path SOURCE_URI] [--sha256 HEX] [--build] [--tag TAG]
compman update [PROFILE] [-c|--config PATH] [--stack NAME]
compman rollback
compman doctor [--profile PROFILE] [-c|--config PATH] [--json] [--stack NAME]
compman status [--profile PROFILE] [-c|--config PATH] [--json] [--stack NAME]
compman ps [PROFILE] [-a|--all] [--json] [-c|--config PATH] [--stack NAME]
compman stats [PROFILE] [-f|--follow] [--json] [-c|--config PATH] [--stack NAME]
compman history [--limit N] [--json]
compman stacks list [--json]
compman stacks remove NAME
compman clear [--yes]
compman upgrade [--repo URL]
compman lang [ko|en]
compman version
compman completion [powershell|bash|zsh|fish] --install

compman stack up [PROFILE] [--wait] [-c|--config PATH] [--stack NAME]
compman stack update [PROFILE] [--wait] [-c|--config PATH] [--stack NAME]
compman stack down [--profile PROFILE] -c|--config PATH --yes [--stack NAME]
compman stack logs [SERVICE...] [-f] [--tail N] [--profile PROFILE] [-c|--config PATH]

compman service start|stop|restart [SERVICE...] [--profile PROFILE] [-c|--config PATH]
compman service status [--profile PROFILE] [-c|--config PATH]
compman service log [SERVICE] [-f] [-n 50] [--profile PROFILE] [-c|--config PATH]
compman service connect [SERVICE] [--profile PROFILE] [-c|--config PATH]

compman volume backup [-z LEVEL] [--zstd] [--no-stop] [--profile PROFILE] [-c|--config PATH]
compman volume restore [TIMESTAMP] [--no-stop] [--replace] [--profile PROFILE] [-c|--config PATH]
compman volume pull [--profile PROFILE] [-c|--config PATH]
compman volume push [--replace] [--profile PROFILE] [-c|--config PATH]

compman image backup [-z LEVEL] [--zstd] [--source-image] [--profile PROFILE] [-c|--config PATH]
compman image restore [TIMESTAMP] [--profile PROFILE] [-c|--config PATH]

compman schedule add [--every N | --daily HH:MM | --weekly DAY HH:MM | --monthly DD HH:MM] [--no-stop] [-z LEVEL] [--name TEXT] [--scheduler systemd|cron]
compman schedule list [--json]
compman schedule status NAME
compman schedule remove NAME
```

`-c/--config`로 설정 파일을, `--profile`로 compose 프로파일을 고르고, 전역
`--stack NAME`은 등록된 스택을 어느 디렉터리에서든 대상으로 지정합니다.
어떤 명령이든 `compman <command> --help`로 모든 옵션을 볼 수 있습니다.

### 알아둘 동작

- `update`는 재빌드 + 강제 재생성이며 **무중단 롤링 배포가 아닙니다**. `deploy`가 없으면 로컬에서 `up -d --build`를 실행합니다.
- 존재하지 않는 스택에 대한 `stack down`은 오류가 아니라 exit 0이므로 스크립트가 멱등하게 호출할 수 있습니다.
- `ps`와 `stats`는 의도적으로 프로젝트 범위입니다. 런타임 전체 결과는 `docker ps` / `podman ps`를 쓰세요.
- `service log`와 `connect`는 **서비스** 이름을 받아 `compose ps -q`로 찾습니다. 인스턴스가 0개이거나 스케일된 서비스가 여러 개면 추정하지 않고 안내와 함께 실패합니다. `connect`는 `sh`로 폴백합니다.
- `volume backup`/`restore`는 일관성을 위해 스택을 중지합니다. `--no-stop`은 이를 포기합니다. 모두 중지된 상태에서도 복구할 수 있으며, 스택을 임시로 시작해 복구한 뒤 다시 중지합니다.
- `volume restore`/`push --replace`는 대상에 없는 파일을 삭제하는 바이트 단위 교체입니다. 설계상 파괴적이며 대상은 절대 컨테이너 경로여야 합니다.
- `image backup`은 기본적으로 컨테이너 상태를 commit하고, `--source-image`를 주면 원본 이미지를 저장합니다. gzip 레벨 기본값은 6(`-z`)이고 `--zstd`는 `.tar.zst`를 쓰며 복구에도 Python 3.14+가 필요합니다.
- 아카이브 이름은 `<stack>.{volume,image}.<YYYYMMDD_HHMMSS>[_<microseconds>].tar.gz` 형식입니다.
- `clear`는 `image prune -af`를 실행하므로 현재 프로젝트 밖의 미사용 이미지도 삭제할 수 있습니다. `--yes`가 필요합니다.
- 오래 걸리는 작업은 300초 후 타임아웃하며 `COMPMAN_TIMEOUT=<초>`로 바꿀 수 있습니다. 스트리밍 명령(`log -f`, `connect`, `stats -f`)은 타임아웃하지 않습니다.

## 진단

```bash
compman doctor
compman doctor --json
compman status --json
```

`--json`은 스키마 버전 `1`을 출력합니다. `doctor`는 *필수* 점검만 실패했을
때 exit 1이고, AWS 자격 증명 누락·`deploy` 무결성 고정 누락·`deploy.auth`와
`notify.slack` 변수 미설정은 경고입니다. `status`는 스택이 없으면 exit 1이고,
모든 서비스가 중지 상태라도 스택이 존재하면 exit 0입니다.

운영 실패(Docker Desktop 준비 상태 포함)는 Python traceback 없이 간결한
메시지로 출력됩니다.

## 알림

웹훅을 설정하면 `stack up`과 `stack update`가 항상 보고합니다:

```bash
export COMPMAN_SLACK_WEBHOOK_URL='https://hooks.slack.com/services/T000/B000/XXXX'
```

호출하는 셸의 환경에서 URL을 빼두려면 스택별로 범위를 지정하세요:

```yaml
compman:
  notify:
    slack:
      webhook_env: COMPMAN_SLACK_WEBHOOK_URL   # 권장
      # webhook: https://hooks.slack.com/services/...   # 직접 적으면 이 파일에 시크릿이 남습니다
```

```text
✅ Stack started

  *Stack* notify-demo  ·  *Profile* default
  *Runtime* docker     ·  *Host* build-host
  *Started at* 2026-10-02 20:06 KST  ·  *Duration* 681ms

  *Services* — 3 of 3 healthy

  ────────────────────────────────────────
  *Volumes* (2)
  🟢 notify-demo_web-data · web:/usr/share/nginx/html · 1.393kB
  🟢 notify-demo_pgdata · db:/var/lib/postgresql/data · 40.01MB

compman 1.12.0 · stack up
```

해석 순서는 `webhook`, `webhook_env`가 가리키는 변수, `COMPMAN_SLACK_WEBHOOK_URL`
순서이며, 마지막 것은 파일에 `notify.slack` 블록이 없을 때만 적용됩니다.
자기 변수를 지정한 스택은 전역 변수로 대체되지 않습니다.

서비스는 정상 개수로 요약하고 **정상이 아닌 것만** 나열하며, 각 줄에 state,
exit code, 이미지 태그, 공개된 포트가 함께 표시됩니다. 하나라도 정상이 아니면
헤드라인이 `⚠️ … N service(s) need attention`로 바뀌고, 장애 난 서비스가 쓴
볼륨은 🔴로 표시해 원인을 짚어줍니다.

전송은 best-effort이며 종료 코드에 영향을 주지 않습니다. 알림 시점에는 이미
컨테이너가 실행 중이므로 장애나 폐기된 웹훅, 변수 미설정은 stderr에 경고만
남기고 exit `0`입니다. `stack down`·백업·복구는 알림을 보내지 않아 백업 과정의
임시 재기동은 조용합니다.

볼륨 **용량**은 `docker system df -v`에서 가져옵니다. Docker에서 크기를 노출하는
유일한 경로이며 호스트 전체를 스캔하므로, compose 파일에 명명된 볼륨이 선언되어
있고 알림이 켜져 있을 때만 실행합니다. 그렇지 않으면 볼륨을 마운트 경로와 함께
계속 표시하고 용량만 생략합니다.

## 백업과 스케줄링

`dirs.backup`은 로컬 경로, `s3://bucket/prefix`,
`ssh://[user@]host[:port]/path`를 받습니다. 원격 저장소는 로컬에 스테이징한 뒤
업로드하고 크기를 검증한 다음 스테이징본을 지웁니다. SSH 모드는
`BatchMode=yes`로 `scp`/`ssh`를 구동하며 키는 이미 프로비저닝된 것으로 봅니다.

```bash
compman schedule add --daily 04:30 --no-stop
compman schedule add --every 30m
compman schedule add --monthly 1 05:00
compman schedule status my-stack.volume
compman schedule remove my-stack.volume
```

캐던스 옵션은 정확히 하나가 필요합니다. 플랫폼 메커니즘은 자동 선택됩니다:
macOS는 launchd, Windows는 schtasks, Linux는 systemd user timer 또는 crontab
(`--scheduler systemd|cron`으로 Linux 메커니즘 강제). cron은 모든 간격을 표현할
수 없어 `--every` 값이 60분을 나누거나 정수 시간이어야 합니다. 출력과 실행 기록은
`schedules.json` 옆, `APPDATA`가 설정되어 있으면 `%APPDATA%\compman`, 없으면
`~/.config/compman`에 쌓입니다. 레지스트리 구성은
[`docs/site/`](docs/site/)를 참고하세요.

## 런타임과 환경 변수

감지 순서는 `docker compose` → `podman compose` → `podman-compose` →
`docker-compose`입니다. `CONTAINER_RUNTIME=podman`으로 강제할 수 있습니다.

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-northeast-2
export AWS_ENDPOINT_URL_S3=http://localhost:4566   # Ministack/LocalStack
export COMPMAN_TIMEOUT=600                         # 초 단위, 기본 300
export COMPMAN_LANG=ko                             # 또는 실행마다 --lang ko
```

Windows + Docker에서는 `stack up`, `stack update`, 배포 빌드가 Docker Desktop
준비 상태를 확인하고 실행을 제안합니다. 비대화형 실행은 Docker Desktop을 절대
시작하지 않으며, 읽기 전용·백업·종료 경로는 점검을 건너뜁니다.

## 더 보기

| 문서 | 내용 |
|------|------|
| [examples/compman-config/](examples/compman-config/) | 케이스별 `compman.yml` 예제 14개 |
| [CHANGELOG.md](CHANGELOG.md) | 릴리즈 이력 |
| [SECURITY.md](SECURITY.md) | 자격 증명 모델, 시크릿 처리, 신고 방법 |
| [BACKLOG.md](BACKLOG.md) | 제약과 진행 중인 작업 |
| [AGENTS.md](AGENTS.md) | 개발·테스트·릴리즈 규칙 |
| [SOLUTION.md](SOLUTION.md) | 디버깅과 설계 교훈 |
| [홈페이지](https://allbegray.github.io/compman/) | 검색 최적화된 프로젝트 사이트 |

## 라이선스

MIT — [LICENSE](LICENSE)를 참고하세요.
