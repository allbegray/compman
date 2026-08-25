from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any

_CURRENT_LANG: ContextVar[str | None] = ContextVar("compman_language", default=None)


def get_lang() -> str:
    current = _CURRENT_LANG.get()
    if current:
        return current
    env_lang = os.environ.get("COMPMAN_LANG", "en").lower()
    if env_lang in ("ko", "ko_kr", "korean"):
        return "ko"
    return "en"


def set_lang(lang: str | None) -> None:
    if lang and lang.lower() in ("en", "ko"):
        _CURRENT_LANG.set(lang.lower())
    elif lang is None:
        _CURRENT_LANG.set(None)


TRANSLATIONS: dict[str, dict[str, str]] = {
    # Command descriptions
    "cmd.root": {
        "en": (
            "Docker Compose Stack Manager CLI.\n\n"
            "Language Options:\n"
            "  - Use --lang / -l <en|ko> option for a one-time language switch.\n"
            "  - Set COMPMAN_LANG=ko environment variable for a permanent setting.\n"
            "  - Run 'compman lang' to view current language or see environment setup guides."
        ),
        "ko": (
            "Docker Compose 스택 및 배포 관리 CLI.\n\n"
            "언어 설정 방법:\n"
            "  - --lang / -l <en|ko> 옵션으로 1회성 언어 전환 가능.\n"
            "  - COMPMAN_LANG=ko 환경 변수를 설정하여 영구 언어 지정 가능.\n"
            "  - 'compman lang' 명령어로 현재 언어 상태 및 설정 방법 확인 가능."
        ),
    },
    "cmd.lang": {
        "en": (
            "Display current language or switch CLI language.\n\n"
            "Examples:\n"
            "  compman lang\n"
            "  compman lang ko\n"
            "  compman lang en"
        ),
        "ko": (
            "현재 CLI 언어 상태를 표시하거나 언어를 변경합니다.\n\n"
            "사용 예시:\n"
            "  compman lang\n"
            "  compman lang ko\n"
            "  compman lang en"
        ),
    },
    "cmd.init": {
        "en": (
            "Initialize project config, fetch S3 package, or generate seed project.\n\n"
            "Provides interactive choices:\n"
            "  1. Create scaffold config (compman.yml)\n"
            "  2. Fetch package from S3 URL\n"
            "  3. Generate test seed project\n\n"
            "Examples:\n"
            "  compman init\n"
            "  compman init --scaffold\n"
            "  compman init --s3 s3://my-bucket/app.tar.gz --build\n"
            "  compman init --seed -o project -p 8080"
        ),
        "ko": (
            "프로젝트 설정, S3 패키지 수신 또는 시드 프로젝트를 생성합니다.\n\n"
            "대화형 선택 지원:\n"
            "  1. 스캐폴드 설정 (compman.yml) 생성\n"
            "  2. S3 URL로부터 패키지 수신 및 프로젝트 생성\n"
            "  3. 테스트용 Seed 프로젝트 생성\n\n"
            "사용 예시:\n"
            "  compman init\n"
            "  compman init --scaffold\n"
            "  compman init --s3 s3://my-bucket/app.tar.gz --build\n"
            "  compman init --seed -o project -p 8080"
        ),
    },
    "cmd.clear": {
        "en": (
            "Prune unused Docker images and build cache.\n\n"
            "Frees disk space by removing dangling and unused container images.\n\n"
            "Examples:\n"
            "  compman clear"
        ),
        "ko": (
            "사용하지 않는 Docker 이미지 및 빌드 캐시를 정리합니다.\n\n"
            "dangling 및 미사용 이미지를 정리하여 디스크 공간을 확보합니다.\n\n"
            "사용 예시:\n"
            "  compman clear"
        ),
    },
    "cmd.deploy": {
        "en": (
            "Fetch an application package and generate scaffold.\n\n"
            "Downloads an S3 prefix/archive or public HTTP archive, extracts it safely, and optionally builds the image.\n\n"
            "Examples:\n"
            "  compman deploy --path s3://my-bucket/app\n"
            "  compman deploy --path s3://my-bucket/app.tar.gz --build"
        ),
        "ko": (
            "배포 소스에서 애플리케이션 패키지를 다운로드하고 스캐폴드를 생성합니다.\n\n"
            "S3 경로/아카이브 또는 공개 HTTP 아카이브를 안전하게 해제하고, 필요시 이미지를 빌드합니다.\n\n"
            "사용 예시:\n"
            "  compman deploy --path s3://my-bucket/app\n"
            "  compman deploy --path s3://my-bucket/app.tar.gz --build"
        ),
    },
    "cmd.update": {
        "en": (
            "Fetch a configured deploy source, build the image, and update the stack.\n\n"
            "If a deploy source is set in compman.yml, fetches the latest package first. Otherwise, rebuilds the local image and updates the stack.\n\n"
            "Examples:\n"
            "  compman update\n"
            "  compman update dev"
        ),
        "ko": (
            "설정된 배포 소스를 수신하고 이미지 빌드 및 스택을 갱신합니다.\n\n"
            "compman.yml에 배포 소스가 설정된 경우 최신 패키지를 먼저 수신하며, 설정이 없으면 로컬 빌드로 갱신합니다.\n\n"
            "사용 예시:\n"
            "  compman update\n"
            "  compman update dev"
        ),
    },
    "cmd.doctor": {
        "en": "Diagnose configuration, Compose files, runtime, and AWS credentials.",
        "ko": "구성, Compose 파일, 런타임 및 AWS 자격 증명을 진단합니다.",
    },
    "cmd.status": {
        "en": "Show structured status for services in a running stack.",
        "ko": "실행 중인 스택 서비스의 구조화된 상태를 표시합니다.",
    },
    "cmd.ps": {
        "en": "List project containers.",
        "ko": "프로젝트 컨테이너 목록 표시",
    },
    "cmd.stats": {
        "en": "Display project container resource usage.",
        "ko": "프로젝트 컨테이너 리소스 사용량 표시",
    },
    "cmd.completion": {
        "en": (
            "Output or install shell auto-completion script.\n\n"
            "Supports powershell, bash, zsh, and fish shells.\n\n"
            "Examples:\n"
            "  compman completion powershell\n"
            "  compman completion bash --install"
        ),
        "ko": (
            "Shell 자동완성(Tab-completion) 스크립트를 출력하거나 자동 등록합니다.\n\n"
            "powershell, bash, zsh, fish 쉘을 지원합니다.\n\n"
            "사용 예시:\n"
            "  compman completion powershell\n"
            "  compman completion bash --install"
        ),
    },
    "cmd.upgrade": {
        "en": (
            "Self-upgrade compman CLI to the latest version from GitHub.\n\n"
            "Reinstalls compman from the specified repository using uv or pip.\n\n"
            "Examples:\n"
            "  compman upgrade"
        ),
        "ko": (
            "compman CLI 자체를 GitHub 최신 버전으로 셀프 업그레이드합니다.\n\n"
            "uv 또는 pip를 통해 원격 리포지토리의 최신 버전으로 자동 재설치합니다.\n\n"
            "사용 예시:\n"
            "  compman upgrade"
        ),
    },
    "cmd.stack": {
        "en": "Manage Docker Compose stack lifecycles.",
        "ko": "Docker Compose 스택 라이프사이클(up, down, update)을 관리합니다.",
    },
    "cmd.stack.up": {
        "en": (
            "Start stack containers in detached mode.\n\n"
            "Brings up containers defined in compose files.\n\n"
            "Examples:\n"
            "  compman stack up\n"
            "  compman stack up dev"
        ),
        "ko": (
            "스택 컨테이너를 백그라운드(detached) 모드로 기동합니다.\n\n"
            "compose 파일에 정의된 서비스 컨테이너를 생성 및 실행합니다.\n\n"
            "사용 예시:\n"
            "  compman stack up\n"
            "  compman stack up dev"
        ),
    },
    "cmd.stack.down": {
        "en": (
            "Stop and remove stack containers and networks.\n\n"
            "Stops running containers and removes networks. Requires --yes confirmation or interactive prompt.\n\n"
            "Examples:\n"
            "  compman stack down\n"
            "  compman stack down --yes"
        ),
        "ko": (
            "스택 컨테이너 및 네트워크를 정지하고 삭제합니다.\n\n"
            "기동 중인 스택 전체를 정지하고 제거합니다. 대화형 확인 또는 --yes 옵션이 필요합니다.\n\n"
            "사용 예시:\n"
            "  compman stack down\n"
            "  compman stack down --yes"
        ),
    },
    "cmd.stack.update": {
        "en": (
            "Rebuild images and recreate stack containers.\n\n"
            "Forces rebuild of container images and recreates updated stack containers.\n\n"
            "Examples:\n"
            "  compman stack update\n"
            "  compman stack update prod"
        ),
        "ko": (
            "이미지를 재빌드하고 스택 컨테이너를 무중단 재생성합니다.\n\n"
            "컨테이너 이미지를 강제 재빌드하고 변경된 컨테이너를 다시 기동합니다.\n\n"
            "사용 예시:\n"
            "  compman stack update\n"
            "  compman stack update prod"
        ),
    },
    "cmd.service": {
        "en": "Manage individual services within a stack.",
        "ko": "스택 내 개별 서비스(start, stop, log, connect, status)를 관리합니다.",
    },
    "cmd.service.start": {
        "en": (
            "Start specific or all services in the stack.\n\n"
            "Examples:\n"
            "  compman service start\n"
            "  compman service start app db"
        ),
        "ko": (
            "스택 내 특정 또는 전체 서비스를 시작합니다.\n\n"
            "사용 예시:\n"
            "  compman service start\n"
            "  compman service start app db"
        ),
    },
    "cmd.service.stop": {
        "en": (
            "Stop specific or all services in the stack.\n\n"
            "Examples:\n"
            "  compman service stop\n"
            "  compman service stop app"
        ),
        "ko": (
            "스택 내 특정 또는 전체 서비스를 정지합니다.\n\n"
            "사용 예시:\n"
            "  compman service stop\n"
            "  compman service stop app"
        ),
    },
    "cmd.service.restart": {
        "en": (
            "Restart specific or all services in the stack.\n\n"
            "Examples:\n"
            "  compman service restart\n"
            "  compman service restart app"
        ),
        "ko": (
            "스택 내 특정 또는 전체 서비스를 재시작합니다.\n\n"
            "사용 예시:\n"
            "  compman service restart\n"
            "  compman service restart app"
        ),
    },
    "cmd.service.status": {
        "en": (
            "Display current status of all stack containers.\n\n"
            "Examples:\n"
            "  compman service status"
        ),
        "ko": (
            "스택 내 모든 컨테이너의 현재 상태를 표시합니다.\n\n"
            "사용 예시:\n"
            "  compman service status"
        ),
    },
    "cmd.service.log": {
        "en": (
            "Display or stream logs for a service container.\n\n"
            "Supports streaming logs (-f/--follow) and limiting line count (-n/--tail).\n\n"
            "Examples:\n"
            "  compman service log\n"
            "  compman service log app -f\n"
            "  compman service log app -n 100"
        ),
        "ko": (
            "서비스 컨테이너의 로그를 조회하거나 실시간 스트리밍합니다.\n\n"
            "실시간 로그 스트리밍(-f/--follow) 및 출력 줄 수 지정(-n/--tail)을 지원합니다.\n\n"
            "사용 예시:\n"
            "  compman service log\n"
            "  compman service log app -f\n"
            "  compman service log app -n 100"
        ),
    },
    "cmd.service.connect": {
        "en": (
            "Open an interactive shell inside a service container.\n\n"
            "Executes an interactive terminal inside the target container (bash with sh fallback).\n\n"
            "Examples:\n"
            "  compman service connect\n"
            "  compman service connect app"
        ),
        "ko": (
            "서비스 컨테이너 내부로 대화형 쉘(bash/sh) 접속을 수행합니다.\n\n"
            "대상 컨테이너 내부 터미널로 대화형 쉘 접속을 실행합니다.\n\n"
            "사용 예시:\n"
            "  compman service connect\n"
            "  compman service connect app"
        ),
    },
    "cmd.volume": {
        "en": "Backup, restore, pull, or push Docker persistent volumes.",
        "ko": "Docker 파시스턴트 볼륨 백업, 복원, 풀, 푸시를 관리합니다.",
    },
    "cmd.volume.backup": {
        "en": (
            "Create a compressed backup archive of stack volumes.\n\n"
            "Copies volume data from running containers and archives them into a timestamped .tar.gz file.\n\n"
            "Examples:\n"
            "  compman volume backup\n"
            "  compman volume backup --no-stop"
        ),
        "ko": (
            "스택 볼륨의 압축 백업 아카이브를 생성합니다.\n\n"
            "컨테이너의 파시스턴트 볼륨 데이터를 추출하고 타임스탬프 .tar.gz 아카이브 파일로 백업합니다.\n\n"
            "사용 예시:\n"
            "  compman volume backup\n"
            "  compman volume backup --no-stop"
        ),
    },
    "cmd.volume.restore": {
        "en": (
            "Restore stack volumes from a backup archive timestamp.\n\n"
            "Restores volume data from a specified timestamp archive back into container volumes.\n\n"
            "Examples:\n"
            "  compman volume restore 20260731_1732\n"
            "  compman volume restore 20260731_1732 --no-stop"
        ),
        "ko": (
            "백업 아카이브 타임스탬프로부터 스택 볼륨을 복원합니다.\n\n"
            "지정한 타임스탬프의 아카이브 데이터로부터 컨테이너 볼륨으로 데이터를 복원합니다.\n\n"
            "사용 예시:\n"
            "  compman volume restore 20260731_1732\n"
            "  compman volume restore 20260731_1732 --no-stop"
        ),
    },
    "cmd.volume.pull": {
        "en": (
            "Extract volume data from containers into local directory.\n\n"
            "Copies volume files from containers into local ./volume directory.\n\n"
            "Examples:\n"
            "  compman volume pull"
        ),
        "ko": (
            "컨테이너 볼륨 데이터를 로컬 디렉터리로 추출합니다.\n\n"
            "컨테이너 내부의 볼륨 파일들을 로컬 ./volume 디렉터리로 복사합니다.\n\n"
            "사용 예시:\n"
            "  compman volume pull"
        ),
    },
    "cmd.volume.push": {
        "en": (
            "Upload local volume directory data into containers.\n\n"
            "Uploads files from local ./volume directory into container volumes.\n\n"
            "Examples:\n"
            "  compman volume push"
        ),
        "ko": (
            "로컬 디렉터리 볼륨 데이터를 컨테이너로 업로드합니다.\n\n"
            "로컬 ./volume 디렉터리의 파일들을 컨테이너 볼륨으로 업로드합니다.\n\n"
            "사용 예시:\n"
            "  compman volume push"
        ),
    },
    "cmd.image": {
        "en": "Backup or restore Docker container images.",
        "ko": "Docker 컨테이너 이미지를 백업하거나 복원합니다.",
    },
    "cmd.image.backup": {
        "en": (
            "Commit and export stack container images to tar.gz archive.\n\n"
            "Saves runtime container state (or original image via --source-image) to a timestamped backup archive.\n\n"
            "Examples:\n"
            "  compman image backup\n"
            "  compman image backup --source-image"
        ),
        "ko": (
            "스택 컨테이너 이미지를 커밋하고 tar.gz 아카이브로 내보냅니다.\n\n"
            "현재 실행 상태 컨테이너(또는 --source-image 지정 시 원본 이미지)를 타임스탬프 백업 아카이브로 저장합니다.\n\n"
            "사용 예시:\n"
            "  compman image backup\n"
            "  compman image backup --source-image"
        ),
    },
    "cmd.image.restore": {
        "en": (
            "Import container images from a backup archive timestamp.\n\n"
            "Loads a container image from a timestamped backup archive.\n\n"
            "Examples:\n"
            "  compman image restore 20260731_1732"
        ),
        "ko": (
            "백업 아카이브 타임스탬프로부터 컨테이너 이미지를 불러옵니다.\n\n"
            "타임스탬프 백업 아카이브 파일로부터 컨테이너 이미지를 로드합니다.\n\n"
            "사용 예시:\n"
            "  compman image restore 20260731_1732"
        ),
    },

    "cmd.version": {
        "en": "Display the current compman CLI version.",
        "ko": "현재 compman CLI 버전을 표시합니다.",
    },

    # Option descriptions
    "opt.force": {
        "en": "Overwrite existing files",
        "ko": "기존 파일 덮어쓰기",
    },
    "opt.archive": {
        "en": "Compress generated seed files into a .tar.gz archive.",
        "ko": "생성된 시드 파일들을 .tar.gz 아카이브 파일로 압축합니다.",
    },
    "opt.output": {
        "en": "Output directory or archive base name (default: project).",
        "ko": "출력 디렉터리 또는 아카이브 기본 이름 (기본값: project).",
    },
    "opt.port": {
        "en": "Port number for the sample app (default: 18080).",
        "ko": "샘플 애플리케이션의 포트 번호 (기본값: 18080).",
    },
    "opt.config": {
        "en": "Path to compman.yml",
        "ko": "compman.yml 설정 파일 경로",
    },
    "opt.all": {
        "en": "Include stopped containers",
        "ko": "중지된 컨테이너 포함",
    },
    "opt.json": {
        "en": "Output as JSON",
        "ko": "JSON으로 출력",
    },
    "opt.path": {
        "en": "S3 URI or public HTTP archive URL (default: 'deploy' in compman.yml)",
        "ko": "S3 URI 또는 공개 HTTP 아카이브 URL (기본값: compman.yml의 deploy 속성)",
    },
    "opt.build": {
        "en": "Build Docker image after fetching",
        "ko": "패키지 수신 후 Docker 이미지 빌드",
    },
    "opt.tag": {
        "en": "Image tag when building (default: directory name)",
        "ko": "빌드 시 이미지 태그명 (기본값: 디렉터리명)",
    },
    "opt.path_sha256": {
        "en": "Expected SHA-256 digest of the deploy archive (64 hexadecimal characters)",
        "ko": "배포 아카이브의 예상 SHA-256 다이제스트(64자리 16진수)",
    },
    "opt.install": {
        "en": "Automatically install completion script into shell profile.",
        "ko": "Shell 프로필에 자동완성 스크립트를 자동 등록합니다.",
    },
    "opt.repo": {
        "en": "Git repository URL used only for pip fallback or manual recovery",
        "ko": "pip 대체 설치 또는 수동 복구에만 사용할 Git 저장소 URL",
    },
    "opt.no_stop": {
        "en": "Don't stop stack during backup/restore",
        "ko": "백업/복원 시 스택을 정지하지 않고 진행",
    },
    "opt.source_image": {
        "en": "Backup original image instead of committing runtime state",
        "ko": "실행 중인 상태 커밋 대신 원본 이미지를 백업",
    },
    "opt.compression_level": {
        "en": "gzip compression level (1=fastest, 9=smallest)",
        "ko": "gzip 압축 레벨 (1=가장 빠름, 9=가장 작음)",
    },
    "opt.follow": {
        "en": "Stream output continuously.",
        "ko": "출력을 실시간으로 계속 표시합니다.",
    },
    "opt.tail": {
        "en": "Number of lines to show from the end of logs (default: 50).",
        "ko": "로그 출력할 마지막 라인 수 (기본값: 50).",
    },
    "opt.clear_yes": {
        "en": "Confirm removal of all unused images",
        "ko": "사용하지 않는 모든 이미지 제거 확인",
    },
    "opt.profile": {
        "en": "Compose profile",
        "ko": "컴포즈 프로필",
    },
    "opt.restore_timestamp": {
        "en": "Timestamp of backup to restore (YYYYMMDD_HHMM)",
        "ko": "복원할 백업 타임스탬프 (YYYYMMDD_HHMM)",
    },
    "opt.seed": {
        "en": "Generate test seed project",
        "ko": "테스트 시드 프로젝트 생성",
    },
    "opt.scaffold": {
        "en": "Create default compman.yml scaffold",
        "ko": "기본 compman.yml 스캐폴드 생성",
    },
    "opt.s3": {
        "en": "Fetch package from S3 URL",
        "ko": "S3 URL에서 패키지 가져오기",
    },
    "opt.lang": {
        "en": "Language (en/ko)",
        "ko": "언어 (en/ko)",
    },
    "opt.language_code": {
        "en": "Language code (en or ko)",
        "ko": "언어 코드 (en 또는 ko)",
    },
    "opt.confirm_stack_removal": {
        "en": "Confirm stack removal",
        "ko": "스택 제거 확인",
    },
    "opt.replace": {
        "en": "Replace destination contents instead of merging",
        "ko": "대상 내용을 병합 대신 교체",
    },

    # Guidance & Error Messages
    "msg.config_not_found": {
        "en": "Info: compman.yml config file not found ({err})",
        "ko": "안내: compman.yml 설정 파일을 찾을 수 없습니다 ({err})",
    },
    "msg.unknown_command": {
        "en": "Error: Unknown command '{command}'.",
        "ko": "오류: 알 수 없는 명령어입니다: '{command}'",
    },
    "msg.command_failed": {
        "en": "Error: {error}",
        "ko": "오류: {error}",
    },
    "msg.runtime_error": {
        "en": "Runtime error: {error}",
        "ko": "런타임 오류: {error}",
    },
    "msg.config_exists": {
        "en": "{config} already exists. Use --force to overwrite.",
        "ko": "{config} 파일이 이미 존재합니다. 덮어쓰려면 --force를 사용하세요.",
    },
    "msg.config_created": {
        "en": "{config} created:\n----------------------------------------\n{content}\n----------------------------------------",
        "ko": "{config} 생성됨:\n----------------------------------------\n{content}\n----------------------------------------",
    },
    "msg.prune_images": {
        "en": "Pruning unused Docker images...",
        "ko": "사용하지 않는 Docker 이미지를 정리하는 중...",
    },
    "msg.completion_registered": {
        "en": "Registered {shell} auto-completion script in {path}",
        "ko": "{path}에 {shell} 자동완성 스크립트를 등록했습니다.",
    },
    "msg.completion_exists": {
        "en": "{path} already has auto-completion registered.",
        "ko": "{path}에 자동완성이 이미 등록되어 있습니다.",
    },
    "msg.completion_error": {
        "en": "Error registering PowerShell completion: {error}",
        "ko": "PowerShell 자동완성 등록 오류: {error}",
    },
    "msg.upgrade_start": {
        "en": "Upgrading compman CLI...",
        "ko": "compman CLI를 업그레이드하는 중...",
    },
    "msg.upgrade_success": {
        "en": "compman CLI upgraded successfully!",
        "ko": "compman CLI 업그레이드가 완료되었습니다!",
    },
    "msg.upgrade_error": {
        "en": "Error upgrading compman: {error}",
        "ko": "compman 업그레이드 오류: {error}",
    },
    "msg.lang_set": {
        "en": "Current session language set to: {language}",
        "ko": "현재 세션 언어를 다음으로 설정했습니다: {language}",
    },
    "msg.lang_unsupported": {
        "en": "Unsupported language code: '{language}'. Use 'en' or 'ko'.",
        "ko": "지원하지 않는 언어 코드입니다: '{language}'. 'en' 또는 'ko'를 사용하세요.",
    },
    "msg.lang_info": {
        "en": "compman CLI Language Info:",
        "ko": "compman CLI 언어 정보:",
    },
    "msg.lang_active": {
        "en": "  - Active Language : {language}",
        "ko": "  - 현재 언어 : {language}",
    },
    "msg.lang_env": {
        "en": "  - COMPMAN_LANG Env: {value}",
        "ko": "  - COMPMAN_LANG 환경 변수: {value}",
    },
    "msg.lang_persistent": {
        "en": "Info: To set language permanently via environment variable:",
        "ko": "안내: 환경 변수로 언어를 영구 설정하려면:",
    },
    "msg.deploy_building": {
        "en": "Building image '{image}' in {path}...",
        "ko": "{path}에서 '{image}' 이미지를 빌드하는 중...",
    },
    "msg.deploy_done": {
        "en": "Deploy done.",
        "ko": "배포가 완료되었습니다.",
    },
    "msg.s3_client_error": {
        "en": "S3 Client Error ({code}): {error}",
        "ko": "S3 클라이언트 오류 ({code}): {error}",
    },
    "msg.download_error": {
        "en": "Download Error: {error}",
        "ko": "다운로드 오류: {error}",
    },
    "msg.operation_cancelled": {
        "en": "Operation cancelled.",
        "ko": "작업이 취소되었습니다.",
    },
    "msg.no_backups": {
        "en": "Info: No {kind} backup files found in {path}.",
        "ko": "안내: {path}에 {kind} 백업 파일이 없습니다.",
    },
    "msg.selected_backup": {
        "en": "Selected backup: {name}",
        "ko": "선택된 백업: {name}",
    },
    "msg.auto_selected": {
        "en": "Auto-selected: {name}",
        "ko": "자동 선택됨: {name}",
    },
    "msg.available_containers": {
        "en": "Available containers:",
        "ko": "사용 가능한 컨테이너:",
    },
    "msg.specify_container": {
        "en": "Specify a container name:",
        "ko": "컨테이너 이름을 지정하세요:",
    },
    "msg.start_guide": {
        "en": "Start by running one of the following commands:",
        "ko": "다음 명령어로 기본 설정 파일을 생성하거나 첫 배포를 진행해보세요:",
    },
    "msg.init_desc": {
        "en": "Generate default compman.yml",
        "ko": "기본 compman.yml 생성",
    },
    "msg.deploy_desc": {
        "en": "Deploy directly from a source URI",
        "ko": "소스 URI로 바로 첫 배포",
    },
    "msg.empty_dir_deploy": {
        "en": "Info: [compman deploy] Empty directory without compman.yml config file.",
        "ko": "안내: [compman deploy] compman.yml 설정 파일이 없는 빈 디렉터리입니다.",
    },
    "msg.empty_dir_start": {
        "en": "Start by running one of the following commands:",
        "ko": "다음 중 하나로 첫 배포 또는 설정을 시작해보세요:",
    },
    "msg.deploy_direct_hint": {
        "en": "  1. Deploy directly with a source URI:",
        "ko": "  1. 소스 URI로 바로 배포:",
    },
    "msg.config_hint": {
        "en": "  2. Generate a default compman.yml:",
        "ko": "  2. 기본 compman.yml 생성:",
    },
    "msg.deploy_path_not_configured": {
        "en": "Info: [compman deploy] Deployment source is not configured.",
        "ko": "안내: [compman deploy] 배포 소스가 지정되지 않았습니다.",
    },
    "msg.deploy_path_hint1": {
        "en": "  - Specify 'deploy' field in compman.yml, or",
        "ko": "  - compman.yml 파일의 'deploy' 속성을 지정하거나,",
    },
    "msg.deploy_path_hint2": {
        "en": "  - Pass a source via option: compman deploy --path <source-uri>",
        "ko": "  - compman deploy --path <source-uri> 옵션으로 배포 소스를 전달해주세요.",
    },
    "msg.stack_not_running": {
        "en": "Info: Stack '{name}' is not currently running. Run 'compman stack up' to start it.",
        "ko": "안내: 스택 '{name}'이(가) 현재 실행 중이지 않습니다. 'compman stack up' 커맨드로 시작하세요.",
    },
    "msg.no_running_containers": {
        "en": "Info: No running containers found in this stack. Run 'compman stack up' first.",
        "ko": "안내: 실행 중인 스택 컨테이너가 없습니다. 'compman stack up' 커맨드를 먼저 실행하세요.",
    },
    "msg.backup_not_found": {
        "en": "Info: Backup not found: {tarball}",
        "ko": "안내: 백업 파일을 찾을 수 없습니다: {tarball}",
    },
    "msg.volume_map_not_found": {
        "en": "Info: volume-map.json not found at {path}. Run 'compman volume pull' first.",
        "ko": "안내: {path} 위치에 volume-map.json이 없습니다. 'compman volume pull'을 먼저 실행하세요.",
    },
    "msg.s3_failed": {
        "en": "Info: [compman deploy] Failed to download from {path}",
        "ko": "안내: [compman deploy] {path} 다운로드 실패",
    },
    "msg.s3_no_creds": {
        "en": "Error: AWS credentials were not found or are incomplete.\n\nGuide - Please set your AWS credentials using environment variables:\n  - Windows PowerShell:\n      $env:AWS_ACCESS_KEY_ID=\"your-key-id\"\n      $env:AWS_SECRET_ACCESS_KEY=\"your-secret-key\"\n      $env:AWS_DEFAULT_REGION=\"ap-northeast-2\"\n  - Windows CMD:\n      set AWS_ACCESS_KEY_ID=your-key-id\n      set AWS_SECRET_ACCESS_KEY=your-secret-key\n      set AWS_DEFAULT_REGION=ap-northeast-2\n  - Or configure credentials in ~/.aws/credentials",
        "ko": "오류: AWS 자격 증명을 찾을 수 없거나 불완전합니다.\n\n가이드 - 환경 변수로 AWS 자격 증명을 설정하세요:\n  - Windows PowerShell:\n      $env:AWS_ACCESS_KEY_ID=\"your-key-id\"\n      $env:AWS_SECRET_ACCESS_KEY=\"your-secret-key\"\n      $env:AWS_DEFAULT_REGION=\"ap-northeast-2\"\n  - Windows CMD:\n      set AWS_ACCESS_KEY_ID=your-key-id\n      set AWS_SECRET_ACCESS_KEY=your-secret-key\n      set AWS_DEFAULT_REGION=ap-northeast-2\n  - 또는 ~/.aws/credentials 파일에 설정",
    },
    "msg.s3_403": {
        "en": "Error 403 (Access Denied): Access to '{path}' was forbidden.\n\nGuide - Troubleshooting 403 Forbidden:\n  1. Ensure AWS credentials have 's3:GetObject' and 's3:ListBucket' permissions.\n  2. Verify S3 bucket name and key path are correct.\n  3. If using local S3 (e.g. ministack), check AWS_ENDPOINT_URL_S3 or AWS_ENDPOINT_URL.",
        "ko": "오류 403 (접근 거부): '{path}' 접근 권한이 거부되었습니다.\n\n가이드 - 403 Forbidden 해결 방법:\n  1. AWS 자격 증명에 's3:GetObject' 및 's3:ListBucket' 권한이 있는지 확인하세요.\n  2. S3 버킷 이름 및 객체 경로가 정확한지 확인하세요.\n  3. 로컬 S3 에뮬레이터 사용 시 AWS_ENDPOINT_URL_S3 또는 AWS_ENDPOINT_URL 환경 변수를 확인하세요.",
    },
    "msg.s3_404": {
        "en": "Error 404 (Not Found): Bucket or file does not exist: '{path}'\n\nGuide - Troubleshooting 404 Not Found:\n  1. Verify bucket name and file/archive path on S3.\n  2. Check for typos in s3://bucket/path",
        "ko": "오류 404 (찾을 수 없음): 버킷 또는 파일이 S3에 존재하지 않습니다: '{path}'\n\n가이드 - 404 Not Found 해결 방법:\n  1. S3의 버킷 이름 및 아카이브 파일 경로를 확인하세요.\n  2. s3://bucket/path 오타 여부를 확인하세요.",
    },
    "msg.s3_network": {
        "en": "Network Error: Unable to connect to S3 endpoint.\n\nGuide - Troubleshooting connection error:\n  1. Check internet connection.\n  2. If using local S3 (e.g. ministack), check AWS_ENDPOINT_URL_S3 or AWS_ENDPOINT_URL.",
        "ko": "네트워크 오류: S3 엔드포인트에 연결할 수 없습니다.\n\n가이드 - 네트워크 연결 오류 해결 방법:\n  1. 인터넷 연결 상태를 확인하세요.\n  2. 로컬 S3 에뮬레이터 사용 시 AWS_ENDPOINT_URL_S3 또는 AWS_ENDPOINT_URL 환경 변수를 확인하세요.",
    },
    "msg.seed_created": {
        "en": "Created sample seed project: {path}/",
        "ko": "샘플 시드 프로젝트가 생성되었습니다: {path}/",
    },
    "msg.seed_archive_created": {
        "en": "Archive created: {path}",
        "ko": "아카이브 파일이 생성되었습니다: {path}",
    },
    "msg.seed_exists": {
        "en": "Info: Directory '{path}' already exists and is not empty. Use --force to overwrite.",
        "ko": "안내: 디렉터리 '{path}'가 이미 존재하며 비어있지 않습니다. 덮어쓰려면 --force 옵션을 사용하세요.",
    },
    "msg.invalid_port": {
        "en": "Error: port must be between 1 and 65535 (got {port}).",
        "ko": "오류: 포트는 1에서 65535 사이여야 합니다 ({port}).",
    },
    "msg.no_volumes": {
        "en": "Info: No volumes found to back up.",
        "ko": "안내: 백업할 볼륨이 없습니다.",
    },
    "msg.backup_done": {
        "en": "{kind} backup done: {path}",
        "ko": "{kind} 백업 완료: {path}",
    },
    "msg.backup_downloading": {
        "en": "Downloading {name} from {path}",
        "ko": "{path}에서 {name} 다운로드하는 중...",
    },
    "msg.backup_store_error": {
        "en": "Backup store operation failed: {detail}",
        "ko": "백업 저장소 작업이 실패했습니다: {detail}",
    },
    "msg.backup_pruned": {
        "en": "Pruned old backup {name}",
        "ko": "오래된 백업 {name}을(를) 삭제했습니다.",
    },
    "msg.backup_prune_failed": {
        "en": "Could not prune old backup {name}: {detail}",
        "ko": "오래된 백업 {name}을(를) 삭제하지 못했습니다: {detail}",
    },
    "msg.restore_done": {
        "en": "{kind} restore done.",
        "ko": "{kind} 복원 완료.",
    },
    "msg.loading_image": {
        "en": "Loading {name} ...",
        "ko": "{name} 로드 중 ...",
    },
    "msg.image_restore_hint": {
        "en": "Update docker-compose.yml image tags and run 'compman stack up'.",
        "ko": "docker-compose.yml 이미지 tag를 갱신하고 'compman stack up'을 실행하세요.",
    },
    "msg.available_backups": {
        "en": "Available {kind} backups:",
        "ko": "사용 가능한 {kind} 백업:",
    },
    "msg.warning_missing_data": {
        "en": "Warning: data dir '{path}' not found, skipping {container}.",
        "ko": "경고: 데이터 디렉터리 '{path}'가 없어 {container}을(를) 건너뜁니다.",
    },
    "msg.restoring_data": {
        "en": "Restoring {container}:{destination} ...",
        "ko": "{container}:{destination} 복원 중 ...",
    },
    "msg.warning_missing_source": {
        "en": "Warning: '{path}' not found, skipping {container}.",
        "ko": "경고: '{path}'가 없어 {container}을(를) 건너뜁니다.",
    },
    "msg.pushing_data": {
        "en": "Pushing to {container}:{destination} ...",
        "ko": "{container}:{destination}로 전송 중 ...",
    },
    "msg.docker_desktop_prompt": {
        "en": "Docker Desktop is not running. Start it now?",
        "ko": "Docker Desktop이 실행 중이 아닙니다. 지금 시작할까요?",
    },
    "msg.stack_stopping": {
        "en": "Stopping stack for consistent operation...",
        "ko": "일관된 작업을 위해 스택을 중지합니다...",
    },
    "msg.stack_starting": {
        "en": "Starting stack again...",
        "ko": "스택을 다시 시작합니다...",
    },
    "msg.stack_restart_failed": {
        "en": "Warning: failed to restart stack: {error}",
        "ko": "경고: 스택 재시작에 실패했습니다: {error}",
    },
    "msg.available_backups_title": {
        "en": "Available {kind} backups",
        "ko": "사용 가능한 {kind} 백업",
    },
    "msg.invalid_timestamp": {
        "en": "Invalid timestamp: {ts} (expected YYYYMMDD_HHMM[SS])",
        "ko": "잘못된 타임스탬프: {ts} (형식: YYYYMMDD_HHMM[SS])",
    },
    "msg.created_compman": {
        "en": "Created compman.yml:",
        "ko": "compman.yml 생성됨:",
    },
    "msg.created_compose": {
        "en": "Created docker-compose.yml:",
        "ko": "docker-compose.yml 생성됨:",
    },
    "msg.remove_stack_confirm": {
        "en": "Remove the entire stack?",
        "ko": "전체 스택을 제거하시겠습니까?",
    },
    "msg.enter_s3_url": {
        "en": "Enter S3 URL (e.g. s3://bucket/path/app.tar.gz)",
        "ko": "S3 URL을 입력하세요 (예: s3://bucket/path/app.tar.gz)",
    },
    "msg.doctor_header": {
        "en": "Doctor:",
        "ko": "진단:",
    },
    "msg.services_list": {
        "en": "Services: {names}",
        "ko": "서비스: {names}",
    },
    "msg.all_services": {
        "en": "All services",
        "ko": "모든 서비스",
    },
    "msg.updated_deploy": {
        "en": "Updated deploy in compman.yml ({s3_path}):",
        "ko": "compman.yml의 배포 대상을 업데이트했습니다 ({s3_path}):",
    },
    "msg.deploy_failed_stage": {
        "en": "Deploy failed while {stage}: {error}",
        "ko": "배포 실패 ({stage} 단계): {error}",
    },
    "msg.select_option": {
        "en": "Select option [1-{count}]",
        "ko": "옵션을 선택하세요 [1-{count}]",
    },
    "msg.prompt_nav": {
        "en": "{title} (Use Up/Down or number keys, Enter to select, Esc to cancel):",
        "ko": "{title} (↑/↓ 또는 숫자 키로 선택, Enter로 확정, Esc로 취소):",
    },
    "msg.clear_confirm": {
        "en": "Remove all unused images (docker image prune -af)? This also affects images outside the current project.",
        "ko": "사용하지 않는 모든 이미지를 제거하시겠습니까 (docker image prune -af)? 현재 프로젝트 외부의 이미지도 함께 제거됩니다.",
    },
    "msg.invalid_replace_dest": {
        "en": "Invalid --replace destination: {dest}",
        "ko": "--replace 대상 경로가 올바르지 않습니다: {dest}",
    },
    "msg.resolved_container": {
        "en": "Using container {container} for service {service}.",
        "ko": "서비스 {service}의 컨테이너 {container}을(를) 사용합니다.",
    },
    "msg.scaled_service_ambiguous": {
        "en": "Service {service} has {count} running instances. Specify the exact container name.",
        "ko": "서비스 {service}에 실행 중인 인스턴스가 {count}개입니다. 정확한 컨테이너 이름을 지정하세요.",
    },
    "msg.deploy_limit_exceeded": {
        "en": "Deploy source exceeds the {limit} MB size limit ({size} bytes).",
        "ko": "배포 소스가 {limit} MB 크기 제한을 초과합니다 ({size} bytes).",
    },
    "msg.deploy_provenance": {
        "en": "Source: {source} ({size} bytes)",
        "ko": "소스: {source} ({size} bytes)",
    },
    "msg.deploy_checksum_verified": {
        "en": "Verified SHA-256: {digest}",
        "ko": "SHA-256 검증 완료: {digest}",
    },
    "msg.deploy_checksum_mismatch": {
        "en": "Deploy source failed SHA-256 verification (expected {expected}, got {actual})",
        "ko": "배포 소스가 SHA-256 검증에 실패했습니다(예상 {expected}, 실제 {actual})",
    },
    "msg.deploy_checksum_requires_archive": {
        "en": "SHA-256 verification requires an archive deploy source (.tar.gz, .tgz, or .zip), not an S3 prefix: {path}",
        "ko": "SHA-256 검증은 아카이브 배포 소스(.tar.gz, .tgz, .zip)에서만 지원됩니다. S3 프리픽스: {path}",
    },
    "msg.deploy_auth_env_missing": {
        "en": "Authentication environment variable '{name}' is not set.",
        "ko": "'{name}' 인증 환경 변수가 설정되지 않았습니다.",
    },
    "msg.deploy_auth_value_invalid": {
        "en": "Authentication environment variable '{name}' must not contain line breaks.",
        "ko": "인증 환경 변수 '{name}'에는 줄바꿈을 사용할 수 없습니다.",
    },
    "msg.deploy_config_invalid": {
        "en": "compman.yml could not be parsed: {err}",
        "ko": "compman.yml을(를) 해석할 수 없습니다: {err}",
    },
    "msg.update_tag_mismatch": {
        "en": "Multiple service images found ({images}); skipping the automatic rebuild because the rebuild target is ambiguous.",
        "ko": "여러 서비스 이미지가 발견되어({images}) 재빌드 대상을 특정할 수 없어 자동 재빌드를 건너뜁니다.",
    },
    "opt.wait": {
        "en": "Wait until every service is running (or healthy) before returning",
        "ko": "모든 서비스가 실행 중(또는 healthy) 상태가 될 때까지 기다린 후 반환합니다",
    },
    "msg.stack_wait_timeout": {
        "en": "Services did not become ready within {seconds}s: {detail}",
        "ko": "{seconds}초 안에 서비스가 준비되지 않았습니다: {detail}",
    },
    "msg.stats_follow_json": {
        "en": "Cannot combine --follow with --json.",
        "ko": "--follow와 --json은 함께 사용할 수 없습니다.",
    },
    "msg.unsupported_shell": {
        "en": "Unsupported shell: {shell}",
        "ko": "지원하지 않는 셸: {shell}",
    },
    "msg.volume_map_escape": {
        "en": "Volume map entry escapes the backup directory: {name}",
        "ko": "볼륨 맵 항목이 백업 디렉터리를 벗어납니다: {name}",
    },
    "msg.volume_map_container": {
        "en": "Volume map references unknown container {container} in project {name}.",
        "ko": "볼륨 맵이 프로젝트 {name}의 알 수 없는 컨테이너 {container}을(를) 참조합니다.",
    },
    "msg.init_select_mode": {
        "en": "Select initialization mode",
        "ko": "초기화 모드를 선택하세요",
    },
    "msg.init_mode_scaffold": {
        "en": "1. Create scaffold config (compman.yml)",
        "ko": "1. 스캐폴드 설정 생성 (compman.yml)",
    },
    "msg.init_mode_s3": {
        "en": "2. Fetch package from S3 URL",
        "ko": "2. S3 URL에서 패키지 가져오기",
    },
    "msg.init_mode_seed": {
        "en": "3. Generate test seed project (app.py, Dockerfile, compose)",
        "ko": "3. 테스트 시드 프로젝트 생성 (app.py, Dockerfile, compose)",
    },
    "msg.status_header": {
        "en": "Status:",
        "ko": "상태:",
    },
    "msg.status_runtime": {
        "en": "runtime:",
        "ko": "런타임:",
    },
    "msg.status_profile": {
        "en": "profile:",
        "ko": "프로필:",
    },
    "cmd.schedule.help": {
        "en": "Manage scheduled volume backups.",
        "ko": "예약된 볼륨 백업을 관리합니다.",
    },
    "cmd.schedule.add.help": {
        "en": (
            "Register a scheduled volume backup on the platform scheduler.\n\n"
            "Examples:\n"
            "  compman schedule add --every 30m --no-stop\n"
            "  compman schedule add --daily 04:30\n"
            "  compman schedule add --weekly sun 03:00 -z 9"
        ),
        "ko": (
            "플랫폼 스케줄러에 볼륨 백업을 등록합니다.\n\n"
            "사용 예시:\n"
            "  compman schedule add --every 30m --no-stop\n"
            "  compman schedule add --daily 04:30\n"
            "  compman schedule add --weekly sun 03:00 -z 9"
        ),
    },
    "cmd.schedule.list.help": {
        "en": "List registered backup schedules.",
        "ko": "등록된 백업 예약 목록을 표시합니다.",
    },
    "cmd.schedule.remove.help": {
        "en": "Remove a registered backup schedule.",
        "ko": "등록된 백업 예약을 제거합니다.",
    },
    "opt.every": {
        "en": "Run every N minutes or hours, e.g. 30m or 6h",
        "ko": "N분 또는 N시간 간격으로 실행합니다(예: 30m, 6h)",
    },
    "opt.daily": {
        "en": "Run daily at HH:MM (local time)",
        "ko": "매일 HH:MM에 실행합니다(현지 시간)",
    },
    "opt.weekly": {
        "en": "Run weekly, e.g. 'sun 03:00'",
        "ko": "매주 지정한 요일과 시간에 실행합니다(예: 'sun 03:00')",
    },
    "opt.job_name": {
        "en": "Override the derived schedule name",
        "ko": "자동 생성된 예약 이름을 대체합니다",
    },
    "opt.scheduler": {
        "en": "Force the Linux scheduler mechanism (systemd or cron)",
        "ko": "Linux 스케줄러 방식을 강제 지정합니다(systemd 또는 cron)",
    },
    "msg.schedule.added": {
        "en": "Scheduled backup '{name}' registered ({platform}).",
        "ko": "예약 백업 '{name}'이(가) 등록되었습니다({platform}).",
    },
    "msg.schedule_registry_corrupt": {
        "en": "Corrupt schedule registry at {path}; moved to {backup}. Starting with an empty registry.",
        "ko": "손상된 예약 레지스트리를 {path}에서 발견하여 {backup}(으)로 옮겼습니다. 빈 레지스트리로 시작합니다.",
    },
    "msg.schedule.removed": {
        "en": "Scheduled backup '{name}' removed.",
        "ko": "예약 백업 '{name}'이(가) 제거되었습니다.",
    },
    "msg.schedule.list_header": {
        "en": "Registered backup schedules:",
        "ko": "등록된 백업 예약:",
    },
    "msg.schedule.list_empty": {
        "en": "No backup schedules registered.",
        "ko": "등록된 백업 예약이 없습니다.",
    },
    "msg.schedule.missing": {
        "en": "[missing]",
        "ko": "[누락]",
    },
    "msg.schedule.cadence_conflict": {
        "en": "Specify exactly one of --every, --daily, or --weekly.",
        "ko": "--every, --daily, --weekly 중 정확히 하나만 지정해야 합니다.",
    },
    "msg.schedule.cadence_invalid": {
        "en": "Invalid cadence '{value}': {reason}",
        "ko": "잘못된 주기 '{value}': {reason}",
    },
    "msg.schedule.exists": {
        "en": (
            "A schedule named '{name}' is already registered (config: {path}). "
            "Remove it first or pass --name."
        ),
        "ko": (
            "'{name}' 이름의 예약이 이미 등록되어 있습니다(config: {path}). "
            "먼저 제거하거나 --name을 사용하세요."
        ),
    },
    "msg.schedule.not_found": {
        "en": "No schedule named '{name}' is registered.",
        "ko": "'{name}' 이름으로 등록된 예약이 없습니다.",
    },
    "msg.schedule.executable_not_found": {
        "en": (
            "Could not resolve the installed compman executable. "
            "Install with 'uv tool install .' and retry."
        ),
        "ko": (
            "설치된 compman 실행 파일을 확인할 수 없습니다. "
            "'uv tool install .'로 설치한 후 다시 시도하세요."
        ),
    },
    "msg.schedule.cron_interval": {
        "en": (
            "'--every {value}' cannot be expressed in cron; use a divisor of 60 (minutes) "
            "or 24 (hours), or force --scheduler systemd."
        ),
        "ko": (
            "'--every {value}'은(는) cron으로 표현할 수 없습니다. 60(분) 또는 24(시간)의 "
            "배수 간격을 사용하거나 --scheduler systemd를 강제하세요."
        ),
    },
    "msg.schedule.no_mechanism": {
        "en": "Neither a systemd user session nor a writable crontab is available: {detail}",
        "ko": "사용 가능한 systemd 사용자 세션도 쓰기 가능한 crontab도 없습니다: {detail}",
    },
    "msg.schedule.force_unsupported": {
        "en": "--scheduler can only be forced on Linux; this platform uses its native scheduler.",
        "ko": "--scheduler는 Linux에서만 강제할 수 있습니다. 이 플랫폼은 기본 스케줄러를 사용합니다.",
    },
    "msg.schedule.unsupported_platform": {
        "en": "Scheduling is not supported on {system}.",
        "ko": "{system}에서는 예약 기능을 지원하지 않습니다.",
    },
    "msg.schedule.already_gone": {
        "en": "Platform entry for '{name}' was already missing; removed from registry.",
        "ko": "'{name}'의 플랫폼 항목이 이미 없습니다. 레지스트리에서만 제거했습니다.",
    },
}


def t(translation_key: str, lang: str | None = None, **kwargs: Any) -> str:
    language = lang or get_lang()
    entry = TRANSLATIONS.get(translation_key, {})
    text = entry.get(language) or entry.get("en") or translation_key
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text
