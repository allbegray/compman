# compman — Docker Compose Stack Manager CLI

Docker/Podman Compose 스택의 실행, 백업, 배포를 하나의 CLI로 관리한다.

**프로젝트 홈페이지:** https://allbegray.github.io/compman/

웹 GUI가 없고 방화벽이 대부분을 차단하며 무거운 관리 도구를 설치할 수 없어 Docker 명령어만 남은 환경에서 특히 유용하다. 모든 편리한 선택지가 허용되지 않았다면 compman이 그 빈자리를 메운다.

## 시작하기

### 요구사항

- Python 3.10 이상
- Docker Compose 또는 Podman Compose
- S3 배포 시 접근 가능한 S3 호환 스토리지와 AWS 자격 증명
- HTTP 배포 시 공개 아카이브 URL, 인증이 필요한 URL은 아직 지원하지 않는다

CI는 Ubuntu, macOS, Windows에서 Python 3.10부터 3.13까지 검증한다. Python 지원 전략과 개선 백로그는 [BACKLOG.md](BACKLOG.md)를 참고한다.

`main`에 푸시된 뒤 CI가 성공하면 `pyproject.toml`의 버전을 기준으로 주석 태그를 자동으로 생성한다. 버전을 올릴 때마다 `CHANGELOG.md`에 날짜가 포함된 항목을 함께 기록해야 하며 이미 존재하는 태그는 이동하지 않는다. 배포된 휠은 PyPI에 올라가므로 `uv tool install compman` 또는 `pipx install compman`으로 설치할 수 있다.

### 설치

#### 자동 설치

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

설치가 끝나면 새 터미널을 열고 확인한다.

```bash
compman -v       # --version도 동일
compman -h       # --help도 동일
```

#### uv로 설치

uv가 compman용 Python을 직접 관리하므로 시스템 Python이 3.9처럼 오래되어도 동작한다.

```bash
uv tool install --force --managed-python git+https://github.com/allbegray/compman.git
```

저장소에서 개발 버전을 설치하려면 다음을 실행한다.

```bash
uv tool install .
```

이미 설치된 CLI는 uv가 저장한 소스 정보를 이용해 갱신한다.

```bash
compman upgrade
```

위 명령은 내부적으로 `uv tool upgrade compman --reinstall --managed-python`을 실행한다.

#### 손상된 설치 복구

설치가 손상되어 `compman upgrade`가 동작하지 않으면 상위 Git 소스에서 다시 설치한다. 소스를 특정 버전에 고정하지 않으면 이후 `uv tool upgrade`가 계속 최신 릴리스로 이동한다.

```bash
uv tool uninstall compman
uv tool install --force --managed-python git+https://github.com/allbegray/compman.git
compman --version
```

### 빠른 시작

#### 기존 Compose 프로젝트

```bash
cd my-project
compman init --scaffold
compman stack up
compman service status
compman stack down --yes
```

인자 없이 `compman init`을 실행하면 대화형 메뉴가 나타난다. 세 가지 모드를 제공한다.

```bash
compman init --scaffold                         # compman.yml 생성
compman init --s3 s3://bucket/app.tar.gz --build
compman init --seed -o project -p 18080         # 테스트용 프로젝트 생성
compman init --seed -o project -a               # 테스트용 프로젝트 생성 후 아카이브
```

이미 존재하는 파일을 덮어쓰려면 `--force`를 명시해야 한다.

#### 새 프로젝트 배포, S3와 HTTP 예시

빈 작업 디렉터리에서 실행한다.

```bash
mkdir my-app && cd my-app
compman deploy --path s3://my-bucket/releases/app.tar.gz --build --tag my-app
compman stack up
```

배포가 성공하면 다음과 같은 구조가 생성된다.

```text
my-app/
├── compman.yml
├── docker-compose.yml
└── project/              # S3에서 내려받은 애플리케이션 소스
```

S3 경로는 두 가지 형식을 지원한다.

- Prefix: 경로 아래 객체를 재귀적으로 내려받고 디렉터리 구조를 그대로 유지한다.
- Archive: `.tar.gz`, `.tgz`, `.zip`을 안전하게 풀며 최상위가 단일 디렉터리이면 자동으로 평탄화한다.

공개 HTTP와 HTTPS URL은 아카이브만 지원한다. 쿼리 문자열은 허용되지만 URL 경로는 `.tar.gz`, `.tgz`, `.zip` 중 하나로 끝나야 한다.

```bash
compman deploy --path https://example.com/releases/app.zip --build --tag my-app
```

배포 시 같은 이름의 대상만 교체하고 나머지 사용자 파일은 그대로 둔다. `--build`를 함께 쓰면 교체 전에 임시 소스에서 이미지를 먼저 빌드한다. 빌드가 실패하면 기존 트리와 설정이 그대로 남는다. 소스 교체 단계가 실패하면 이전 트리를 복원한다. 교체 이후 스캐폴드 생성이 실패한 경우에만 새 소스 트리가 남을 수 있다.

#### per-profile 배포, 로컬 소스, 검증과 롤백

프로파일마다 다른 배포 소스를 쓰려면 `deploy`를 맵으로 둔다. 문자열 하나를 쓰던 기존 설정은 그대로 동작하며 문자열은 `default`로 정규화된다. 자세한 선언은 [`examples/compman-config/10-per-profile-deploy.md`](examples/compman-config/10-per-profile-deploy.md)와 [`per-profile-deploy.yml`](examples/compman-config/per-profile-deploy.yml)를 참고한다.

```yaml
compman:
  name: my-stack
  deploy:
    default: s3://my-bucket/releases/app.tar.gz
    dev:
      source: file://./dist/app.tar.gz
    prod:
      source: s3://my-bucket/releases/app.tar.gz
      checksum: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
      strategy: recreate
  compose:
    default:
      file: docker-compose.yml
    dev:
      file: docker-compose.dev.yml
    prod:
      file: docker-compose.prod.yml
```

- per-profile deploy: `dev`는 로컬 빌드 산출물(`file://` 또는 베어 경로 `./dist/app.tar.gz`도 허용), `prod`는 S3에 체크섬을 붙여 검증한다. `checksum`은 `sha256:` 뒤 64자리 16진수만 허용한다. `strategy`는 `recreate`(기본) 또는 `pull-only`이며 `pull-only`는 이미지 빌드와 `pull`을 건너뛴다.
- 로컬 소스 예제: 디렉터리나 아카이브 모두 허용하며 `file://`와 베어 경로를 동일하게 처리한다.

```yaml
# checksum을 포함한 prod 예제
compman:
  name: my-stack
  deploy:
    prod:
      source: s3://my-bucket/releases/app.tar.gz
      checksum: sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
  compose:
    prod:
      file: docker-compose.prod.yml
```

```bash
# 로컬 아카이브를 실제 교체 없이 검증, diff를 출력한다
compman deploy --path ./dist/app.tar.gz --dry-run

# 로컬 디렉터리를 prod 체크섬과 함께 배포
compman deploy --profile prod --build

# pull-only 전략으로 빌드를 건너뛴다
compman deploy --profile prod --strategy pull-only --keep 5

# 이전 배포로 되돌린다, 타임스탬프 없이 실행하면 대화형으로 선택한다
compman rollback 20260820_120000
compman rollback --profile prod
```

배포가 성공하면 `backup/.versions/<YYYYMMDD_HHMMSS>`에 최대 3개(기본값, `--keep 1-10`으로 조절) 버전이 보관된다.

### 설정 파일 compman.yml

모든 설정은 `compman.yml`의 `compman` 키 아래에 둔다.

상황별 예제는 [`examples/compman-config/`](examples/compman-config/)(목록은 [`examples/README.md`](examples/README.md))를 참고한다.

#### 프로파일 기반 Compose 설정

`compose`는 필수이며 프로파일 매핑이어야 한다. Compose 파일이 하나라면 단일 프로파일로 충분하다.

```yaml
compman:
  name: my-stack
  compose:
    default:
      file: docker-compose.yml
```

여러 프로파일을 두면 환경별로 Compose 파일과 환경 변수를 다르게 선택할 수 있다.

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

프로파일의 `file`은 생략할 수 있다. 생략하면 `base`를 사용하고 `base`도 없으면 `docker-compose.yml`을 사용한다. 덕분에 하나의 Compose 파일로 환경 변수만 다르게 운용할 수 있다.

```bash
compman stack up dev
compman service status --profile dev
compman stack down --profile dev --yes
```

기본 프로파일은 인자를 주지 않으면 설정된 프로파일 중 첫 번째가 된다. 이름을 직접 지정하면 유효한 프로파일이어야 하며 알 수 없는 이름은 오류로 끝난다.

#### 배포와 관리 디렉터리

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
- `dirs.project`: 배포 소스를 관리하는 상대 하위 디렉터리
- `dirs.backup`: 백업 아카이브를 저장하는 디렉터리
- `dirs.volume`: 호스트와 볼륨 데이터를 주고받는 디렉터리
- `deploy`: `compman deploy`와 `compman update`가 사용할 기본 S3 URI 또는 공개 HTTP 아카이브 URL

관리 경로는 `compman.yml`이 있는 디렉터리를 벗어날 수 없다. `--path`는 한 번의 호출에만 설정된 `deploy` 값을 덮어쓴다.

배포 소스 크기를 제한하려면 선택 제한을 둔다. 설정하면 출처 정보로 소스와 바이트 크기를 함께 출력한다.

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

오래 걸리는 Docker와 하위 프로세스 동작은 기본 300초 타임아웃을 사용한다. 프로세스별로 `COMPMAN_TIMEOUT=<초>`로 덮어쓸 수 있다. 예를 들면 `COMPMAN_TIMEOUT=600`이다. 잘못된 값은 300으로 되돌아간다.

#### Secrets, AWS Secrets Manager와 ${secrets:NAME}

최상위 `secrets` 키로 공통 비밀값을 제공한다. 각 항목은 이름을 `{ arn, key }`에 매핑한다. 프로파일 `env` 값 안의 `${secrets:NAME}` 마커가 있는 곳에서만 비밀값을 주입한다. compman은 비밀의 JSON `SecretString`을 가져와 `key`에 해당하는 값을 치환해 compose 컨텍스트를 만들 때 적용한다.

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

- 비밀값은 프로파일 `env` 값에 `${secrets:NAME}` 마커가 있을 때만 주입하며 compose에 독립 변수로 넘기지 않는다. 프로파일의 `secrets` 블록은 최상위 설정을 덮어쓴다. 이름이 겹치면 프로파일이 우선한다.
- `key`는 비밀 내부 JSON 키를 가리킨다. `dtx/db/url` 같은 슬래시 키도 지원한다.
- 같은 ARN은 한 번의 명령 호출에서 한 번만 가져온다. 여러 env 변수가 같은 ARN을 참조해도 마찬가지다.
- 비밀이 없거나 리전을 해석할 수 없거나 비밀 본문이 올바르지 않으면 명령이 명확한 오류와 함께 실패한다. 표준 AWS 자격 증명과 리전 환경 변수를 사용한다. 비밀을 설정했는데 자격 증명이나 리전이 없으면 `compman doctor`가 경고를 출력한다.

프로파일 `env`에서 비밀을 참조하는 예시는 다음과 같다. `docker-compose.yml`에 `DB_URL`과 `DB_PASSWORD`를 직접 적는 대신 `${secrets:NAME}` 마커로 env 값을 조합할 수 있다. `NAME`은 `secrets` 블록에 선언된 이름이어야 한다. 부분 치환을 지원하고 시스템 변수 참조 옆에 두어도 된다. 시스템 변수는 그대로 두어 docker compose가 해석하게 한다.

```yaml
compman:
  name: my-stack
  compose:
    local: docker-compose.local.yml
    dev:
      file: docker-compose.dev.yml
      env:
        DATABASE_URL: postgres://${secrets:DB_USER}:${secrets:DB_PASSWORD}@db.example.com
        LOG_LEVEL: ${LOG_LEVEL:-info}          # 시스템 변수, compose가 해석
  secrets:
    DB_USER:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/user
    DB_PASSWORD:
      arn: arn:aws:secretsmanager:ap-northeast-2:123456789012:secret:db
      key: dtx/db/password
```

선언되지 않은 이름을 참조하는 마커는 명확한 오류와 함께 실패한다.

주입된 변수를 실제로 사용하려면 선언만으로 끝나면 안 된다. compman은 치환된 프로파일 `env` 값을 `docker compose` 프로세스 환경으로 넘긴다. 따라서 `docker-compose.yml`에서도 `${VAR}` 치환으로 참조해야 한다.

```yaml
# docker-compose.yml
services:
  app:
    image: my-app
    environment:
      - DB_URL=${DB_URL}                  # secrets에서 주입됨
      - LOG_LEVEL=${LOG_LEVEL:-info}      # 기본값과 함께 사용
```

시스템 환경 변수는 docker compose가 직접 상속하므로 설정에 따로 둘 필요가 없다.

#### .env 파일로 환경 변수 불러오기

프로파일마다 `.env` 파일을 지정해 환경 변수를 Compose 컨텍스트에 주입할 수 있다. `env_file`은 문자열 또는 문자열 리스트를 받으며 `.env`에 적은 값을 일일이 `env:`에 옮겨 적지 않아도 된다.

```yaml
compman:
  name: my-stack
  compose:
    dev:
      file: docker-compose.dev.yml
      env_file: .env
      env:
        LOG_LEVEL: debug
    prod:
      file: docker-compose.prod.yml
      env_file: [".env", "prod.env"]  # 뒤 파일이 덮어씀
      env:
        DATABASE_URL: prod.db.example.com  # env_file보다 우선
```

경로는 `compman.yml`이 있는 디렉터리 기준이며 절대 경로는 그대로 사용한다. 예를 들어 `env_file: /etc/compman/prod.env`처럼 쓸 수 있다. 파일이 없으면 `ConfigError`로 실패한다.

병합 순서는 다음 3단계로 고정된다.

1. `env_file`에 나열된 파일들을 순서대로 읽어 병합한다, 뒤 파일이 앞 파일을 덮어쓴다
2. 프로파일의 `env:`에 직접 적은 값이 그 결과를 덮어쓴다
3. 최종 값에 포함된 `${secrets:NAME}` 마커를 치환한다, Secrets와 함께 쓰면 `.env` 값 안에서도 비밀값을 참조할 수 있다

```yaml
# prod.env
DATABASE_URL=prod.db.example.com
LOG_LEVEL=info

# compman.yml에서 Secrets와 함께 사용
compman:
  compose:
    prod:
      env_file: prod.env
      env:
        DATABASE_URL: ${secrets:DB_URL}  # .env 값을 Secrets 결과로 덮어씀
```

파싱 규칙은 다음과 같다.

- 빈 줄과 `#`으로 시작하는 주석은 무시한다
- `export` 접두사는 자동으로 제거한다, `export DATABASE_URL=...` 형태를 그대로 쓸 수 있다
- 따옴표로 감싼 값은 따옴표를 벗겨 저장한다, `"hello world"`와 `'hello world'` 모두 `hello world`로 해석된다
- `KEY=VALUE` 형태가 아니면 해당 줄은 무시한다

### 언어와 셸 자동 완성

```bash
compman lang ko                    # 현재 프로세스의 기본 언어 설정
compman --lang en --help           # 이번 호출만 영어로 표시
export COMPMAN_LANG=ko             # 셸 환경에서 기본 언어 설정

compman completion powershell --install
compman completion bash --install
compman completion zsh --install
compman completion fish --install
```

도움말과 옵션, 사용자 메시지는 모두 `t()` 번역 함수를 거친다. 기본 언어는 영어이며 한국어는 `--lang ko` 또는 `COMPMAN_LANG=ko`로 활성화한다.

### 개발과 검증

```bash
uv sync --dev
uv run ruff check compman tests
uv run mypy compman
uv run pytest --cov=compman --cov-report=term-missing
```

CI가 검증하는 항목은 다음과 같다.

- Ubuntu, macOS, Windows 곱하기 Python 3.10부터 3.13까지 테스트
- 100% 문장과 분기 커버리지
- Ruff와 mypy
- 휠 빌드, 격리 설치, CLI 실행
- Ministack S3 내려받기, Docker 이미지 빌드, Compose 시작과 종료 E2E

현재 제약과 개선 백로그는 [BACKLOG.md](BACKLOG.md)를 참고한다. 개발과 테스트, 디버깅에서 얻은 교훈은 [SOLUTION.md](SOLUTION.md)에 모여 있다. 테스트 프로젝트 사용법은 [`test/`](test/) 아래 각 README를 참고한다.

PowerShell에서 출력이 깨지면 세션 시작 시 인코딩을 고정한다.

```powershell
chcp 65001
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING="utf-8"
```

## 주요 기능

- Docker Compose와 Podman Compose 런타임을 자동으로 탐지한다. `CONTAINER_RUNTIME`으로 선호 런타임을 강제할 수도 있다
- 프로파일 기반 `compose` 설정으로 프로파일마다 Compose 파일과 환경 변수, 비밀값을 다르게 주입한다
- 프로파일별 `env_file`로 `.env` 파일을 불러와 환경 변수를 주입하고 `env:`에 직접 적은 값이 덮어쓴다
- `ps`와 `stats`로 현재 프로젝트의 컨테이너만 조회하고 모니터링한다. 전체 런타임 조회가 필요하면 `docker ps`와 `docker stats`를 직접 쓰면 된다
- S3 prefix와 아카이브, 공개 HTTP와 HTTPS `.tar.gz`, `.tgz`, `.zip` 아카이브에서 배포한다. 아카이브는 절대 경로와 경로 이탈, 링크를 거부하고 최상위 단일 디렉터리는 자동으로 평탄화한다
- 빈 디렉터리에 배포하면 `compman.yml`과 `docker-compose.yml`을 자동으로 생성한다
- 볼륨과 컨테이너 이미지의 타임스탬프 백업을 만들고 복원한다. gzip 레벨과 `--no-stop`, `--replace` 같은 세부 옵션을 지원한다
- 한국어와 영어 도움말을 제공하고 셸 자동 완성을 지원한다
- Windows, Linux, macOS에서 동작한다

### 전체 명령어

```text
compman init [--scaffold | --s3 URI | --seed]
compman deploy [--path SOURCE_URI] [--build] [--tag TAG]
compman update [PROFILE]
compman doctor [--profile PROFILE] [-c|--config PATH] [--json]
compman status [--profile PROFILE] [-c|--config PATH] [--json]
compman ps [PROFILE] [-a|--all] [-c|--config PATH]
compman stats [PROFILE] [-f|--follow] [-c|--config PATH]
compman upgrade
compman version
compman lang [ko|en]
compman completion [powershell|bash|zsh|fish] --install

compman stack up [PROFILE]
compman stack update [PROFILE]
compman stack down [--profile PROFILE] --yes

compman service start [SERVICE...] [--profile PROFILE]
compman service stop [SERVICE...] [--profile PROFILE]
compman service restart [SERVICE...] [--profile PROFILE]
compman service status [--profile PROFILE]
compman service log [CONTAINER] [-f] [-n 50] [--profile PROFILE]
compman service connect [CONTAINER] [--profile PROFILE]

compman volume backup [-z LEVEL] [--no-stop] [--profile PROFILE]
compman volume restore [TIMESTAMP] [--no-stop] [--replace] [--profile PROFILE]
compman volume pull [--profile PROFILE]
compman volume push [--replace] [--profile PROFILE]

compman image backup [-z LEVEL] [--source-image] [--profile PROFILE]
compman image restore [TIMESTAMP] [--profile PROFILE]

compman clear [--yes]
```

각 명령의 모든 옵션은 `compman <command> --help`로 확인한다. 루트 버전 플래그는 `-v`와 `--version`이며 도움말 플래그는 루트와 명령 그룹 모두에서 `-h`와 `--help`를 지원한다.

### 동작 특성

- `update`: `deploy`가 설정되어 있으면 S3 또는 HTTP 소스를 내려받고 이미지를 빌드한 뒤 스택을 시작한다. 설정이 없으면 `up -d --build`로 로컬 Compose 프로젝트를 갱신한다.
- `service log`: 기본으로 마지막 50줄을 보여주며 `docker logs -n 50`에 해당한다. `-f`로 스트리밍하고 `-n`과 `--tail N`으로 줄 수를 조절한다. Compose 서비스 이름을 받아 `compose ps -q`로 컨테이너를 찾는다. 스케일된 서비스처럼 인스턴스가 여러 개이면 정확한 컨테이너 이름을 지정하라는 안내를 출력한다.
- `ps`: 선택된 compman 프로젝트 안에서 실행 중인 컨테이너만 나열한다. `-a`로 멈춘 컨테이너까지 포함한다.
- `stats`: 선택된 프로젝트의 실행 중인 컨테이너에 대해 자원 사용량 스냅샷을 한 번 출력한다. `-f`로 계속 스트리밍한다.
- `service connect`: `docker exec -it`로 접속하며 bash가 실패하면 sh로 되돌아간다.
- `volume backup`과 `restore`: 기본으로 작업 중 스택을 내렸다가 다시 올린다. 일관성 위험을 이해한 경우에만 `--no-stop`으로 생략한다.
- `volume restore`와 `push`의 `--replace`: 병합 대신 대상에만 있는 파일을 삭제한 뒤 바이트 단위로 덮어쓴다. 컨테이너 쪽 대상 경로는 절대 경로이며 루트여서는 안 된다. 파괴적인 동작이므로 의도를 명확히 하고 사용한다.
- `image backup`: 기본으로 실행 중인 컨테이너 상태를 커밋해 저장한다. `--source-image`로 원본 이미지를 저장할 수 있다.
- `volume backup`과 `image backup`: gzip 레벨 기본값은 6이다. 더 빠른 백업은 `-z 1`, 더 작은 아카이브는 `-z 9`를 사용한다.
- `clear`: 선택된 런타임에 대해 `image prune -af`를 실행한다. 현재 프로젝트 바깥의 미사용 이미지도 삭제할 수 있으므로 `--yes` 확인이 필요하다. 대화형에서는 `y`로 답해도 된다.
- `stack down`: `--yes` 확인을 요구하며 `typer.confirm`으로 묻는다.
- `deploy` 소스는 `compman.yml`의 `deploy` 하나 또는 `--path`에서 온다. 프로파일별로 따로 두지 않는다. S3는 boto3로 처리하며 AWS CLI가 필요 없고 `AWS_ENDPOINT_URL_S3`나 `AWS_ENDPOINT_URL`로 클라이언트를 리다이렉트한다. 예를 들어 `http://localhost:4566`의 Ministack이 그렇다. 자격 증명은 표준 AWS 환경 변수를 쓴다.
- 가져온 트리는 관리되는 `dirs.project` 디렉터리 내용을 교체하며 `.git`과 `.gitkeep`은 유지한다. 루트의 `compman.yml`과 `docker-compose.yml`은 별도로 생성하거나 갱신한다.
- `--build`가 포함된 배포는 관리 트리 교체까지 트랜잭션처럼 동작한다. 임시 소스에서 먼저 빌드하므로 빌드가 실패하면 기존 트리와 설정은 그대로 남는다. 교체 자체는 실패 시 롤백되며 교체 뒤 스캐폴드 생성이 실패했을 때만 새 소스 트리가 남을 수 있다.
- `update`는 이미지를 다시 빌드하고 컨테이너를 강제 재생성한다. 무중단 롤링 배포가 아니다.
- Docker Desktop 준비 실패를 포함한 예상 가능한 운영 실패는 파이썬 트레이스백 없이 간결한 오류로만 보여준다.

### 진단과 상태

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

`doctor`는 설정과 Compose 파일, 컨테이너 런타임 가용성과 연결 상태, 관리 디렉터리, AWS 자격 증명을 점검한다. `status`는 실행 중인 스택의 서비스 상태를 보여준다. `--json`은 자동화에 적합한 구조화 JSON을 스키마 버전 `1`로 출력한다.

`ps`와 `stats`는 의도적으로 프로젝트 범위로 제한된다. 런타임 전체 결과가 필요하면 `docker ps`와 `docker stats` 또는 Podman 동등 명령을 직접 사용한다.

필수 `doctor` 검사가 실패하면 종료 코드 `1`로 끝난다. `status`는 대상 스택이 없거나 상태 조회 자체가 실패하면 종료 코드 `1`을 반환한다. 스택이 존재하고 조회에 성공하면 모든 서비스가 멈춘 상태라도 종료 코드 `0`을 반환한다. 필수 AWS 환경 변수(`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) 누락은 실패가 아닌 경고로 처리한다. 다른 필수 검사가 모두 통과하면 `doctor`는 종료 코드 `0`을 반환한다. 비밀값 관련 선행 조건이 부족해도 같은 방식으로 경고를 낸다.

### 백업과 복원

백업 파일은 `dirs.backup`에 저장된다.

```text
<스택이름>.volume.<YYYYMMDD_HHMMSS>[_<마이크로초>].tar.gz
<스택이름>.image.<YYYYMMDD_HHMMSS>[_<마이크로초>].tar.gz
```

타임스탬프 없이 복원하면 대화형으로 백업을 선택한다. 볼륨 복원과 `volume push`는 대상에 병합하며 대상에만 있는 파일을 삭제하지 않는다. `--replace`를 쓰면 삭제 후 덮어쓴다. 이미지 복원은 런타임에 이미지를 로드하지만 Compose `image` 태그를 자동으로 바꾸지는 않는다.

### 런타임 선택

자동 탐지 순서는 다음과 같다.

```text
docker compose → podman compose → podman-compose → docker-compose
```

Podman을 우선하려면 환경 변수를 설정한다.

```bash
export CONTAINER_RUNTIME=podman
# PowerShell: $env:CONTAINER_RUNTIME="podman"
```

Docker를 먼저 찾고 다음으로 Podman을 찾는다.

#### Windows Docker Desktop 준비 상태

Windows에서 Docker를 선택한 경우 compman은 `compman stack up`과 `compman update`, `compman stack update`, `compman deploy --build`의 이미지 빌드 전에 Docker Desktop 준비 상태를 확인한다. 대화형 터미널에서 Docker Desktop을 사용할 수 없으면 다음과 같이 묻는다.

```text
Docker Desktop is not running. Start it now? [Y/n]
```

Enter를 누르거나 `Y`로 답하면 compman이 Docker Desktop을 시작하고 최대 60초간 기다린다. `N`으로 답하면 수동으로 시작하라는 안내와 함께 종료한다.

비대화형 실행에서는 compman이 Docker Desktop을 자동으로 시작하지 않고 간결한 오류와 함께 종료한다. 이 검사는 Podman이나 읽기 전용 명령, 백업과 복원, stop과 down 경로에서는 동작하지 않는다.

### S3 호환 스토리지

표준 AWS SDK 환경 변수를 사용한다.

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=ap-northeast-2
export AWS_ENDPOINT_URL_S3=http://localhost:4566   # Ministack과 LocalStack 기본 포트
```

`AWS_ENDPOINT_URL_S3`가 없으면 `AWS_ENDPOINT_URL`도 사용할 수 있다.

S3 배포는 boto3로 처리하며 AWS CLI가 필요 없다. 자격 증명은 표준 AWS 환경 변수만 쓴다. 배포는 S3 prefix와 `.tar.gz`, `.tgz`, `.zip` 아카이브, 같은 확장자를 가진 공개 HTTP와 HTTPS 아카이브를 받는다. HTTP는 표준 TLS와 리다이렉트 동작을 따르고 30초 타임아웃을 쓰며 인증 옵션은 없다.
