#!/bin/bash
# coupang(hyunji_zip) 텍스트 트랙 러너 — 실행 → 데이터·docs 커밋·푸시
# 사용: run_coupang.sh <script_name> [args...]   (예: auto_post / casual_post / preselect)
#
# 2026-07-24 ops 편입: EC2 로컬에만 있던 스크립트를 레포로(버전관리·복원).
#   EC2 부트스트랩: cd <repo> && git pull -q && exec ops/run_coupang.sh "$@"
# 실행 전제: CWD = 레포 루트(부트스트랩이 cd·pull 완료)
VENV=/home/ubuntu/ai-agent/venv/bin/python

SCRIPT=$1
shift
nice -n 10 "$VENV" "scripts/${SCRIPT}.py" "$@"
CODE=$?

# data/*.json 글롭은 .jsonl을 못 잡으므로 qc_log.jsonl 명시(2026-07-23 QC 게이트)
git add data/*.json docs/ data/qc_log.jsonl 2>/dev/null
if ! git diff --staged --quiet 2>/dev/null; then
  git commit -qm "auto: ${SCRIPT} (ec2 $(date -u +%F))"
  git pull --rebase --autostash -q && git push -q
fi
exit $CODE
