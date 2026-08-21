# compman - Docker Compose Stack Manager CLI

Docker Compose 스택의 실행, 서비스 운영, 볼륨/이미지 백업과 S3/HTTP 배포를 하나의 CLI로 다루는 도구이다.

# 프로젝트 요약

compman은 Docker와 Podman Compose 스택을 프로파일 기반으로 관리하는 CLI이다. `compman.yml` 한 파일로 Compose 파일 선택, 환경 변수와 Secrets Manager 비밀값을 프로파일별로 주입하고, S3 프리픽스나 공개 HTTP 아카이브로부터 배포와 백업 복구를 수행한다. 현재 버전은 1.5.0이며 Python 3.10 이상과 `uv` 기반으로 동작한다.

## 빌드/테스트 방법

### 빠른 시작

```bash
uv tool install .      # CLI 설치
compman --help         # 동작 확인
cd my-project
compman init --scaffold
compman stack up
```

`compman init`은 대화형 3종 메뉴를 제공한다. 1. compman.yml 생성, 2. S3 URL 배포, 3. 테스트용 시드 프로젝트 생성. 직접 플래그는 `--scaffold`, `--s3 <url>`, `--seed`로 동일 기능을 수행한다.

### 검증 명령

```bash
uv sync --dev
uv run ruff check compman tests
uv run mypy compman
uv run pytest --cov=compman --cov-report=term-missing
```

커버리지는 100% 문장과 분기 커버리지를 기준으로 하며 `fail_under = 100`으로 강제된다. 새로 생긴 분기는 반드시 테스트를 추가한다.

릴리스 전에는 휠을 빌드한 뒤 격리된 `uv tool` 디렉터리에 설치하고 생성된 `compman` 바이너리 자체로 스모크 테스트를 수행한다. `--version`, 영문과 한글 `--help`, `init`, `doctor`, `status`를 확인하고 저장된 설치 소스가 지원하면 `upgrade`도 테스트한다. 패키지 버전을 올릴 때마다 루트 `CHANGELOG.md`에 사용자 관점 변경점을 최신 버전이 맨 위에 오도록 기록한다. `main`으로 푸시된 뒤 CI가 성공하면 `.github/workflows/release-tag.yml`이 `v<project.version>` 형태의 주석 태그를 생성한다. 이미 존재하는 태그는 이동하지 않으며 버전과 태그가 충돌하면 워크플로가 실패한다.

### PowerShell 실행

PowerShell에서는 UTF-8을 강제로 사용한다. 출력이 깨지면 세션 시작 시 인코딩을 고정한다.

```powershell
chcp 65001
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING="utf-8"
```

## 에이전트 행동 지침

작업 시작 시 이 문서를 가장 먼저 읽고, 변경이 생기면 해당 섹션과 실행 기록을 즉시 갱신한다. `git push` 전에는 필수 문서 6종을 반드시 최신화한 뒤 푸시한다. 변경점은 `CHANGELOG.md`에 새 버전으로, 맥락과 결정은 `AGENTS.md` 실행 기록에 날짜별로 추가한다.

### 핵심 규칙

* **출력과 메시지:** 표준 라이브러리 `logging`을 쓰지 않는다. 모든 출력은 `typer.echo(..., err=True)`와 `t()` 번역 함수를 거친다. 오류는 예외로만 전달한다.
* **예외 계층:** `errors.py`에 정의된 `CommandError(message, code=1)`, `ConfigError`, `RuntimeError`, `ValueError`(소스 URL 검증)를 사용한다. 예외를 다시 감쌀 때는 `raise X from exc`로 체인을 유지한다. 예외 메시지는 영문을 유지하고 번역은 CLI 표현 계층에서만 수행한다.
* **도메인 모델:** `Config`, `Profile`, `SecretRef`, `ContainerRuntime` 등은 딕셔너리 대신 데이터클래스로 다룬다. 값 객체는 `@dataclass(frozen=True)`로 만든다. 딕셔너리는 YAML 원문을 읽는 운반 단계에만 쓰고 파싱 후 검증해 `ConfigError`를 발생시킨 뒤 객체를 생성한다.
* **국제화:** 모든 도움말, 옵션, 사용자 메시지는 `t("cmd.*" | "opt.*" | "msg.*" | "err.*")`로 참조한다. 기본 언어는 영어이며 한국어는 `--lang ko`나 `COMPMAN_LANG=ko`로 활성화한다. 한글 텍스트는 `i18n.py`의 `TRANSLATIONS`와 관련 테스트에만 둔다.
* **타입과 도구:** 파일 상단에 `from __future__ import annotations`를 두고 PEP 604 `str | None`과 내장 제네릭을 사용한다. `cli.py`의 `typing.Optional`만 예외로 허용한다. mypy는 `--strict`가 아니며 `check_untyped_defs`, `warn_unused_ignores`를 쓴다. Ruff는 `select E,F,I`, `ignore E501`, 줄 길이 120이다.
* **테스트:** 테스트 이름은 `test_<단위>_<동작>` 형태를 따른다. 픽스처는 `tests/conftest.py`의 `runner`, `dummy_runtime`, `temp_dir`만 쓴다. `unittest.mock`의 `patch`, `patch.object`, `patch.dict`와 `monkeypatch`를 주로 쓰고 `pytest-mock`은 쓰지 않는다. `dummy_runtime.compose_runs[*]["args"]`로 호출을 검증하고 `pytest.raises(..., match=...)`로 오류를 확인한다. 분기 커버리지는 `@pytest.mark.parametrize`로 채운다.

### 금지 사항

* `compose`는 반드시 프로파일 매핑이어야 하며 리스트나 문자열 형태는 금지하고 `ConfigError`로 실패한다.
* 관리 경로는 `compman.yml`이 있는 디렉터리를 벗어날 수 없고 삭제성 관리 디렉터리는 설정 루트와 같아서는 안 된다.
* `type: ignore`, `# pragma: no cover`, `TODO`/`FIXME`/`HACK` 마커를 추가하지 않는다. 기준선은 깨끗하며 `deploy.py`의 `noqa: F401` 재내보내기만 예외이다.
* 비밀값은 독립 Compose 변수로 직접 넘기지 않는다. `${secrets:NAME}` 마커를 통해서만 주입한다.
* `scratch/`에는 프로덕션 코드를 두지 않으며 `test/`는 예제와 E2E 가이드용으로 pytest 대상이 아니다.
* 루트에는 필수 문서 6종 `AGENTS.md`, `BACKLOG.md`, `CHANGELOG.md`, `README.md`, `SECURITY.md`, `SOLUTION.md`만 둔다. 그 외 Markdown은 예외 없이 `docs/` 아래로 둔다. 6종 중 하나라도 없으면 작업 전에 코드베이스를 분석해 즉시 생성한다.
* `env_file` 절대 경로는 운영 비밀을 `/etc/compman`에 분리하는 사용 사례를 위해 예외적으로 허용하며 경로 격리 검사를 적용하지 않는다.

### 문서와 그래프 운영

* 모든 문서와 커밋 메시지는 한국어를 원칙으로 하며 코드와 기술 용어는 영문을 그대로 쓴다. 커밋 메시지는 conventional commits를 따른다: `<type>(<scope>): <subject>` (예: `feat(deploy): ...`), 템플릿은 `.gitmessage`와 `git config commit.template .gitmessage`로 관리한다.
* 코드베이스를 탐색할 때는 `graphify-out/`이 있으면 그래프를 먼저 조회한다. 질문은 `graphify query "<질문>"`으로 탐색하고 코드 수정 뒤에는 `graphify --update`로 그래프를 동기화한다. 두 명령 모두 skill이나 에이전트를 통하지 않고 CLI를 직접 실행해 빠르게 처리한다. 그래프가 없으면 `uv tool install --from graphifyy graphifyy` 또는 `pip install graphifyy`로 설치한 뒤 `graphify` 초기 빌드를 수행하면 `graphify-out/`에 `graph.json`, `GRAPH_REPORT.md`, `graph.html`이 생성된다.
* `BACKLOG.md`는 `[H1]`, `[M1]`, `[L1]` 라벨과 `- [ ]` 체크박스로 관리하고 완료된 항목은 `[x]`로 표시한 뒤 삭제한다. 완료 항목을 파일에 남겨두지 않는다.
* `CHANGELOG.md`는 `## [x.y.z] - YYYY-MM-DD` 형식으로 최신 버전이 맨 위에 오도록 작성하고 `### 추가`, `### 변경`, `### 수정`, `### 제거` 중 해당 항목만 둔다.
* `SECURITY.md`는 인증과 인가, 비밀 관리, 취약점 보고, 코드 작성 시 보안 규칙을 다룬다. 실제 자격 증명은 하드코딩하지 않고 자리표시자를 쓴다.
* `SOLUTION.md`는 `## [주제]` 아래 `### 증상`, `### 원인`, `### 해결`, `### 재발 방지` 형식으로 문제 해결 지식을 모은다. 다른 문서에 흩어진 문제 해결 내용은 여기로 통합한다.
* 패키지를 추가하거나 아키텍처를 바꾸거나 버그 수정 방식을 알게 되면 실행 기록에 즉시 남긴다.

## 서브시스템 구조

### 디렉터리와 파일

```
compman/               # Python 패키지
  cli.py               # typer 진입점 compman.cli:app, 루트와 4개 그룹 전체를 정의
  config.py            # compman.yml 로더, Config 데이터클래스
  docker.py            # ContainerRuntime 추상화, compose 파일 해석, Docker Desktop 준비 상태
  deploy.py            # 소스 분기, 관리 트리 교체, 선택적 이미지 빌드
  diagnostics.py       # doctor/status 리포트 수집, 스키마 v1
  archive.py           # 경로 안전한 tar/zip 해제
  archive_source.py    # 아카이브 인식과 해제 공통 로직
  http_source.py       # 공개 HTTP/HTTPS 아카이브 다운로드
  s3_source.py         # S3 프리픽스/아카이브 다운로드
  env_source.py        # AWS Secrets Manager 해석과 ${secrets:NAME} 치환
  scaffold.py          # 배포 시 compman/compose 생성
  errors.py            # CommandError, ConfigError 예외 계층
  i18n.py              # en/ko TRANSLATIONS 사전과 t(), ContextVar/COMPMAN_LANG으로 언어 관리
  __main__.py          # python -m compman 심
  ops/                 # 도메인별 비즈니스 로직
    stack.py, service.py, container.py, volume.py, image.py, seed.py
    common.py          # 공통: prompt_select, select_backup_timestamp, stack_paused, ensure_runtime_ready
tests/                 # pytest 단위/회귀 스위트, 모듈과 1대1 대응, 100% 분기 커버리지
test/                  # 실행 가능한 예제와 E2E 가이드, pytest 대상 아님
examples/compman-config/  # 상황별 compman.yml 예제
docs/site/             # 의존성 없는 GitHub Pages 홈페이지
docs/superpowers/      # 설계 명세와 계획, 구현 근거
docker-init/           # Ministack S3 시드 번들, 통합과 E2E용
scratch/               # 일회성 실험 프로젝트, 프로덕션 코드 금지
.github/workflows/     # ci.yml, release-tag.yml, pages.yml
SOLUTION.md            # 개발과 테스트, 디버깅 교훈, 런타임/CLI/테스트를 건드리기 전에 읽을 것
```

`compman/ops/AGENTS.md`는 하위 모듈 전용 문서이므로 이 파일에서는 다루지 않는다.

### 어디를 볼 것인가

| 작업 | 위치 |
|------|------|
| 명령 트리, 새 CLI 명령 추가 | `compman/cli.py`, 루트와 4개 그룹이 모두 여기에 정의됨 |
| 명령의 비즈니스 로직 | `compman/ops/<domain>.py` |
| `compman.yml` 파싱과 검증 | `compman/config.py` |
| 런타임 탐지와 docker/podman 호출 | `compman/docker.py` |
| `doctor`/`status` JSON 스키마 v1 | `compman/diagnostics.py` |
| `${secrets:NAME}` 해석 | `compman/env_source.py` |
| 배포 소스 S3/HTTP/아카이브 | `compman/deploy.py`와 `{s3,http,archive,archive_source}_source.py` |
| 사용자 노출 문자열과 언어 | `compman/i18n.py`, `t()`와 `TRANSLATIONS` |
| 예외 타입 | `compman/errors.py` |
| 대화형 선택과 백업 타임스탬프 | `compman/ops/common.py` |

### 코드 맵

| 심볼 | 위치 | 참조 수 | 역할 |
|------|------|---------|------|
| `ContainerRuntime` | `docker.py:18` | 48 | 런타임 추상화, 모든 명령 경로에서 사용 |
| `load_config` | `cli.py:32` | 32 | 설정 부트스트랩 |
| `deploy()` | `deploy.py:31` | 18 | 배포와 업데이트 핵심 |
| `detect_runtime` | `cli.py:38` | 14 | 런타임 선택 |
| `ensure_runtime_ready` | `ops/common.py:14` | 7 | Docker Desktop 게이트 |
| `stack_paused` | `ops/common.py:146` | 5 | 백업 일관성을 위한 stop/start 래퍼 |
| `generate_seed` | `ops/seed.py:13` | 5 | `init --seed` |
| `t()` | `i18n.py:767` | 전역 | 번역 조회 |

### 설정 파일 compman.yml

프로파일 기반만 지원하며 단순 리스트 모드는 없다.

```yaml
compose:
  default:
    file: docker-compose.yml
  dev:
    file: docker-compose.dev.yml
    env:
      DATABASE_URL: dev.db.example.com
```

* `compose`는 필수이며 프로파일 매핑이어야 한다. 빠뜨리거나 리스트나 문자열로 쓰면 `ConfigError`가 발생한다. 1.4.0 이전 설정과는 호환되지 않는 변경이다.
* 선택 키 `folder`가 있으면 Compose 파일은 해당 상대 하위 디렉터리에 둔다.
* `folder`와 `dirs.*`는 설정 파일이 있는 디렉터리 기준으로 해석한다. 관리되는 백업과 볼륨, 프로젝트 경로는 설정 디렉터리를 벗어날 수 없으며 파괴적 관리 디렉터리는 설정 루트와 같아서는 안 된다.
* 선택 키 `base`가 있으면 프로파일 Compose 파일 앞에 `-f`로 먼저 붙는다.
* 프로파일의 `file`은 생략할 수 있다. 생략하면 `base`를 쓰고 `base`도 없으면 `docker-compose.yml`로 대체한다. 모든 프로파일이 하나의 Compose 파일을 공유하면서 환경 변수만 다르게 쓸 때 유용하다.
* `env_file`은 선택 키로 문자열(`.env`) 또는 문자열 리스트(`[".env", "prod.env"]`)를 받는다. 경로는 `compman.yml`이 있는 디렉터리 기준이며 절대 경로는 그대로 사용한다. 파일이 없으면 `ConfigError`로 실패한다. 여러 파일을 지정하면 뒤 파일이 앞 파일을 덮고, `env:`에 직접 적은 값이 최종으로 덮는다. 빈 줄과 `#` 주석, `export` 접두사, 따옴표로 감싼 값은 자동으로 처리되며 값 안의 `${secrets:NAME}`도 치환된다.
* 최상위 `secrets`는 마커 이름을 `{ arn, key }`로 매핑한다. 비밀값은 프로파일 `env` 값 안의 `${secrets:NAME}` 마커를 통해서만 주입하며 Compose에 독립 변수로 넘기지 않는다. 프로파일의 `secrets` 블록은 최상위 설정을 덮어쓰며 이름이 겹치면 프로파일이 이긴다. 각 ARN은 명령 한 번 호출당 한 번만 가져오고 Compose 컨텍스트를 만들 때 지연 로딩한다. 부분 치환을 지원하며 선언되지 않은 마커 이름은 실패한다. 시스템 환경 변수는 docker compose가 직접 상속하므로 설정에 따로 둘 필요가 없다.
* 선택 최상위 `limits: { max_archive_mb: N }`은 가져온 배포 소스 크기를 제한한다. 추출된 트리 기준으로 검사하고 한도를 넘으면 파일 시스템을 바꾸기 전에 배포를 중단한다. 설정되어 있으면 배포된 소스와 바이트 크기를 출처 정보로 함께 출력한다.
* 오래 걸리는 Docker와 하위 프로세스 동작은 기본 300초 타임아웃을 쓰며 프로세스별로 `COMPMAN_TIMEOUT=<초>`로 덮어쓸 수 있다. 잘못된 값은 300으로 되돌아간다.

### 런타임

* Docker를 먼저 찾고 다음으로 Podman을 찾는다. `CONTAINER_RUNTIME=podman`으로 강제할 수 있다.
* 탐지 순서는 `docker compose`, `podman compose`, `podman-compose`, `docker-compose` 순이다.
* Windows에서 Docker를 쓸 때 `stack up`, `update`, 배포 이미지 빌드는 Docker Desktop 준비 상태를 확인한다. 대화형 터미널에서 Desktop을 쓸 수 없으면 `Docker Desktop is not running. Start it now? [Y/n]`을 물으며 Enter를 누르면 기본값으로 수락해 compman이 Desktop을 시작하고 최대 60초간 기다린다. `No`를 고르면 수동으로 시작하라는 안내와 함께 종료한다. 비대화형 명령은 Desktop을 자동으로 시작하지 않는다. Podman, 읽기 전용 명령, 백업과 복원, stop과 down 경로는 이 검사를 쓰지 않는다.

### CLI 동작 특성

* `doctor`는 설정, Compose 파일, 컨테이너 런타임, 배포 선행 조건을 점검한다. `--json`은 스키마 버전 `1`을 출력하고 필수 검사가 실패하면 종료 코드 1로 끝난다. 선택인 AWS 환경 변수 누락은 경고로 처리하며 비밀값 선행 조건 미비도 경고를 낸다.
* 최상위 `status`는 Docker와 Podman에 걸쳐 정규화된 스택과 서비스 상태를 보여준다. `--json`은 스키마 버전 `1`을 쓰고 스택이 없거나 런타임 조회가 실패하면 종료 코드 1로 끝난다. 이미 존재하지만 멈춘 스택은 성공으로 처리한다.
* 최상위 `ps`는 선택된 compman 프로젝트 안의 컨테이너만 보여준다. `-a`와 `--all`로 멈춘 컨테이너까지 포함한다.
* 최상위 `stats`는 선택된 프로젝트의 실행 중인 컨테이너에 대해 자원 스냅샷을 한 번 출력한다. `-f`와 `--follow`로 계속 스트리밍한다.
* `stack down`은 `--yes` 확인을 요구하며 `typer.confirm`으로 묻는다.
* 기본 프로파일은 인자 없이 호출하면 설정된 프로파일 중 첫 번째가 된다. 이름을 직접 지정하면 유효한 프로파일이어야 하며 알 수 없는 이름은 실패한다.
* `image backup`은 기본으로 실행 중인 컨테이너 상태를 커밋해 저장한다. `--source-image`를 쓰면 원본 이미지를 저장한다.
* `volume backup/restore`는 선택 플래그 `--no-stop`으로 스택 중단을 건너뛸 수 있다.
* `volume restore/push`는 선택 플래그 `--replace`로 대상에만 있는 파일을 삭제한 뒤 복사해 병합 대신 바이트 단위로 덮어쓴다. 컨테이너 쪽 대상 경로는 절대 경로이며 루트가 아니어야 한다.
* `volume backup`과 `image backup`은 `-z`와 `--level`로 1부터 9까지 gzip 압축 레벨을 받으며 기본값은 6이다.
* `service log`는 기본으로 마지막 50줄을 보여주며 `docker logs -n 50`에 해당한다. `-f`와 `--follow`로 스트리밍하고 `-n`과 `--tail N`으로 줄 수를 조절한다.
* `service connect`는 `docker exec -it`를 실행하며 bash가 실패하면 sh로 되돌아간다.
* `service log`와 `connect`는 Compose 서비스 이름을 받으며 실행 컨테이너는 `compose ps -q <service>`로 찾는다. 인스턴스가 없으면 실행 중인 컨테이너가 없다는 오류를 내고 여러 인스턴스가 있으면 정확한 컨테이너 이름을 지정하라는 안내를 낸다.
* `deploy` 소스는 `compman.yml`의 `deploy`, 단일 값이며 프로파일별 설정이 아니다, 또는 `--path`에서 온다. S3는 boto3로 처리하며 AWS CLI가 필요 없고 `AWS_ENDPOINT_URL_S3`나 `AWS_ENDPOINT_URL`로 클라이언트를 리다이렉트한다. 예를 들어 `http://localhost:4566`의 Ministack이 그렇다. 자격 증명은 표준 AWS 환경 변수를 쓴다.
* 배포는 S3 프리픽스나 `.tar.gz`, `.tgz`, `.zip` 아카이브, 그리고 같은 확장자를 가진 공개 HTTP와 HTTPS 아카이브를 받는다. HTTP는 표준 TLS와 리다이렉트 동작을 따르고 30초 타임아웃을 쓰며 인증 옵션은 없다. 아카이브는 절대 경로와 경로 이탈, 링크를 거부하고 최상위 단일 디렉터리는 자동으로 평탄화한다.
* `compman upgrade`는 저장된 소스로부터 `uv tool upgrade compman --reinstall --managed-python --python 3.13`으로 갱신한다. 설치가 손상되어 복구가 필요하면 `uv tool uninstall compman` 뒤에 `uv tool install --managed-python --python 3.13 git+https://github.com/allbegray/compman.git`을 실행하고 `compman --version`으로 확인한다. 복구 소스는 고정하지 않아 이후 `uv tool upgrade`가 새 릴리스로 이동할 수 있게 둔다.
* 가져온 트리는 관리되는 `dirs.project` 디렉터리 내용을 교체하며 `.git`과 `.gitkeep`은 유지한다. 루트의 `compman.yml`과 `docker-compose.yml`은 별도로 생성하거나 갱신한다.
* `--build`를 포함한 배포는 관리 트리 교체까지 트랜잭션처럼 동작한다. 이미지를 임시 소스에서 먼저 빌드하므로 빌드가 실패하면 기존 트리와 설정은 그대로 남는다. 교체 자체는 실패 시 롤백되며 교체 뒤 스캐폴드 생성이 실패했을 때만 새 소스 트리가 남을 수 있다.
* `update`는 이미지를 다시 빌드하고 컨테이너를 강제 재생성한다. 무중단 롤링 배포가 아니다.
* Docker Desktop 준비 실패를 포함한 예상 가능한 운영 실패는 파이썬 트레이스백 없이 간결한 오류로만 보여준다.
* 루트 버전 플래그는 `-v`와 `--version`이며 도움말 플래그는 루트와 명령 그룹 모두에서 `-h`와 `--help`이다.

### 백업 파일 명명

```
<스택이름>.volume.<YYYYMMDD_HHMMSS>[_<마이크로초>].tar.gz
<스택이름>.image.<YYYYMMDD_HHMMSS>[_<마이크로초>].tar.gz
```

### 품질 게이트

* Python 3.10 이상, 런타임 의존성은 typer, PyYAML, boto3, botocore, `[tool.uv] package = true`로 `uv` 기반 빌드와 실행을 한다.
* 품질 게이트는 330개 pytest 테스트, 100% 문장과 분기 커버리지, Ruff, mypy이며 CI는 Linux와 macOS, Windows에서 Python 3.10부터 3.13까지 테스트하고 패키징과 Docker와 Ministack 통합 잡을 함께 수행한다.

## 실행 기록

* **2026-08-10** — gorani 프로젝트의 `PROMPT.md` 에이전트 규칙을 적용했다. 필수 문서 6종이 모두 존재함을 확인하고 이미 영문으로 작성된 상태를 점검했다. `SECURITY.md`를 GitHub 템플릿에서 실제 정책으로 다시 쓰고 `BACKLOG.md`를 H와 M, L 라벨 체크리스트 형식으로 재구성했으며 `graphify-out/` 지식 그래프가 graphifyy v0.9.38로 빌드되어 최신 상태임을 확인했다.
* **2026-08-20** — `AGENTS.md`를 gorani `PROMPT.md` 3.1 양식에 맞춰 한국어로 전면 재구성했다. 필수 5개 섹션인 프로젝트 요약, 빌드와 테스트 방법, 에이전트 행동 지침, 서브시스템 구조, 실행 기록을 순서대로 갖추고 기존 영문 문서에 담긴 핵심 지식을 손실 없이 보존했다. 문서 거버넌스를 한국어 원칙으로 갱신하고 PowerShell UTF-8 강제, `git push` 전 6종 문서 최신화, 루트는 6종 Markdown만 허용한다는 규칙을 명시했다. 코드베이스 탐색과 수정 뒤 동기화에 `graphify query`와 `graphify --update`를 CLI로 직접 실행하는 지침을 추가했다.
* **2026-08-20** — `compose.<profile>.env_file` 문자열/리스트 지원과 파싱 규칙, `deploy _swap`의 `src/.git` 스킵을 검증하고 `CHANGELOG.md` 1.4.1과 `pyproject.toml` 1.4.1, `uv.lock` 동기화, `graphify --update` 그래프 갱신을 완료했다.
* **2026-08-20** — deploy-flex T11 문서/예제 갱신: `deploy`를 `str | dict[profile, str|{source,checksum,strategy}]`로 확장한 per-profile 배포 유연성을 사용자 문서에 노출했다. `README.md` Deploy 섹션에 per-profile YAML, 로컬 소스 `file://`와 베어 경로, `--dry-run`/`--strategy`/`--keep`/`--no-build`, `checksum: sha256:…`, `compman rollback 20260820_120000` 예제를 추가하고 제약과 버전 보관(`backup/.versions`, 기본 3개) 동작을 명시했다. `examples/compman-config/per-profile-deploy.yml`은 dev 로컬 아카이브와 prod S3+checksum+strategy를 담은 최소 파싱 가능한 YAML로 생성해 `Config.load_config`와 `resolve_deploy`로 검증했고, `10-per-profile-deploy.md`에서 dry-run diff와 rollback 선택 흐름, `update` deprecated 경로를 함께 설명하며 `examples/README.md` 인덱스에 10번으로 등록했다. `CHANGELOG.md` 최상단에 `## [1.5.0] - 2026-08-20`을 두고 `### 추가`에 per-profile deploy, local source, dry-run/strategy, rollback/versions 4줄을 기록했으며 `docs/site/index.html` Deploy 섹션에도 동일 내용을 per-profile/local/rollback 카드로 미러했다. `pyproject.toml` 버전은 1.5.0으로 동기화한다.
