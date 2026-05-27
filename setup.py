"""
꿀픽 파이프라인 자동 설치 스크립트
------------------------------------
사용법:
  1. 이 파일(setup.py) 하나만 새 PC에 저장
  2. 터미널에서: python setup.py
  3. 안내에 따라 API 키 입력
  4. 완료 후 coupang_pipeline 폴더에서 작업 시작
"""
import subprocess
import sys
import os
import shutil

REPO_URL = "https://github.com/parky091999-sudo/coupang-pipeline.git"
CLONE_DIR = "coupang_pipeline"

# .env에 들어갈 항목들: (키, 설명, 기본값 or None)
ENV_VARS = [
    ("THREADS_USERNAME",       "Threads 계정 아이디 (예: kkul.pick.kr)",    "kkul.pick.kr"),
    ("THREADS_PASSWORD",       "Threads 계정 비밀번호",                       None),
    ("NAVER_CLIENT_ID",        "네이버 API Client ID",                        None),
    ("NAVER_CLIENT_SECRET",    "네이버 API Client Secret",                    None),
    ("GROQ_API_KEY",           "Groq API Key",                                None),
    ("YOUTUBE_API_KEY",        "YouTube Data API v3 Key",                     None),
    ("COUPANG_PARTNERS_ACTIVE","쿠팡파트너스 활성화 (True/False)",             "False"),
    ("MAX_PRODUCTS_PER_RUN",   "1회 수집 상품 수",                            "5"),
]


def run(cmd, cwd=None, check=True):
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, cwd=cwd)
    if check and result.returncode != 0:
        print(f"\n오류: 명령 실패 — {cmd}")
        sys.exit(1)
    return result


def check_prerequisites():
    print("\n[1/5] 사전 요구사항 확인...")

    # Python 버전
    if sys.version_info < (3, 10):
        print(f"  오류: Python 3.10 이상 필요 (현재: {sys.version})")
        sys.exit(1)
    print(f"  Python {sys.version.split()[0]} OK")

    # Git
    if not shutil.which("git"):
        print("  오류: Git이 설치되지 않았습니다.")
        print("  설치: https://git-scm.com/download/win")
        sys.exit(1)
    print("  Git OK")


def clone_repo():
    print(f"\n[2/5] GitHub에서 코드 받기...")
    if os.path.exists(CLONE_DIR):
        print(f"  '{CLONE_DIR}' 폴더가 이미 있습니다. git pull로 최신화합니다.")
        run("git pull", cwd=CLONE_DIR)
    else:
        run(f"git clone {REPO_URL} {CLONE_DIR}")
    print(f"  완료: {os.path.abspath(CLONE_DIR)}")


def create_venv():
    print(f"\n[3/5] 가상환경(venv) 생성 및 패키지 설치...")
    venv_dir = os.path.join(CLONE_DIR, "venv")

    if not os.path.exists(venv_dir):
        run(f"python -m venv venv", cwd=CLONE_DIR)
        print("  venv 생성 완료")
    else:
        print("  venv 이미 존재 — 패키지만 업데이트")

    # Windows / Mac 경로 분기
    if sys.platform == "win32":
        pip = os.path.join(CLONE_DIR, "venv", "Scripts", "pip")
        python = os.path.join(CLONE_DIR, "venv", "Scripts", "python")
    else:
        pip = os.path.join(CLONE_DIR, "venv", "bin", "pip")
        python = os.path.join(CLONE_DIR, "venv", "bin", "python")

    run(f'"{pip}" install -r requirements.txt', cwd=CLONE_DIR)
    print("  패키지 설치 완료")
    return python


def install_playwright(python_path):
    print(f"\n[4/5] Playwright 브라우저 설치...")
    run(f'"{python_path}" -m playwright install chromium')
    print("  Chromium 설치 완료")


def create_env():
    print(f"\n[5/5] .env 파일 생성 (API 키 입력)")
    env_path = os.path.join(CLONE_DIR, ".env")

    if os.path.exists(env_path):
        answer = input("  .env 파일이 이미 있습니다. 덮어쓰시겠어요? (y/N): ").strip().lower()
        if answer != "y":
            print("  .env 유지")
            return

    print("  엔터만 누르면 기본값 사용 (없는 항목은 직접 입력 필수)\n")
    lines = []
    for key, desc, default in ENV_VARS:
        if default:
            prompt = f"  {desc}\n  {key} [{default}]: "
        else:
            prompt = f"  {desc}\n  {key}: "

        value = input(prompt).strip()
        if not value:
            if default is not None:
                value = default
            else:
                print(f"  (비워둠 — 나중에 .env에서 직접 입력 가능)")
                value = ""
        lines.append(f"{key}={value}")
        print()

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  .env 생성 완료: {os.path.abspath(env_path)}")


def print_done():
    abs_dir = os.path.abspath(CLONE_DIR)
    if sys.platform == "win32":
        activate = os.path.join(abs_dir, "venv", "Scripts", "activate")
    else:
        activate = f"source {os.path.join(abs_dir, 'venv', 'bin', 'activate')}"

    print("\n" + "=" * 50)
    print("설치 완료!")
    print("=" * 50)
    print(f"\n작업 폴더: {abs_dir}")
    print("\n다음 명령으로 시작하세요:\n")
    print(f"  cd {CLONE_DIR}")
    print(f"  {activate}")
    print(f"  python preview.py    # 미리보기 확인")
    print(f"  python main.py       # 실제 포스팅\n")
    print("VS Code에서 열기:")
    print(f"  code {CLONE_DIR}\n")


if __name__ == "__main__":
    print("=" * 50)
    print("꿀픽 파이프라인 자동 설치")
    print("=" * 50)

    check_prerequisites()
    clone_repo()
    python_path = create_venv()
    install_playwright(python_path)
    create_env()
    print_done()
