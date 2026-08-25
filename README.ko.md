# compman: Docker Compose 스택 관리 CLI

[ [English](README.md) | 한국어 ]

`compman`은 Docker 또는 Podman Compose 스택을 하나의 CLI에서 관리합니다. 실행, 서비스 작업, 볼륨과 이미지 백업, S3 또는 HTTP 아카이브 배포까지 모두 포함합니다.

**프로젝트 홈페이지:** https://allbegray.github.io/compman/

## 이 도구는 누구를 위한 것인가요?

웹 GUI를 쓸 수 없고, 방화벽은 쓸 만한 것을 전부 막고, 무거운 관리 소프트웨어는 설치할 수 없어 어쩔 수 없이 raw Docker 명령어만 남은 환경에서 일하는 용감하고 약간 불행한 분들을 위한 도구입니다.

편리한 옵션을 하나하나 "안 됩니다"라는 답으로 들어왔다면, `compman`이 당신을 위한 도구입니다.

## 주요 기능

- Docker Compose와 Podman Compose 런타임을 자동으로 감지합니다
- 프로파일별 env 변수와 시크릿을 갖는 프로파일 기반 `compose` 설정을 사용합니다
- `ps`와 `stats`로 현재 프로젝트의 컨테이너만 조회하고 모니터링합니다
- S3 프리픽스/아카이브 또는 HTTP/HTTPS `.tar.gz`/`.tgz`/`.zip` 아카이브에서 배포하며, 선택적 HTTPS 헤더 인증과 SHA-256 무결성 고정을 지원합니다
- 비어 있는 디렉터리에 배포할 때 `compman.yml`과 `docker-compose.yml`을 자동 생성합니다
- 볼륨과 컨테이너 이미지의 타임스탬프 백업을 만들고 복구합니다
- `dirs.backup`(`s3://bucket/prefix`)을 통해 백업을 로컬 디렉터리 또는 S3 호환 버킷에 저장합니다
- 한국어/영어 도움말과 셸 완성을 제공합니다
- Windows, Linux, macOS를 지원합니다

## 요구 사항

- Python 3.12 이상
- Docker Compose 또는 Podman Compose
- S3 배포와 S3 백업 저장소: 접근 가능한 S3 호환 스토리지와 AWS 자격 증명
- HTTP 배포: 공개 아카이브 URL, 또는 `deploy.auth` 설정으로 인증하는 HTTPS URL(토큰은 환경 변수로 제공)

CI는 Ubuntu, macOS, Windows에서 Python 3.12~3.14를 검증합니다. Python 3.14 지원 계획과 업그레이드 결정은 [BACKLOG.md](BACKLOG.md)의 `Python version strategy` 섹션을 참고하세요.

`main` 푸시의 CI가 성공하면 `pyproject.toml`의 버전으로 annotated 태그가 자동 생성됩니다. 버전을 올릴 때는 반드시 `CHANGELOG.md`에 맞는 날짜 섹션을 추가해야 하며, 기존 태그는 절대 옮기지 않습니다. 배포된 wheel은 PyPI에 올라가므로 `uv tool install compman`(또는 `pipx install compman`)으로 PyPI에서 설치할 수 있습니다.

## 설치

### 자동 설치

```powershell
# Windows PowerShell
irm https://raw.githubusercontent.com/allbegray/compman/main/install.ps1 | iex
```

```cmd
:: Windows CMD
curl -fsSL https://raw.githubusercontent.com/allbegray/compman/main/install.cmd -o %TEMP%\install.cmd && call %TEMP%\install.cmd
```

```bash
# Linux / macOS
curl -fsSL https://raw.githubusercontent.com/allbegray/compman/main/install.sh | sh
```

새 터미널을 연 뒤 설치를 확인합니다.

```bash
compman -v       # --version also works
compman -h       # --help also works
```

### uv로 설치

compman의 Python 인터프리터를 uv가 관리하게 합니다(managed Python을 내려받으므로 3.9 같은 오래된 Python이 깔린 시스템에서도 동작합니다):

```bash
uv tool install --force --managed-python git+https://github.com/allbegray/compman.git
```

저장소에서 개발 버전을 설치하려면 다음을 실행합니다:

```bash
uv tool install .
```

설치된 CLI는 uv에 저장된 tool source로 업데이트합니다:

```bash
compman upgrade
```

이 명령은 `uv tool upgrade compman --reinstall --managed-python --python 3.13`을 실행합니다. 다른 Git 저장소에서 업그레이드를 받으려면 `--repo URL`을 전달합니다(uv를 사용할 수 없을 때의 pip 폴백에만 사용됩니다):

```bash
compman upgrade --repo https://github.com/your-fork/compman.git
```

### 손상된 설치 복구

설치가 손상되어 `compman upgrade`를 실행할 수 없다면 upstream Git 소스에서 다시 설치합니다. 이 소스를 고정하지 않고 두면 이후 `uv tool upgrade` 명령이 계속 최신 릴리스로 이동할 수 있습니다:

```bash
uv tool uninstall compman
uv tool install --force --managed-python git+https://github.com/allbegray/compman.git
compman --version
```

## 빠른 시작

### 기존 Compose 프로젝트

```bash
cd my-project
compman init --scaffold
compman stack up
compman service status
compman stack down --yes
```

인자 없이 `compman init`을 실행하면 이 세 가지 모드를 담은 대화형 메뉴가 표시됩니다.

```bash
compman init --scaffold                         # Create compman.yml
compman init --s3 s3://bucket/app.tar.gz --build
compman init --seed -o project -p 18080         # Create a test project
compman init --seed -o project -a               # Create a test project and archive
```

기존 파일을 덮어쓰려면 명시적인 `--force`가 필요합니다.

### S3 또는 HTTP에서 새 프로젝트 배포

비어 있는 작업 디렉터리에서 실행합니다.

```bash
mkdir my-app && cd my-app
compman deploy --path s3://my-bucket/releases/app.tar.gz --build --tag my-app
compman stack up
```

배포가 성공하면 이 파일 구조가 만들어집니다.

```text
my-app/
├── compman.yml
├── docker-compose.yml
└── project/              # Application source downloaded from S3
```

S3 경로는 두 가지 형식을 지원합니다.

- 프리픽스: 경로 아래의 객체를 재귀적으로 내려받고 디렉터리 구조를 유지합니다.
- 아카이브: `.tar.gz`, `.tgz`, `.zip`을 안전하게 추출합니다. 최상위 디렉터리가 하나뿐이면 자동으로 평탄화합니다.

공개 HTTP/HTTPS URL은 아카이브만 지원합니다. 쿼리 문자열은 허용되지만 URL 경로가 `.tar.gz`, `.tgz`, `.zip`으로 끝나야 합니다.

```bash
compman deploy --path https://example.com/releases/app.zip --build --tag my-app
```

같은 이름의 배포 대상만 교체하고 다른 사용자 파일은 유지합니다. `--build`를 쓰면 교체(swap) 전에 임시 소스에서 이미지를 빌드하므로, 빌드가 실패해도 기존 트리와 설정은 그대로입니다. 소스 교체 단계가 실패하면 이전 트리를 복원합니다. swap 이후의 스캐폴드 생성 실패만이 새 소스 트리를 그 자리에 남길 수 있습니다.

배포 소스는 SHA-256 다이제스트로 known-good 아티팩트에 고정할 수 있습니다. 한 번의 실행에만 적용하려면 `--sha256 HEX`를 전달하고, `compman.yml`에서 `deploy`를 매핑(`{ url: ..., sha256: ... }`)으로 설정해도 됩니다. 내려받은 소스는 추출, 이미지 빌드, managed-tree swap 전에 검증되며, 불일치 시 exit status 1로 배포를 중단하고 디스크에는 아무 변경도 남기지 않습니다. 이 고정은 배포 소스 URL이 설정된 `deploy` URL과 같을 때 항상 적용되므로 `compman update`가 자동으로 상속합니다.

HTTPS 배포 소스는 `deploy`의 매핑 형태에 선택적 `auth` 블록으로 인증할 수 있습니다: `{ url: https://..., sha256?: ..., auth?: { header, value_env } }`. fetch 시점에 compman은 `value_env`가 가리키는 환경 변수에서 헤더 값을 읽습니다. 토큰은 `compman.yml`에 저장되지도, 출력에 노출되지도 않으며, 오류 메시지는 변수 이름만 언급합니다. 헤더는 `<env value>` 그대로 전송되므로 Bearer 인증이라면 변수에 `Bearer <token>` 문자열 전체를 넣어야 합니다.

인증 소스는 `https://`를 요구합니다. plain `http://`에 `auth`를 조합하면 설정 오류입니다. cross-host 리디렉션에서는 따라가기 전에 auth 헤더를 제거해 토큰이 리디렉션 대상으로 새지 않게 하고, same-host 리디렉션에서는 헤더를 유지합니다. CDN이 리디렉션 후에도 헤더를 요구한다면 아카이브를 같은 호스트에서 서브하세요. 인증은 배포 소스 URL이 설정된 `deploy` URL과 같을 때만 적용되며, 명시적인 `--path` 배포는 인증되지 않습니다(문서화된 제한). `deploy.auth`가 설정됐는데 환경 변수가 unset이면 `compman doctor`가 경고합니다.

## 설정 파일

모든 설정은 `compman.yml`의 `compman` 키 아래에 둡니다.

케이스별 예제는 [`examples/compman-config/`](examples/compman-config/)를 참고하세요(색인은 [`examples/README.md`](examples/README.md)).

### 프로파일 기반 Compose 설정

`compose`는 필수이며 프로파일의 매핑이어야 합니다. Compose 파일 하나에는 프로파일 하나면 충분합니다:

```yaml
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
```

여러 프로파일은 환경별로 Compose 파일과 환경 변수를 선택합니다:

```yaml
compman:
  name: my-stack
  compose:
    base: docker-compose.yml
    local: docker-compose.local.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: dev.db.example.com
        LOG_LEVEL: debug
    prod:
      file: docker-compose.prod.yml
      env:
        DATABASE_URL: prod.db.example.com
```

프로파일의 `file`은 선택입니다. 생략하면 `base`를 쓰고, `base`도 없으면 `docker-compose.yml`을 씁니다. 이렇게 하면 Compose 파일 하나로 환경마다 다른 환경 변수를 쓸 수 있습니다.

```bash
compman stack up dev
compman service status --profile dev
compman stack down --profile dev --yes
```

### 배포 및 관리 디렉터리

```yaml
compman:
  name: my-stack
  deploy: s3://my-bucket/releases/app.tar.gz
  folder: compose
  dirs:
    project: project
    backup: backup
    volume: volume
  compose:
    default:
      file: docker-compose.yml
```

- `folder`: Compose 파일이 들어 있는 상대 하위 디렉터리
- `dirs.project`: 관리되는 배포 소스를 위한 상대 하위 디렉터리
- `dirs.backup`: 백업 아카이브 디렉터리
- `dirs.volume`: 볼륨 데이터를 호스트와 주고받는 디렉터리
- `deploy`: `compman deploy`와 `compman update`의 기본 S3 URI 또는 공개 HTTP 아카이브 URL

관리 경로는 `compman.yml`이 있는 디렉터리를 벗어날 수 없습니다. `--path`는 설정된 `deploy` 값을 한 번의 실행에만 재정의합니다.

배포 소스 크기를 제한하려면 선택적 limit을 설정합니다. 설정하면 소스와 바이트 크기를 provenance로 출력합니다:

```yaml
compman:
  name: my-stack
  deploy: s3://my-bucket/releases/app.tar.gz
  limits:
    max_archive_mb: 50
  compose:
    default:
      file: docker-compose.yml
```

오래 실행되는 Docker/subprocess 작업은 기본 300초 타임아웃을 사용하며, 프로세스별로 `COMPMAN_TIMEOUT=<seconds>`(예: `COMPMAN_TIMEOUT=600`)로 재정의할 수 있습니다. 스트리밍 명령(`service log -f`, `service connect`, `stats -f`)은 의도적으로 타임아웃 없이 실행합니다.

### AWS Secrets Manager 환경 변수

최상위 `secrets` 키로 공유 시크릿 값을 제공합니다. 각 항목은 이름을 `{ arn, key }`에 매핑합니다. 프로파일 `env` 값은 `${secrets:NAME}` 마커로 이 이름을 참조하고, compose 컨텍스트를 만들 때 compman이 시크릿의 JSON `SecretString`을 가져와 `key` 위치의 값으로 치환합니다.

```yaml
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
  secrets:
    DB_URL:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/url
    DB_PASSWORD:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/password
```

- 시크릿은 프로파일 `env` 값에 `${secrets:NAME}` 마커가 있을 때만 주입되며, standalone compose 변수로 전달되지 않습니다. 프로파일 `secrets` 블록은 최상위 블록 위에 병합됩니다(이름이 겹치면 프로파일이 이깁니다).
- `key`는 시크릿 안의 JSON 키 이름입니다(`dtx/db/url` 같은 slash 키를 지원합니다).
- 같은 ARN은 여러 env 변수가 참조해도 명령 실행당 한 번만 가져옵니다.
- 시크릿 누락, region 미확정, 잘못된 시크릿 본문은 명령을 명확한 오류로 실패시킵니다. 표준 AWS 자격 증명/region 환경 변수를 사용하세요. 시크릿이 설정됐는데 자격 증명이나 region이 없으면 `compman doctor`가 경고를 보고합니다.

**프로파일 `env`에서 시크릿 참조:** `secrets`에 `DB_URL`/`DB_PASSWORD` 쌍을 선언하고 `docker-compose.yml`에 그대로 옮기는 대신, `${secrets:NAME}` 마커로 env 값을 구성할 수 있습니다. `NAME`은 `secrets` 블록에 선언된 이름이어야 합니다. 부분 치환을 지원하며, 마커는 시스템 변수 참조(compose가 해석하도록 그대로 둠) 옆에 놓일 수 있습니다:

```yaml
compman:
  name: my-stack
  compose:
    local: docker-compose.local.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}:${secrets:DB_PASSWORD}@db.example.com
        LOG_LEVEL: ${LOG_LEVEL:-info}          # system var, resolved by compose
  secrets:
    DB_USER:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/user
    DB_PASSWORD:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/password
```

선언되지 않은 이름을 참조하는 마커는 명령을 명확한 오류로 실패시킵니다.

**주입된 변수 사용:** 선언만으로는 부족합니다. compman은 치환된 프로파일 `env` 값을 `docker compose` 프로세스 환경에 넘기므로, `docker-compose.yml`은 `${VAR}` 치환으로 참조해야 합니다:

```yaml
# docker-compose.yml
services:
  app:
    image: my-app
    environment:
      - DB_URL=${DB_URL}                  # injected from secrets
      - LOG_LEVEL=${LOG_LEVEL:-info}      # with a default fallback
```

## 명령어

```text
compman init [--scaffold | --s3 URI | --seed]
compman deploy [--path SOURCE_URI] [--sha256 HEX] [--build] [--tag TAG]
compman update [PROFILE] [-c|--config PATH]
compman doctor [--profile PROFILE] [-c|--config PATH] [--json]
compman status [--profile PROFILE] [-c|--config PATH] [--json]
compman ps [PROFILE] [-a|--all] [--json] [-c|--config PATH]
compman stats [PROFILE] [-f|--follow] [--json] [-c|--config PATH]
compman upgrade [--repo URL]
compman version
compman lang [ko|en]
compman completion [powershell|bash|zsh|fish] --install

compman stack up [PROFILE] [-c|--config PATH]
compman stack update [PROFILE] [-c|--config PATH]
compman stack down [--profile PROFILE] [-c|--config PATH] --yes

compman service start [SERVICE...] [--profile PROFILE] [-c|--config PATH]
compman service stop [SERVICE...] [--profile PROFILE] [-c|--config PATH]
compman service restart [SERVICE...] [--profile PROFILE] [-c|--config PATH]
compman service status [--profile PROFILE] [-c|--config PATH]
compman service log [CONTAINER] [-f] [-n 50] [--profile PROFILE] [-c|--config PATH]
compman service connect [CONTAINER] [--profile PROFILE] [-c|--config PATH]

compman volume backup [-z LEVEL] [--no-stop] [--profile PROFILE] [-c|--config PATH]
compman volume restore [TIMESTAMP] [--no-stop] [--replace] [--profile PROFILE] [-c|--config PATH]
compman volume pull [--profile PROFILE] [-c|--config PATH]
compman volume push [--replace] [--profile PROFILE] [-c|--config PATH]

compman image backup [-z LEVEL] [--source-image] [--profile PROFILE] [-c|--config PATH]
compman image restore [TIMESTAMP] [--profile PROFILE] [-c|--config PATH]

compman schedule add [--every N | --daily HH:MM | --weekly DAY HH:MM] [--no-stop] [-z LEVEL] [--profile PROFILE] [--name TEXT] [--scheduler systemd|cron] [-c|--config PATH]
compman schedule list [--json]
compman schedule remove NAME

compman clear [--yes]
```

`compman <command> --help`로 명령의 모든 옵션을 볼 수 있습니다.

### 동작 참고 사항

- `update`: `deploy`가 설정되어 있으면 S3 또는 HTTP 소스를 내려받아 이미지를 빌드하고 스택을 시작합니다. 없으면 로컬 Compose 프로젝트를 `up -d --build`로 갱신합니다.
- `stack down`: 존재하지 않는 스택을 종료해도 오류가 아닙니다. compman은 안내를 출력하고 exit 0으로 끝나므로 스크립트가 멱등하게 호출할 수 있습니다.
- `service log`: 기본으로 마지막 50줄을 표시하고 `-f`로 출력을 스트리밍합니다. Compose 서비스 이름을 받아 `compose ps -q`로 컨테이너를 찾으며, 여러 인스턴스로 스케일된 서비스는 정확한 컨테이너 이름을 요청합니다.
- `ps`: 선택한 compman 프로젝트의 실행 중인 컨테이너를 나열합니다. `-a`로 중단된 컨테이너까지 포함합니다.
- `stats`: 선택한 프로젝트의 실행 중인 컨테이너에 대한 리소스 사용량 스냅샷을 한 번 출력합니다. `-f`로 계속 스트리밍합니다.
- `service connect`: `bash` 연결이 실패하면 `sh`로 폴백합니다.
- `volume backup/restore`: 기본적으로 작업 동안 스택을 내리고 끝난 뒤 되살립니다. 일관성 위험을 이해할 때만 `--no-stop`을 쓰세요.
- `volume restore/push --replace`: 병합하는 대신 대상에 없는 소스 기준으로 대상의 파일을 삭제합니다(바이트 단위 교체). 대상은 검증된 절대 컨테이너 경로여야 하며, 파괴적이므로 신중하게 쓰세요.
- `image backup`: 기본적으로 실행 중인 컨테이너 상태를 commit해 저장합니다. 원본 이미지를 저장하려면 `--source-image`를 쓰세요.
- `volume backup`과 `image backup`: gzip 레벨 기본값은 6입니다. `-z 1`은 더 빠른 백업, `-z 9`는 더 작은 아카이브입니다.
- `clear`: 선택한 런타임에 `image prune -af`를 실행하므로 현재 프로젝트 밖의 미사용 이미지도 삭제할 수 있습니다. `--yes` 확인(또는 대화형 `y` 응답)이 필요합니다.

## 진단 및 상태

```bash
compman doctor
compman doctor --json
compman doctor --config /path/to/compman.yml
compman doctor -c /path/to/compman.yml
compman status
compman status --profile PROFILE
compman status --json
compman status --config /path/to/compman.yml
compman status -c /path/to/compman.yml
```

`doctor`는 설정, Compose 파일, 컨테이너 런타임 가용성과 연결, 관리 디렉터리, AWS 자격 증명을 점검합니다. `status`는 실행 중인 스택의 서비스 상태를 표시합니다. `--json`은 자동화에 적합한 구조화된 JSON을 출력합니다.

`ps`와 `stats`는 의도적으로 프로젝트 범위로 한정됩니다. 런타임 전체 결과가 필요하면 `docker ps`, `docker stats` 또는 Podman equivalent를 직접 사용하세요.

`doctor`의 필수 점검이 실패하면 exit code `1`을 반환합니다. `status`는 대상 스택이 없거나 상태 조회 자체가 실패하면 exit code `1`을 반환합니다. 스택이 존재하고 조회가 성공하면 모든 서비스가 중단/종료 상태여도 exit code `0`을 반환합니다. AWS 환경 변수(`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) 누락은 실패하지 않는 경고이므로, 다른 필수 점검이 모두 통과하면 `doctor`는 exit code `0`을 반환합니다.

백업 파일은 `dirs.backup`에 저장됩니다.

```text
<stack>.volume.<YYYYMMDD_HHMMSS>[_<microseconds>].tar.gz
<stack>.image.<YYYYMMDD_HHMMSS>[_<microseconds>].tar.gz
```

선택적 보존 정책: `limits.max_backups`를 설정하면 스택과 종류별로 최신 N개 아카이브만 유지합니다. 성공한 백업마다 저장소(로컬 파일 또는 S3 객체)에서 오래된 아카이브를 정리하고 매 삭제를 출력합니다. 삭제 실패는 경고할 뿐 백업을 실패시키지 않습니다.

```yaml
compman:
  limits:
    max_backups: 10
```

타임스탬프 없이 복구하면 사용 가능한 백업을 대화형으로 고릅니다. 볼륨 복구와 `volume push`는 대상에 데이터를 병합하며, 대상에만 있는 파일은 삭제하지 않습니다. 이미지 복구는 이미지를 런타임에 로드할 뿐 Compose `image` 태그를 자동으로 바꾸지 않습니다.

### S3 백업 저장소

`dirs.backup`은 로컬 상대 경로 또는 S3 URI를 받습니다. S3 저장소를 쓰면 아카이브는 버킷에 살고, compman은 백업이나 복구가 실행되는 동안에만 로컬에 스테이징하고 업로드가 성공하면 스테이징 사본을 삭제합니다.

```yaml
compman:
  name: my-stack
  dirs:
    backup: s3://my-bucket/backups
  compose:
    default:
      file: docker-compose.yml
```

- 모든 `volume backup`과 `image backup`은 아카이브를 `Content-Type: application/gzip`으로 `<prefix>/<archive-filename>`에 업로드한 뒤, 저장된 객체 크기를 스테이징 파일과 대조합니다.
- 복구는 버킷에서 사용 가능한 타임스탬프를 나열하고 선택한 아카이브를 자동으로 내려받습니다. 수동 sync 단계는 없습니다.
- 업로드 실패는 non-zero로 종료하고 스테이징 아카이브를 남기며 그 경로를 알려줍니다. 성공한 업로드는 스테이징 사본을 제거합니다.
- 저장소는 `AWS_ENDPOINT_URL_S3` / `AWS_ENDPOINT_URL`을 통해 어떤 S3 호환 엔드포인트와도 동작합니다([S3 호환 스토리지](#s3-호환-스토리지) 참고).
- S3 백업 저장소가 설정됐는데 AWS 자격 증명이나 region이 없으면 `compman doctor`가 경고를 보고합니다.

운영자 참고: 중단된 multipart 전송은 과금되는 orphaned part를 버킷에 남길 수 있습니다. 불안정한 네트워크에서는 불완전한 multipart 업로드를 중단하는 버킷 lifecycle 규칙을 추가하세요(7일이 적당합니다).

### 스케줄 백업

`compman schedule add`는 무인 `volume backup` 작업을 플랫폼 native 스케줄러에 등록하므로 셸 루프 없이도 백업이 주기적으로 실행됩니다. S3 백업 저장소가 설정되어 있으면 스케줄 백업이 자동으로 오프사이트에 복제됩니다.

```bash
compman schedule add --daily 04:30 --no-stop      # every day at 04:30 local time
compman schedule add --every 30m                  # every 30 minutes
compman schedule add --weekly sun 03:00 -z 9     # Sundays at 03:00, gzip level 9
compman schedule list [--json]
compman schedule remove daily-04-30               # name shown by `schedule list`
```

캐던스 옵션은 정확히 하나가 필요합니다: `--every Nm|Nh`, `--daily HH:MM`, 또는 `--weekly <day> HH:MM`(요일 이름은 `sun`..`sat`, 대소문자 무관; 모든 시각은 로컬). pass-through 플래그는 `volume backup`을 따릅니다: `--no-stop`, `-z LEVEL`, `--profile`. 작업은 래퍼 스크립트 없이 `[compman, -c <config>, volume backup, ...]`를 직접 실행하고, 출력을 스케줄 레지스트리 옆의 `schedule.log`에 append합니다(`~/.config/compman/schedule.log`, Windows는 `%APPDATA%\compman\schedule.log`). Linux systemd timer에서는 출력이 journald로 갑니다(`journalctl --user -u compman-<name>.service`).

스케줄러 메커니즘은 자동으로 고릅니다: macOS는 launchd, Windows는 schtasks, Linux는 `systemctl --user show-environment`가 성공하면 systemd user timer, 아니면 crontab입니다. Linux 메커니즘은 `--scheduler systemd|cron`으로 강제할 수 있습니다. cron은 모든 간격을 표현할 수 없습니다: `--every` 값은 60분을 나눠떨어지거나 정수 시간이어야 하며, 그렇지 않으면 등록이 실패하고 `--scheduler systemd`를 제안합니다.

`~/.config/compman/schedules.json`(Windows는 `%APPDATA%\compman\schedules.json`) 레지스트리가 source of truth입니다. `schedule list`는 각 플랫폼 아티팩트를 probe하고 drift된 항목에 `[missing]`을 표시합니다. `schedule remove`는 플랫폼 아티팩트가 이미 사라졌어도 레지스트리 항목을 삭제합니다.

이 기능에 의존하기 전에 알아야 할 플랫폼 제약:

- macOS LaunchAgents는 사용자가 로그인해 있는 동안에만 발화합니다. headless 서버는 Linux 메커니즘을 쓰세요.
- Windows 예약 작업은 사용자가 로그온해 있는 동안에만 실행됩니다.
- 스케줄 백업은 non-interactive 실행과 똑같이 동작합니다. Docker Desktop이 필요한데 준비되지 않았으면 작업이 멈추지 않고 간결하게 실패합니다.

## 런타임 선택

자동 감지 순서는 다음과 같습니다.

```text
docker compose → podman compose → podman-compose → docker-compose
```

Podman을 선호하려면 환경 변수를 설정합니다.

```bash
export CONTAINER_RUNTIME=podman
# PowerShell: $env:CONTAINER_RUNTIME="podman"
```

### Windows Docker Desktop 준비 상태

Windows에서 Docker가 선택된 런타임이면 compman은 `compman stack up`, `compman update`, `compman stack update`, `compman deploy --build` 이미지 빌드 전에 Docker Desktop을 확인합니다. 대화형 터미널에서 Docker Desktop이 준비되지 않았으면 다음처럼 묻습니다:

```text
Docker Desktop is not running. Start it now? [Y/n]
```

Enter(또는 `Y`)를 누르면 Docker Desktop을 시작합니다. compman은 준비될 때까지 최대 60초 기다린 뒤 계속합니다. `N`으로 답하면 Docker Desktop을 수동으로 시작하고 재시도하라는 안내와 함께 종료합니다.

non-interactive 실행에서는 compman이 Docker Desktop을 절대 시작하지 않고 간결한 오류로 종료합니다. 이 확인은 Podman, 읽기 전용 명령, backup/restore, stop/down 경로에서는 실행되지 않습니다.

Docker Desktop 준비 실패를 포함한 예상된 운영 실패는 Python traceback 없이 간결한 메시지로 출력됩니다.

## S3 호환 스토리지

표준 AWS SDK 환경 변수를 사용합니다.

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-northeast-2
export AWS_ENDPOINT_URL_S3=http://localhost:4566   # Default Ministack/LocalStack port
```

`AWS_ENDPOINT_URL_S3`가 없으면 `AWS_ENDPOINT_URL`도 사용할 수 있습니다.

## 언어 및 셸 완성

```bash
compman lang ko                    # Set the default language for the current process
compman --lang en --help           # Use English for this invocation only
export COMPMAN_LANG=ko             # Set the default language in the shell environment

compman completion powershell --install
compman completion bash --install
compman completion zsh --install
compman completion fish --install
```

## 개발 및 검증

```bash
uv sync --dev
uv run ruff check compman tests
uv run mypy compman
uv run pytest --cov=compman --cov-report=term-missing
```

CI는 다음을 검증합니다:

- Ubuntu, macOS, Windows × Python 3.12~3.14 테스트
- 100% statement/branch 커버리지
- Ruff와 mypy
- wheel 빌드, 격리 설치, CLI 실행
- Ministack S3 다운로드, Docker 이미지 빌드, Compose 시작/중지 E2E

현재 제약과 개선 백로그는 [BACKLOG.md](BACKLOG.md)를, 개발/테스트/디버깅 교훈은 [SOLUTION.md](SOLUTION.md)를 참고하세요.
