#!/usr/bin/env bash
# Mantém o túnel do RDS aberto: quando a sessão do SSM cai, abre de novo.
#
# Por que cai: a sessão do Session Manager morre com "broken pipe" quando a
# conexão fica ociosa ou oscila, e sempre que a task do ECS por onde ela
# passa é trocada (todo deploy do Jarvis). Não há ajuste que a deixe aberta
# para sempre; reconectar sozinho é o que resolve.
#
# Uso, no WSL (fica rodando em segundo plano, log em /tmp/tunel_rds.log):
#   setsid nohup bash infra/rds/manter_tunel_wsl.sh > /tmp/tunel_rds.log 2>&1 < /dev/null &
# Para parar:
#   pkill -f manter_tunel_wsl.sh; pkill -f '^session-manager-plugin'
set -uo pipefail
AQUI="$(cd "$(dirname "$0")" && pwd)"

while true; do
  echo "[$(date '+%F %T')] abrindo o túnel"
  bash "$AQUI/abrir_tunel_wsl.sh"
  echo "[$(date '+%F %T')] o túnel caiu; reabrindo em 5 s"
  sleep 5
done
