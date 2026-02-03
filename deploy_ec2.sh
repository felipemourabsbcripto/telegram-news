#!/bin/bash
# ============================================================
# Deploy Script para AWS EC2 - CriptonewsFelipeMoura Bot
# ============================================================

echo "🚀 Iniciando deploy para AWS EC2..."

# Variáveis - EDITE COM SEUS DADOS
EC2_HOST="seu-ip-ec2"
EC2_USER="ubuntu"
KEY_FILE="sua-chave.pem"
APP_DIR="/home/ubuntu/telegram-news"

# Cores
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}1. Conectando ao EC2...${NC}"

ssh -i "$KEY_FILE" "$EC2_USER@$EC2_HOST" << 'REMOTE'
    set -e
    
    echo "📦 Atualizando sistema..."
    sudo apt update && sudo apt upgrade -y
    
    echo "🐍 Instalando Python e dependências..."
    sudo apt install -y python3 python3-pip python3-venv git postgresql postgresql-contrib
    
    echo "📁 Clonando/atualizando repositório..."
    if [ -d "/home/ubuntu/telegram-news" ]; then
        cd /home/ubuntu/telegram-news
        git pull origin master
    else
        cd /home/ubuntu
        git clone https://github.com/felipemourabsbcripto/telegram-news.git
        cd telegram-news
    fi
    
    echo "🔧 Criando ambiente virtual..."
    python3 -m venv venv
    source venv/bin/activate
    
    echo "📦 Instalando dependências Python..."
    pip install --upgrade pip
    pip install -r requirements.txt
    pip install psycopg2-binary deep-translator
    
    echo "🗄️ Configurando PostgreSQL..."
    sudo -u postgres psql -c "CREATE DATABASE news_db;" 2>/dev/null || echo "DB já existe"
    sudo -u postgres psql -c "CREATE USER botuser WITH PASSWORD 'botpassword';" 2>/dev/null || echo "User já existe"
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE news_db TO botuser;"
    
    echo "✅ Setup concluído!"
REMOTE

echo -e "${GREEN}✅ Deploy finalizado!${NC}"
echo ""
echo "Próximos passos:"
echo "1. Conecte ao EC2: ssh -i $KEY_FILE $EC2_USER@$EC2_HOST"
echo "2. Configure o .env com suas credenciais"
echo "3. Inicie o bot: cd telegram-news && source venv/bin/activate && python3 admin_bot.py"
