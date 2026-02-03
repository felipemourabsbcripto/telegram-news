#!/bin/bash

# Script de deploy para AWS EC2
# Uso: ./deploy_aws.sh

set -e

# Configurações
KEY_PATH="$HOME/Desktop/newscripto/newscripto.pem"
SERVER="ubuntu@56.125.89.20"

echo "🚀 Iniciando deploy no AWS EC2..."
echo "📡 Servidor: $SERVER"
echo ""

# Conectar ao servidor e atualizar
ssh -i "$KEY_PATH" "$SERVER" << 'ENDSSH'
cd ~/telegram-news
echo "📥 Atualizando código..."
git pull

echo "🔄 Reiniciando serviço..."
sudo systemctl restart telegram-news

echo "⏳ Aguardando inicialização..."
sleep 3

echo "✅ Status do serviço:"
sudo systemctl status telegram-news --no-pager -l

echo ""
echo "📊 Logs recentes:"
sudo journalctl -u telegram-news -n 20 --no-pager
ENDSSH

echo ""
echo "✅ Deploy concluído!"
