#!/usr/bin/env python3
"""
🤖 Telegram News Bot - Admin Panel
Bot com painel de configuração via teclado inline
"""

import os
import sys
import json
import time
import logging
import hashlib
import threading
from datetime import datetime, timedelta
from typing import Optional
import requests
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Text, DateTime
from sqlalchemy.orm import Session, declarative_base
from telegram_news.template import InfoExtractor, NewsPostman

# ============================================================
# 🔧 CONFIGURAÇÕES
# ============================================================
TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID") or os.getenv("TELEGRAM_CHANNEL")
ADMIN_ID = os.getenv("ADMIN_ID")  # Seu ID de usuário (para restringir acesso)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:password@localhost:5432/news_db")

# Groq AI (gratuito e rápido!) - Configure sua chave em GROQ_API_KEY
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# OpenAI para resumos com IA (opcional, fallback)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ============================================================
# Logging
# ============================================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================
# Database Models
# ============================================================
Base = declarative_base()

class BotConfig(Base):
    __tablename__ = 'bot_config'
    id = Column(Integer, primary_key=True)
    key = Column(String(100), unique=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow)

class ScheduledPost(Base):
    __tablename__ = 'scheduled_posts'
    id = Column(Integer, primary_key=True)
    hour = Column(Integer)  # 0-23
    minute = Column(Integer, default=0)
    theme = Column(String(50))  # news, analysis, whale, etc.
    max_posts = Column(Integer, default=5)
    enabled = Column(Boolean, default=True)

class PostAnalytics(Base):
    """Rastreia métricas de cada post enviado."""
    __tablename__ = 'post_analytics'
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer)
    source = Column(String(100))
    title = Column(Text)
    link = Column(Text)
    theme = Column(String(50))
    posted_at = Column(DateTime, default=datetime.utcnow)
    views = Column(Integer, default=0)
    forwards = Column(Integer, default=0)
    reactions = Column(Integer, default=0)
    clicks = Column(Integer, default=0)  # Estimado via encurtador
    last_updated = Column(DateTime, default=datetime.utcnow)

class CryptoEvent(Base):
    """Eventos cripto - conferências, discursos, lançamentos."""
    __tablename__ = 'crypto_events'
    id = Column(Integer, primary_key=True)
    title = Column(String(500))
    description = Column(Text)
    date_event = Column(DateTime)
    end_date = Column(DateTime, nullable=True)
    category = Column(String(100))  # conference, speech, launch, update, airdrop, ama
    coin = Column(String(50), nullable=True)  # BTC, ETH, etc
    source = Column(String(100))  # coinmarketcal, manual, scraped
    source_url = Column(Text, nullable=True)
    location = Column(String(200), nullable=True)  # Virtual, Miami, Dubai, etc
    importance = Column(Integer, default=5)  # 1-10
    alert_sent = Column(Boolean, default=False)
    alert_1day_sent = Column(Boolean, default=False)
    alert_1hour_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    external_id = Column(String(100), nullable=True)  # ID externo para evitar duplicatas

# ============================================================
# Default Configuration
# ============================================================
DEFAULT_CONFIG = {
    # Fontes ativas
    "sources_enabled": {
        "coindesk": True,
        "cointelegraph": True,
        "decrypt": True,
        "bitcoinmagazine": True,
        "cryptoslate": True,
        "utoday": True,
        "portaldobitcoin": True,
        "cointelegraphbr": True,
        "criptofacil": True,
        "whaletracker": False,  # Whale Alert
        "lookonchain": False,   # On-chain
    },
    # Formato
    "format": {
        "show_link": True,
        "show_image": True,
        "show_video": False,
        "translate": True,
        "summarize": False,  # Resumir com IA
        "filter_relevance": False,  # Filtrar por relevância (IA)
        "add_emoji": False,  # Adicionar emojis com IA
        "min_relevance_score": 5,  # Nota mínima para postar
        "style": "complete",  # complete, summary, title_only
    },
    # Temas ativos
    "themes": {
        "news": True,
        "analysis": True,
        "onchain": False,
        "whale": False,
        "liquidation": False,
        "exchange": False,
    },
    # Idioma
    "language": "pt",
    # Intervalo entre ciclos (segundos)
    "cycle_interval": 300,
}

# ============================================================
# Telegram API Helper
# ============================================================
class TelegramAPI:
    def __init__(self, token):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, chat_id, text, reply_markup=None, parse_mode="HTML"):
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        return requests.post(f"{self.base_url}/sendMessage", data=data)
    
    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        return requests.post(f"{self.base_url}/editMessageText", data=data)
    
    def answer_callback(self, callback_id, text=""):
        return requests.post(f"{self.base_url}/answerCallbackQuery", {
            "callback_query_id": callback_id,
            "text": text
        })
    
    def get_updates(self, offset=None, timeout=30):
        params = {"timeout": timeout}
        if offset:
            params["offset"] = offset
        try:
            r = requests.get(f"{self.base_url}/getUpdates", params=params, timeout=timeout+5)
            return r.json().get("result", [])
        except:
            return []

# ============================================================
# Keyboard Builders
# ============================================================
def build_main_menu():
    return {
        "inline_keyboard": [
            [{"text": "📰 Fontes", "callback_data": "menu_sources"}],
            [{"text": "📅 Calendário Cripto", "callback_data": "menu_calendar"}],
            [{"text": "⏰ Horários", "callback_data": "menu_schedule"}],
            [{"text": "📝 Formato", "callback_data": "menu_format"}],
            [{"text": "🏷️ Temas", "callback_data": "menu_themes"}],
            [{"text": "🤖 IA (Groq)", "callback_data": "menu_ai"}],
            [{"text": "📊 Analytics", "callback_data": "menu_analytics"}],
            [{"text": "▶️ Status", "callback_data": "menu_status"}],
        ]
    }

def build_sources_menu(config):
    sources = config.get("sources_enabled", {})
    buttons = []
    for source, enabled in sources.items():
        icon = "✅" if enabled else "❌"
        buttons.append([
            {"text": f"{icon} {source.title()}", "callback_data": f"toggle_source_{source}"},
            {"text": "🗑️", "callback_data": f"delete_source_{source}"}
        ])
    buttons.append([{"text": "➕ Adicionar Fonte", "callback_data": "add_source"}])
    buttons.append([{"text": "📋 Fontes Populares", "callback_data": "popular_sources"}])
    buttons.append([{"text": "⬅️ Voltar", "callback_data": "menu_main"}])
    return {"inline_keyboard": buttons}

def build_popular_sources_menu():
    """Menu com fontes populares pré-configuradas para adicionar."""
    return {
        "inline_keyboard": [
            [{"text": "━━━ 🌍 Internacionais ━━━", "callback_data": "noop"}],
            [{"text": "🐋 Whale Alert", "callback_data": "quick_add_whalealert"},
             {"text": "📊 Glassnode", "callback_data": "quick_add_glassnode"}],
            [{"text": "💹 TradingView", "callback_data": "quick_add_tradingview"},
             {"text": "📰 The Block", "callback_data": "quick_add_theblock"}],
            [{"text": "🏦 Binance Blog", "callback_data": "quick_add_binance_blog"},
             {"text": "📢 Binance News", "callback_data": "quick_add_binance_news"}],
            [{"text": "🌐 BeInCrypto", "callback_data": "quick_add_beincrypto"},
             {"text": "📈 Blockworks", "callback_data": "quick_add_blockworks"}],
            [{"text": "💎 Messari", "callback_data": "quick_add_messari"},
             {"text": "🦊 The Defiant", "callback_data": "quick_add_defiant"}],
            [{"text": "📰 Daily Hodl", "callback_data": "quick_add_dailyhodl"},
             {"text": "🥔 CryptoPotato", "callback_data": "quick_add_cryptopotato"}],
            [{"text": "━━━ 🇧🇷 Brasileiras ━━━", "callback_data": "noop"}],
            [{"text": "🇧🇷 Livecoins", "callback_data": "quick_add_livecoins"},
             {"text": "🇧🇷 CriptoFácil", "callback_data": "quick_add_criptofacil"}],
            [{"text": "🇧🇷 Portal Bitcoin", "callback_data": "quick_add_portaldobitcoin"},
             {"text": "🇧🇷 CoinTelegraph BR", "callback_data": "quick_add_cointelegraph_br"}],
            [{"text": "🇧🇷 BeInCrypto BR", "callback_data": "quick_add_beincrypto_br"},
             {"text": "🇧🇷 InfoMoney", "callback_data": "quick_add_infomoney"}],
            [{"text": "🇧🇷 Exame Cripto", "callback_data": "quick_add_exame_future"},
             {"text": "🇧🇷 Money Times", "callback_data": "quick_add_moneytimes"}],
            [{"text": "━━━ 🏦 Exchanges ━━━", "callback_data": "noop"}],
            [{"text": "🔶 Coinbase", "callback_data": "quick_add_coinbase_blog"},
             {"text": "🐙 Kraken", "callback_data": "quick_add_kraken_blog"}],
            [{"text": "🇧🇷 Mercado Bitcoin", "callback_data": "quick_add_mercadobitcoin"}],
            [{"text": "⬅️ Voltar", "callback_data": "menu_sources"}],
        ]
    }

# Fontes populares pré-configuradas - Expandido com todas as melhores fontes
POPULAR_SOURCES = {
    # === 1. Notícias e Atualizações em Tempo Real ===
    "coindesk_pt": ("CoinDesk BR", "https://www.coindesk.com.br/", "div.article-card a, h3 a", "h1", "div.at-text, div.content, article"),
    "binance_square": ("Binance Square", "https://www.binance.com/en/square", "div.css-1wr4jig a, article a", "h1", "div.content, article"),
    "binance_news": ("Binance News", "https://www.binance.com/en/news", "a.css-1ej4hfo", "h1", "div.css-1wr4jig"),
    "livecoins": ("Livecoins BR", "https://livecoins.com.br/", "h2.entry-title a, h3 a", "h1.entry-title", "div.entry-content"),
    "infomoney": ("InfoMoney Cripto", "https://www.infomoney.com.br/tudo-sobre/criptomoedas/", "a.hl-title, h2 a", "h1", "div.article-content, div.im-article-body"),
    "ccnbrasil": ("CCN Brasil", "https://www.ccn.com/pt/", "h3 a, article a", "h1", "div.entry-content, article"),
    
    # === Fontes Internacionais Top ===
    "whalealert": ("Whale Alert", "https://whale-alert.io/", "div.transaction-item a", "h1", "div.content"),
    "glassnode": ("Glassnode Insights", "https://insights.glassnode.com/", "article a, div.post-item a", "h1", "div.post-content"),
    "tradingview": ("TradingView News", "https://www.tradingview.com/news/", "div.news-item a", "h1", "div.body"),
    "binance_blog": ("Binance Blog", "https://www.binance.com/en/blog", "a.article-item", "h1", "div.article-content"),
    "beincrypto": ("BeInCrypto", "https://beincrypto.com/", "article a, h3 a", "h1", "div.entry-content"),
    "beincrypto_br": ("BeInCrypto BR", "https://br.beincrypto.com/", "article a, h3 a", "h1", "div.entry-content"),
    "theblock": ("The Block", "https://www.theblock.co/", "a.title, h3 a", "h1", "div.article-content"),
    "blockworks": ("Blockworks", "https://blockworks.co/news", "article a, h3 a", "h1", "div.article-body"),
    "coinpedia": ("CoinPedia", "https://coinpedia.org/news/", "h2 a, h3 a", "h1", "div.entry-content"),
    "ambcrypto": ("AMBCrypto", "https://ambcrypto.com/", "h2 a, h3 a", "h1", "div.entry-content"),
    "newsbtc": ("NewsBTC", "https://www.newsbtc.com/", "h2 a, h3 a", "h1", "div.entry-content"),
    "dailyhodl": ("Daily Hodl", "https://dailyhodl.com/", "h2 a, h3 a", "h1", "div.entry-content"),
    "cryptopotato": ("CryptoPotato", "https://cryptopotato.com/", "h3 a, article a", "h1", "div.entry-content"),
    "coingape": ("CoinGape", "https://coingape.com/", "h2 a, h3 a", "h1", "div.entry-content"),
    "bitcoinist": ("Bitcoinist", "https://bitcoinist.com/", "h2 a, h3 a", "h1", "div.entry-content"),
    "cryptobriefing": ("Crypto Briefing", "https://cryptobriefing.com/", "h2 a, h3 a", "h1", "div.entry-content"),
    "messari": ("Messari", "https://messari.io/news", "a.headline, h3 a", "h1", "div.post-body"),
    "defiant": ("The Defiant", "https://thedefiant.io/", "h3 a, article a", "h1", "div.post-content"),
    
    # === Fontes Brasileiras ===
    "portaldobitcoin": ("Portal do Bitcoin", "https://portaldobitcoin.uol.com.br/", "h3 a, div.post-title a", "h1", "div.entry-content"),
    "criptofacil": ("CriptoFácil", "https://www.criptofacil.com/", "div.posts-layout article a", "h1", "div.entry-content"),
    "cointelegraph_br": ("CoinTelegraph BR", "https://br.cointelegraph.com/", "li.posts-listing__item a", "h1", "div.post-content"),
    "moneytimes": ("Money Times Cripto", "https://www.moneytimes.com.br/criptomoedas/", "h2 a, h3 a", "h1", "div.content"),
    "exame_future": ("Exame Future of Money", "https://exame.com/future-of-money/", "h2 a, h3 a", "h1", "div.article-body"),
    "btcbrasil": ("BTC Brasil", "https://www.btcbrasil.com.br/", "h2 a, h3 a", "h1", "div.entry-content"),
    
    # === Exchanges e Dados ===
    "coinbase_blog": ("Coinbase Blog", "https://www.coinbase.com/blog", "h3 a, article a", "h1", "div.content"),
    "kraken_blog": ("Kraken Blog", "https://blog.kraken.com/", "h2 a, article a", "h1", "div.post-content"),
    "mercadobitcoin": ("Mercado Bitcoin", "https://blog.mercadobitcoin.com.br/", "h2 a, h3 a", "h1", "div.post-content"),
}

def build_format_menu(config):
    fmt = config.get("format", {})
    return {
        "inline_keyboard": [
            [{"text": f"{'✅' if fmt.get('show_link') else '❌'} Mostrar Link", "callback_data": "toggle_format_show_link"}],
            [{"text": f"{'✅' if fmt.get('show_image') else '❌'} Mostrar Imagem", "callback_data": "toggle_format_show_image"}],
            [{"text": f"{'✅' if fmt.get('show_video') else '❌'} Mostrar Vídeo", "callback_data": "toggle_format_show_video"}],
            [{"text": f"{'✅' if fmt.get('translate') else '❌'} Traduzir", "callback_data": "toggle_format_translate"}],
            [{"text": f"{'✅' if fmt.get('summarize') else '❌'} Resumir com IA", "callback_data": "toggle_format_summarize"}],
            [
                {"text": "📄 Completo" if fmt.get('style') == 'complete' else "Completo", "callback_data": "set_style_complete"},
                {"text": "📋 Resumido" if fmt.get('style') == 'summary' else "Resumido", "callback_data": "set_style_summary"},
                {"text": "📌 Só Título" if fmt.get('style') == 'title_only' else "Só Título", "callback_data": "set_style_title_only"},
            ],
            [{"text": "⬅️ Voltar", "callback_data": "menu_main"}],
        ]
    }

def build_themes_menu(config):
    themes = config.get("themes", {})
    theme_labels = {
        "news": "📰 Notícias",
        "analysis": "📊 Análises",
        "onchain": "🔗 On-Chain",
        "whale": "🐋 Baleias",
        "liquidation": "💥 Liquidações",
        "exchange": "🏦 Exchange",
    }
    buttons = []
    for theme, enabled in themes.items():
        icon = "✅" if enabled else "❌"
        label = theme_labels.get(theme, theme.title())
        buttons.append([{"text": f"{icon} {label}", "callback_data": f"toggle_theme_{theme}"}])
    buttons.append([{"text": "⬅️ Voltar", "callback_data": "menu_main"}])
    return {"inline_keyboard": buttons}

def build_schedule_menu(schedules):
    buttons = []
    for s in schedules:
        icon = "✅" if s.enabled else "❌"
        buttons.append([{"text": f"{icon} {s.hour:02d}:{s.minute:02d} - {s.theme} ({s.max_posts} posts)", 
                        "callback_data": f"toggle_schedule_{s.id}"}])
    buttons.append([{"text": "➕ Adicionar Horário", "callback_data": "add_schedule"}])
    buttons.append([{"text": "⬅️ Voltar", "callback_data": "menu_main"}])
    return {"inline_keyboard": buttons}

def build_calendar_menu():
    """Menu do calendário de eventos cripto."""
    return {
        "inline_keyboard": [
            [{"text": "📅 Eventos Hoje", "callback_data": "calendar_today"}],
            [{"text": "📆 Próximos 7 Dias", "callback_data": "calendar_week"}],
            [{"text": "🗓️ Próximos 30 Dias", "callback_data": "calendar_month"}],
            [{"text": "🎤 Discursos Importantes", "callback_data": "calendar_speeches"}],
            [{"text": "🎪 Conferências 2026", "callback_data": "calendar_conferences"}],
            [{"text": "🚀 Lançamentos & Updates", "callback_data": "calendar_launches"}],
            [{"text": "━━━ ⚙️ Configurar ━━━", "callback_data": "noop"}],
            [{"text": "🔔 Config Alertas", "callback_data": "calendar_alerts_config"}],
            [{"text": "➕ Adicionar Evento", "callback_data": "calendar_add"}],
            [{"text": "🔄 Atualizar Eventos", "callback_data": "calendar_refresh"}],
            [{"text": "⬅️ Voltar", "callback_data": "menu_main"}],
        ]
    }

def build_calendar_alerts_menu(config):
    """Menu de configuração de alertas do calendário."""
    cal_config = config.get("calendar", {})
    return {
        "inline_keyboard": [
            [{"text": f"{'✅' if cal_config.get('alerts_enabled', True) else '❌'} Alertas Ativos", "callback_data": "toggle_cal_alerts"}],
            [{"text": f"{'✅' if cal_config.get('alert_1day', True) else '❌'} Alerta 1 Dia Antes", "callback_data": "toggle_cal_1day"}],
            [{"text": f"{'✅' if cal_config.get('alert_1hour', True) else '❌'} Alerta 1 Hora Antes", "callback_data": "toggle_cal_1hour"}],
            [{"text": f"{'✅' if cal_config.get('alert_conferences', True) else '❌'} Alertar Conferências", "callback_data": "toggle_cal_conferences"}],
            [{"text": f"{'✅' if cal_config.get('alert_speeches', True) else '❌'} Alertar Discursos", "callback_data": "toggle_cal_speeches"}],
            [{"text": f"{'✅' if cal_config.get('alert_launches', True) else '❌'} Alertar Lançamentos", "callback_data": "toggle_cal_launches"}],
            [{"text": "⬅️ Voltar", "callback_data": "menu_calendar"}],
        ]
    }

def build_ai_menu(config):
    fmt = config.get("format", {})
    return {
        "inline_keyboard": [
            [{"text": f"{'✅' if fmt.get('summarize') else '❌'} Resumir com IA", "callback_data": "toggle_format_summarize"}],
            [{"text": f"{'✅' if fmt.get('filter_relevance') else '❌'} Filtrar Relevância", "callback_data": "toggle_format_filter_relevance"}],
            [{"text": f"{'✅' if fmt.get('add_emoji') else '❌'} Adicionar Emojis", "callback_data": "toggle_format_add_emoji"}],
            [{"text": "🔑 Config Groq API Key", "callback_data": "set_groq_key"}],
            [{"text": "⬅️ Voltar", "callback_data": "menu_main"}],
        ]
    }

def build_analytics_menu():
    return {
        "inline_keyboard": [
            [{"text": "📈 Relatório Hoje", "callback_data": "analytics_today"}],
            [{"text": "📊 Relatório Semanal", "callback_data": "analytics_week"}],
            [{"text": "🏆 Top 10 Posts", "callback_data": "analytics_top"}],
            [{"text": "📰 Por Fonte", "callback_data": "analytics_sources"}],
            [{"text": "🏷️ Por Tema", "callback_data": "analytics_themes"}],
            [{"text": "🔄 Atualizar Métricas", "callback_data": "analytics_refresh"}],
            [{"text": "⬅️ Voltar", "callback_data": "menu_main"}],
        ]
    }

# ============================================================
# Config Manager
# ============================================================
class ConfigManager:
    def __init__(self, db_session):
        self.db = db_session
        self._cache = None
    
    def get_config(self):
        if self._cache:
            return self._cache
        try:
            row = self.db.query(BotConfig).filter_by(key="main_config").first()
            if row:
                self._cache = json.loads(row.value)
                return self._cache
        except:
            pass
        self._cache = DEFAULT_CONFIG.copy()
        return self._cache
    
    def save_config(self, config):
        self._cache = config
        try:
            row = self.db.query(BotConfig).filter_by(key="main_config").first()
            if row:
                row.value = json.dumps(config)
                row.updated_at = datetime.utcnow()
            else:
                row = BotConfig(key="main_config", value=json.dumps(config))
                self.db.add(row)
            self.db.commit()
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            self.db.rollback()
    
    def toggle(self, section, key):
        config = self.get_config()
        if section in config and key in config[section]:
            config[section][key] = not config[section][key]
            self.save_config(config)
        return config
    
    def set_value(self, section, key, value):
        config = self.get_config()
        if section in config:
            config[section][key] = value
            self.save_config(config)
        return config

# ============================================================
# AI - Groq (Llama 3.1 - Gratuito e Rápido!)
# ============================================================
def call_groq_ai(prompt, system_prompt="Você é um assistente especializado em criptomoedas.", max_tokens=300):
    """Chama a API do Groq (gratuita e muito rápida)."""
    api_key = GROQ_API_KEY
    if not api_key:
        return None
    
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3
            },
            timeout=30
        )
        result = response.json()
        if "choices" in result:
            return result["choices"][0]["message"]["content"].strip()
        logger.error(f"Groq error: {result}")
        return None
    except Exception as e:
        logger.error(f"Groq API error: {e}")
        return None

def filter_news_relevance(title, content):
    """Usa IA para determinar se a notícia é relevante (nota 1-10)."""
    prompt = f"""Analise esta notícia de criptomoedas e dê uma nota de 1 a 10 para relevância.
Considere: impacto no mercado, novidade, interesse do público brasileiro.

Título: {title}
Conteúdo: {content[:500]}

Responda APENAS com o número da nota (1-10):"""
    
    result = call_groq_ai(prompt, max_tokens=10)
    try:
        score = int(result.strip().split()[0])
        return min(max(score, 1), 10)
    except:
        return 5  # Default

def summarize_with_ai(text, max_length=200):
    """Usa Groq para resumir o texto."""
    if not GROQ_API_KEY and not OPENAI_API_KEY:
        return text[:max_length] + "..." if len(text) > max_length else text
    
    prompt = f"Resuma esta notícia de criptomoedas em português, em no máximo 2 frases concisas e informativas:\n\n{text[:2000]}"
    
    # Tenta Groq primeiro (mais rápido e grátis)
    result = call_groq_ai(prompt)
    if result:
        return result
    
    # Fallback para OpenAI
    if OPENAI_API_KEY:
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-3.5-turbo",
                    "messages": [
                        {"role": "system", "content": "Você é um assistente que resume notícias de criptomoedas em português."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": 150,
                    "temperature": 0.5
                },
                timeout=30
            )
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"OpenAI error: {e}")
    
    return text[:max_length] + "..." if len(text) > max_length else text

def add_emojis_to_title(title):
    """Adiciona emojis relevantes ao título usando IA."""
    prompt = f"""Adicione 1-2 emojis relevantes ao INÍCIO deste título de notícia cripto. 
Retorne APENAS o título com os emojis, nada mais.

Título: {title}"""
    
    result = call_groq_ai(prompt, max_tokens=100)
    if result:
        return result
    return title

def classify_news_theme(title, content):
    """Classifica o tema da notícia."""
    prompt = f"""Classifique esta notícia em UMA das categorias:
- news (notícia geral)
- analysis (análise de mercado/preço)
- onchain (dados on-chain, métricas)
- whale (movimentação de baleias)
- liquidation (liquidações)
- exchange (notícias de exchanges)
- regulation (regulamentação)
- defi (DeFi, yield)
- nft (NFTs, metaverso)

Título: {title}
Conteúdo: {content[:300]}

Responda APENAS com a categoria:"""
    
    result = call_groq_ai(prompt, max_tokens=20)
    if result:
        theme = result.strip().lower().split()[0]
        valid_themes = ["news", "analysis", "onchain", "whale", "liquidation", "exchange", "regulation", "defi", "nft"]
        if theme in valid_themes:
            return theme
    return "news"

# ============================================================
# Calendário de Eventos Cripto
# ============================================================

# Eventos importantes de 2026 (pré-carregados) - Com links oficiais
CRYPTO_EVENTS_2026 = [
    # Conferências Principais
    {"title": "ETHDenver 2026", "date": "2026-02-24", "end": "2026-03-02", "category": "conference", "location": "Denver, EUA", "importance": 9, "url": "https://www.ethdenver.com/"},
    {"title": "Bitcoin 2026 Conference", "date": "2026-05-15", "end": "2026-05-17", "category": "conference", "location": "Nashville, EUA", "importance": 10, "url": "https://b.tc/conference"},
    {"title": "Consensus 2026 (CoinDesk)", "date": "2026-05-26", "end": "2026-05-28", "category": "conference", "location": "Miami, EUA", "importance": 10, "url": "https://consensus.coindesk.com/"},
    {"title": "Web Summit Rio 2026", "date": "2026-06-15", "end": "2026-06-18", "category": "conference", "location": "Rio de Janeiro, Brasil", "importance": 8, "url": "https://rio.websummit.com/"},
    {"title": "Paris Blockchain Week 2026", "date": "2026-04-07", "end": "2026-04-11", "category": "conference", "location": "Paris, França", "importance": 9, "url": "https://www.parisblockchainweek.com/"},
    {"title": "Token2049 Singapore", "date": "2026-09-14", "end": "2026-09-15", "category": "conference", "location": "Singapura", "importance": 9, "url": "https://www.token2049.com/"},
    {"title": "Token2049 Dubai", "date": "2026-04-28", "end": "2026-04-29", "category": "conference", "location": "Dubai, UAE", "importance": 9, "url": "https://www.token2049.com/"},
    {"title": "Blockchain Rio 2026", "date": "2026-08-10", "end": "2026-08-12", "category": "conference", "location": "Rio de Janeiro, Brasil", "importance": 8, "url": "https://www.blockchainrio.com.br/"},
    {"title": "Gramado Summit 2026", "date": "2026-09-20", "end": "2026-09-22", "category": "conference", "location": "Gramado, Brasil", "importance": 7, "url": "https://gramadosummit.com/"},
    {"title": "Blockchain Life 2026", "date": "2026-12-08", "end": "2026-12-10", "category": "conference", "location": "Dubai, UAE", "importance": 9, "url": "https://blockchain-life.com/"},
    {"title": "Consensus Hong Kong 2026", "date": "2026-11-10", "end": "2026-11-12", "category": "conference", "location": "Hong Kong", "importance": 9, "url": "https://consensus-hongkong.coindesk.com/"},
    {"title": "NFT.NYC 2026", "date": "2026-04-15", "end": "2026-04-17", "category": "conference", "location": "New York, EUA", "importance": 8, "url": "https://www.nft.nyc/"},
    {"title": "Devcon 2026", "date": "2026-10-20", "end": "2026-10-23", "category": "conference", "location": "TBA", "importance": 10, "url": "https://devcon.org/"},
    
    # Discursos e Reuniões Econômicas Importantes
    {"title": "FOMC Meeting - Fed (Janeiro)", "date": "2026-01-28", "category": "speech", "location": "Washington, EUA", "importance": 10, "coin": "BTC", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"title": "FOMC Meeting - Fed (Março)", "date": "2026-03-18", "category": "speech", "location": "Washington, EUA", "importance": 10, "coin": "BTC", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"title": "FOMC Meeting - Fed (Maio)", "date": "2026-05-06", "category": "speech", "location": "Washington, EUA", "importance": 10, "coin": "BTC", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"title": "FOMC Meeting - Fed (Junho)", "date": "2026-06-17", "category": "speech", "location": "Washington, EUA", "importance": 10, "coin": "BTC", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"title": "FOMC Meeting - Fed (Julho)", "date": "2026-07-29", "category": "speech", "location": "Washington, EUA", "importance": 10, "coin": "BTC", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"title": "FOMC Meeting - Fed (Setembro)", "date": "2026-09-16", "category": "speech", "location": "Washington, EUA", "importance": 10, "coin": "BTC", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"title": "FOMC Meeting - Fed (Novembro)", "date": "2026-11-04", "category": "speech", "location": "Washington, EUA", "importance": 10, "coin": "BTC", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"title": "FOMC Meeting - Fed (Dezembro)", "date": "2026-12-16", "category": "speech", "location": "Washington, EUA", "importance": 10, "coin": "BTC", "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"},
    {"title": "Jackson Hole Symposium", "date": "2026-08-27", "end": "2026-08-29", "category": "speech", "location": "Wyoming, EUA", "importance": 10, "coin": "BTC", "url": "https://www.kansascityfed.org/research/jackson-hole-economic-symposium/"},
    {"title": "World Economic Forum Davos", "date": "2026-01-19", "end": "2026-01-23", "category": "speech", "location": "Davos, Suíça", "importance": 9, "url": "https://www.weforum.org/events/world-economic-forum-annual-meeting-2026/"},
    {"title": "G20 Summit 2026", "date": "2026-11-21", "end": "2026-11-22", "category": "speech", "location": "África do Sul", "importance": 9, "url": "https://www.g20.org/"},
    
    # Updates e Lançamentos Esperados
    {"title": "Ethereum Pectra Upgrade", "date": "2026-03-15", "category": "launch", "coin": "ETH", "importance": 10, "url": "https://ethereum.org/en/roadmap/"},
    {"title": "Bitcoin Halving Cycle Analysis", "date": "2026-04-15", "category": "launch", "coin": "BTC", "importance": 8, "url": "https://www.bitcoinblockhalf.com/"},
]

def scrape_coinmarketcal_events():
    """Scrape eventos do CoinMarketCal (principal calendário cripto)."""
    events = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        # CoinMarketCal API pública limitada - usar scraping básico
        url = "https://coinmarketcal.com/en/"
        response = requests.get(url, headers=headers, timeout=15)
        
        if response.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Buscar cards de eventos
            event_cards = soup.select("article.card, div.event-card")[:20]
            
            for card in event_cards:
                try:
                    title_el = card.select_one("h4, h5, .card-title")
                    date_el = card.select_one(".date, .card-date, time")
                    coin_el = card.select_one(".coin-name, .card-coin")
                    
                    if title_el:
                        title = title_el.get_text(strip=True)
                        date_str = date_el.get_text(strip=True) if date_el else ""
                        coin = coin_el.get_text(strip=True) if coin_el else ""
                        
                        events.append({
                            "title": title,
                            "date_str": date_str,
                            "coin": coin,
                            "category": "launch",
                            "source": "coinmarketcal"
                        })
                except:
                    continue
                    
    except Exception as e:
        logger.error(f"Error scraping CoinMarketCal: {e}")
    
    return events

def scrape_crypto_speeches():
    """Busca discursos e falas importantes sobre cripto."""
    speeches = []
    
    # Federal Reserve Calendar
    try:
        url = "https://www.federalreserve.gov/newsevents/calendar.htm"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            events = soup.select("div.event-item, tr.fomc-meeting")[:10]
            for event in events:
                title = event.get_text(strip=True)[:200]
                if any(kw in title.lower() for kw in ["fomc", "powell", "fed", "rate"]):
                    speeches.append({
                        "title": f"🏦 Fed: {title}",
                        "category": "speech",
                        "source": "fed",
                        "importance": 10
                    })
    except Exception as e:
        logger.debug(f"Error scraping Fed: {e}")
    
    return speeches

def fetch_and_save_events(db_session):
    """Busca eventos de várias fontes e salva no banco."""
    saved = 0
    
    # 1. Carregar eventos pré-definidos de 2026
    for event_data in CRYPTO_EVENTS_2026:
        try:
            # Verificar se já existe
            existing = db_session.query(CryptoEvent).filter(
                CryptoEvent.title == event_data["title"],
                CryptoEvent.date_event == datetime.strptime(event_data["date"], "%Y-%m-%d")
            ).first()
            
            if not existing:
                event = CryptoEvent(
                    title=event_data["title"],
                    date_event=datetime.strptime(event_data["date"], "%Y-%m-%d"),
                    end_date=datetime.strptime(event_data.get("end", event_data["date"]), "%Y-%m-%d") if event_data.get("end") else None,
                    category=event_data.get("category", "conference"),
                    coin=event_data.get("coin"),
                    location=event_data.get("location"),
                    importance=event_data.get("importance", 5),
                    source="manual",
                    source_url=event_data.get("url")  # Salvar URL do evento
                )
                db_session.add(event)
                saved += 1
            else:
                # Atualizar URL se existir e não tiver
                if not existing.source_url and event_data.get("url"):
                    existing.source_url = event_data.get("url")
        except Exception as e:
            logger.error(f"Error saving event: {e}")
            db_session.rollback()
    
    # 2. Scrape CoinMarketCal
    try:
        scraped_events = scrape_coinmarketcal_events()
        for event_data in scraped_events:
            try:
                # Tentar parsear a data
                date_str = event_data.get("date_str", "")
                event_date = None
                for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y", "%d %B %Y"]:
                    try:
                        event_date = datetime.strptime(date_str, fmt)
                        break
                    except:
                        continue
                
                if not event_date:
                    event_date = datetime.utcnow() + timedelta(days=30)  # Default
                
                # Verificar duplicata
                existing = db_session.query(CryptoEvent).filter(
                    CryptoEvent.title == event_data["title"],
                    CryptoEvent.source == "coinmarketcal"
                ).first()
                
                if not existing:
                    event = CryptoEvent(
                        title=event_data["title"],
                        date_event=event_date,
                        category=event_data.get("category", "launch"),
                        coin=event_data.get("coin"),
                        source="coinmarketcal",
                        importance=5
                    )
                    db_session.add(event)
                    saved += 1
            except:
                continue
    except Exception as e:
        logger.error(f"Error processing scraped events: {e}")
    
    try:
        db_session.commit()
    except:
        db_session.rollback()
    
    return saved

def get_events_for_period(db_session, start_date, end_date, category=None):
    """Retorna eventos para um período."""
    query = db_session.query(CryptoEvent).filter(
        CryptoEvent.date_event >= start_date,
        CryptoEvent.date_event <= end_date
    )
    
    if category:
        query = query.filter(CryptoEvent.category == category)
    
    return query.order_by(CryptoEvent.date_event).all()

def format_event_message(event):
    """Formata um evento para mensagem com link."""
    icons = {
        "conference": "🎪",
        "speech": "🎤",
        "launch": "🚀",
        "update": "⬆️",
        "airdrop": "🎁",
        "ama": "💬",
        "halving": "⛏️"
    }
    icon = icons.get(event.category, "📅")
    
    date_str = event.date_event.strftime("%d/%m/%Y")
    if event.end_date and event.end_date != event.date_event:
        date_str += f" - {event.end_date.strftime('%d/%m/%Y')}"
    
    # Título com link se disponível
    if event.source_url:
        msg = f"{icon} <b><a href='{event.source_url}'>{event.title}</a></b>\n"
    else:
        msg = f"{icon} <b>{event.title}</b>\n"
    
    msg += f"📅 {date_str}\n"
    
    if event.location:
        msg += f"📍 {event.location}\n"
    if event.coin:
        msg += f"🪙 {event.coin}\n"
    if event.importance >= 8:
        msg += f"⭐ Importância: {'⭐' * min(event.importance, 10)}\n"
    
    # Link separado para melhor visualização
    if event.source_url:
        msg += f"🔗 <a href='{event.source_url}'>Mais informações</a>\n"
    
    return msg

def send_event_alert(api, channel_id, event, alert_type="upcoming"):
    """Envia alerta de evento para o canal."""
    icons = {
        "conference": "🎪",
        "speech": "🎤",
        "launch": "🚀"
    }
    icon = icons.get(event.category, "📅")
    
    if alert_type == "1day":
        header = "⏰ <b>AMANHÃ!</b>"
    elif alert_type == "1hour":
        header = "🔔 <b>EM 1 HORA!</b>"
    else:
        header = "📅 <b>EVENTO CRIPTO</b>"
    
    date_str = event.date_event.strftime("%d/%m/%Y às %H:%M") if event.date_event.hour else event.date_event.strftime("%d/%m/%Y")
    
    msg = f"""{header}

{icon} <b>{event.title}</b>

📅 Data: {date_str}"""
    
    if event.location:
        msg += f"\n📍 Local: {event.location}"
    if event.coin:
        msg += f"\n🪙 Moeda: {event.coin}"
    if event.description:
        msg += f"\n\n{event.description[:200]}"
    
    importance_stars = "⭐" * min(event.importance, 5)
    msg += f"\n\n{importance_stars} Importância: {event.importance}/10"
    
    if event.source_url:
        msg += f"\n\n🔗 <a href='{event.source_url}'>Mais informações</a>"
    
    try:
        api.send_message(channel_id, msg)
        return True
    except Exception as e:
        logger.error(f"Error sending event alert: {e}")
        return False

def check_and_send_event_alerts(db_session, api, channel_id, config):
    """Verifica e envia alertas de eventos próximos."""
    cal_config = config.get("calendar", {})
    
    if not cal_config.get("alerts_enabled", True):
        return 0
    
    now = datetime.utcnow()
    alerts_sent = 0
    
    # Alerta 1 dia antes
    if cal_config.get("alert_1day", True):
        tomorrow = now + timedelta(days=1)
        events = db_session.query(CryptoEvent).filter(
            CryptoEvent.date_event >= tomorrow.replace(hour=0, minute=0),
            CryptoEvent.date_event <= tomorrow.replace(hour=23, minute=59),
            CryptoEvent.alert_1day_sent == False
        ).all()
        
        for event in events:
            # Verificar filtros de categoria
            if event.category == "conference" and not cal_config.get("alert_conferences", True):
                continue
            if event.category == "speech" and not cal_config.get("alert_speeches", True):
                continue
            if event.category == "launch" and not cal_config.get("alert_launches", True):
                continue
            
            if send_event_alert(api, channel_id, event, "1day"):
                event.alert_1day_sent = True
                alerts_sent += 1
    
    # Alerta 1 hora antes
    if cal_config.get("alert_1hour", True):
        one_hour = now + timedelta(hours=1)
        events = db_session.query(CryptoEvent).filter(
            CryptoEvent.date_event >= now,
            CryptoEvent.date_event <= one_hour,
            CryptoEvent.alert_1hour_sent == False
        ).all()
        
        for event in events:
            if send_event_alert(api, channel_id, event, "1hour"):
                event.alert_1hour_sent = True
                alerts_sent += 1
    
    try:
        db_session.commit()
    except:
        db_session.rollback()
    
    return alerts_sent

# ============================================================
# Translation
# ============================================================
try:
    from deep_translator import GoogleTranslator
    HAS_TRANSLATOR = True
except ImportError:
    HAS_TRANSLATOR = False

def translate_text(text, target='pt'):
    if not HAS_TRANSLATOR or not text:
        return text
    try:
        translator = GoogleTranslator(source='auto', target=target)
        if len(text) > 4000:
            text = text[:4000]
        return translator.translate(text)
    except:
        return text

# ============================================================
# Admin Bot Handler
# ============================================================
class AdminBot:
    def __init__(self, token, db_session):
        self.api = TelegramAPI(token)
        self.config_mgr = ConfigManager(db_session)
        self.db = db_session
        self.running = True
        self.news_thread = None
        self.awaiting_input = {}  # user_id -> (type, context)
    
    def handle_update(self, update):
        if "callback_query" in update:
            self.handle_callback(update["callback_query"])
        elif "message" in update:
            self.handle_message(update["message"])
    
    def handle_message(self, msg):
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "")
        user_id = msg["from"]["id"]
        
        # Check if awaiting input
        if user_id in self.awaiting_input:
            await_type, context = self.awaiting_input.pop(user_id)
            if await_type == "schedule":
                self.process_schedule_input(chat_id, text)
                return
            elif await_type == "openai_key":
                self.process_openai_key(chat_id, text)
                return
            elif await_type == "groq_key":
                self.process_groq_key(chat_id, text)
                return
            elif await_type == "add_source":
                self.process_add_source(chat_id, text)
                return
            elif await_type == "calendar_add":
                self.process_calendar_add(chat_id, text)
                return
        
        if text == "/start" or text == "/config":
            self.show_main_menu(chat_id)
        elif text == "/status":
            self.show_status(chat_id)
        elif text == "/help":
            self.show_help(chat_id)
        elif text == "/calendar" or text == "/eventos":
            self.api.send_message(chat_id,
                "📅 <b>Calendário Cripto 2026</b>\n\n"
                "Acompanhe eventos, conferências e discursos importantes!",
                build_calendar_menu())
    
    def handle_callback(self, callback):
        callback_id = callback["id"]
        data = callback.get("data", "")
        chat_id = callback["message"]["chat"]["id"]
        message_id = callback["message"]["message_id"]
        user_id = callback["from"]["id"]
        
        self.api.answer_callback(callback_id)
        
        config = self.config_mgr.get_config()
        
        # Main menu
        if data == "menu_main":
            self.api.edit_message(chat_id, message_id, 
                "🤖 <b>Painel de Configuração</b>\n\nEscolha uma opção:", 
                build_main_menu())
        
        # Sources menu
        elif data == "menu_sources":
            self.api.edit_message(chat_id, message_id,
                "📰 <b>Fontes de Notícias</b>\n\nAtive/desative as fontes:",
                build_sources_menu(config))
        
        elif data.startswith("toggle_source_"):
            source = data.replace("toggle_source_", "")
            config = self.config_mgr.toggle("sources_enabled", source)
            self.api.edit_message(chat_id, message_id,
                "📰 <b>Fontes de Notícias</b>\n\nAtive/desative ou gerencie as fontes:",
                build_sources_menu(config))
        
        elif data.startswith("delete_source_"):
            source = data.replace("delete_source_", "")
            config = self.config_mgr.get_config()
            if source in config.get("sources_enabled", {}):
                del config["sources_enabled"][source]
                # Remove também da config de seletores se existir
                if "custom_sources" in config and source in config["custom_sources"]:
                    del config["custom_sources"][source]
                self.config_mgr.save_config(config)
            self.api.edit_message(chat_id, message_id,
                f"🗑️ Fonte <b>{source}</b> removida!\n\n📰 <b>Fontes de Notícias</b>:",
                build_sources_menu(config))
        
        elif data == "add_source":
            self.awaiting_input[user_id] = ("add_source", None)
            self.api.send_message(chat_id,
                "➕ <b>Adicionar Nova Fonte</b>\n\n"
                "Envie os dados no formato:\n"
                "<code>nome|url|seletor_lista|seletor_titulo|seletor_conteudo</code>\n\n"
                "<b>Exemplo:</b>\n"
                "<code>MeuSite|https://meusite.com/|h3 a|h1|div.content</code>\n\n"
                "<i>Dica: Use DevTools (F12) no navegador para encontrar seletores CSS.</i>\n\n"
                "Ou envie apenas:\n"
                "<code>nome|url</code>\n"
                "para usar seletores genéricos.")
        
        elif data == "popular_sources":
            self.api.edit_message(chat_id, message_id,
                "📋 <b>Fontes Populares</b>\n\nClique para adicionar rapidamente:",
                build_popular_sources_menu())
        
        elif data.startswith("quick_add_"):
            source_key = data.replace("quick_add_", "")
            if source_key in POPULAR_SOURCES:
                name, url, list_sel, title_sel, content_sel = POPULAR_SOURCES[source_key]
                config = self.config_mgr.get_config()
                config["sources_enabled"][source_key] = True
                if "custom_sources" not in config:
                    config["custom_sources"] = {}
                config["custom_sources"][source_key] = {
                    "name": name,
                    "url": url,
                    "list_selector": list_sel,
                    "title_selector": title_sel,
                    "content_selector": content_sel
                }
                self.config_mgr.save_config(config)
                self.api.edit_message(chat_id, message_id,
                    f"✅ <b>{name}</b> adicionada!\n\n📰 <b>Fontes de Notícias</b>:",
                    build_sources_menu(config))
            else:
                self.api.edit_message(chat_id, message_id,
                    "❌ Fonte não encontrada.",
                    build_popular_sources_menu())
        
        # Format menu
        elif data == "menu_format":
            self.api.edit_message(chat_id, message_id,
                "📝 <b>Formato das Postagens</b>\n\nConfigure como as notícias serão exibidas:",
                build_format_menu(config))
        
        elif data.startswith("toggle_format_"):
            key = data.replace("toggle_format_", "")
            config = self.config_mgr.toggle("format", key)
            self.api.edit_message(chat_id, message_id,
                "📝 <b>Formato das Postagens</b>\n\nConfigure como as notícias serão exibidas:",
                build_format_menu(config))
        
        elif data.startswith("set_style_"):
            style = data.replace("set_style_", "")
            config = self.config_mgr.set_value("format", "style", style)
            self.api.edit_message(chat_id, message_id,
                "📝 <b>Formato das Postagens</b>\n\nConfigure como as notícias serão exibidas:",
                build_format_menu(config))
        
        # Themes menu
        elif data == "menu_themes":
            self.api.edit_message(chat_id, message_id,
                "🏷️ <b>Temas</b>\n\nEscolha os tipos de conteúdo:",
                build_themes_menu(config))
        
        elif data.startswith("toggle_theme_"):
            theme = data.replace("toggle_theme_", "")
            config = self.config_mgr.toggle("themes", theme)
            self.api.edit_message(chat_id, message_id,
                "🏷️ <b>Temas</b>\n\nEscolha os tipos de conteúdo:",
                build_themes_menu(config))
        
        # Schedule menu
        elif data == "menu_schedule":
            schedules = self.db.query(ScheduledPost).all()
            self.api.edit_message(chat_id, message_id,
                "⏰ <b>Horários de Postagem</b>\n\nConfigure quando postar:",
                build_schedule_menu(schedules))
        
        elif data.startswith("toggle_schedule_"):
            sched_id = int(data.replace("toggle_schedule_", ""))
            sched = self.db.query(ScheduledPost).filter_by(id=sched_id).first()
            if sched:
                sched.enabled = not sched.enabled
                self.db.commit()
            schedules = self.db.query(ScheduledPost).all()
            self.api.edit_message(chat_id, message_id,
                "⏰ <b>Horários de Postagem</b>\n\nConfigure quando postar:",
                build_schedule_menu(schedules))
        
        elif data == "add_schedule":
            self.awaiting_input[user_id] = ("schedule", None)
            self.api.send_message(chat_id, 
                "📝 Digite o horário no formato:\n<code>HH:MM tema quantidade</code>\n\n"
                "Exemplo: <code>09:00 news 5</code>\n\n"
                "Temas: news, analysis, onchain, whale, liquidation, exchange")
        
        # AI menu
        elif data == "menu_ai":
            self.api.edit_message(chat_id, message_id,
                "🤖 <b>Inteligência Artificial (Groq)</b>\n\n"
                "Use IA para filtrar, resumir e melhorar notícias.\n"
                f"🔑 Groq API: {'✅ Configurada' if GROQ_API_KEY else '❌ Não configurada'}\n"
                f"🔑 OpenAI: {'✅ Backup' if OPENAI_API_KEY else '❌ Não configurada'}\n\n"
                "<i>Groq é gratuito e usa Llama 3.1 70B!</i>",
                build_ai_menu(config))
        
        elif data == "set_groq_key":
            self.awaiting_input[user_id] = ("groq_key", None)
            self.api.send_message(chat_id,
                "🔑 Envie sua Groq API Key:\n\n"
                "Obtenha grátis em: https://console.groq.com/keys")
        
        elif data.startswith("toggle_format_filter_relevance"):
            config = self.config_mgr.toggle("format", "filter_relevance")
            self.api.edit_message(chat_id, message_id,
                "🤖 <b>Inteligência Artificial (Groq)</b>\n\n"
                "Use IA para filtrar, resumir e melhorar notícias.\n"
                f"🔑 Groq API: {'✅ Configurada' if GROQ_API_KEY else '❌ Não configurada'}",
                build_ai_menu(config))
        
        elif data.startswith("toggle_format_add_emoji"):
            config = self.config_mgr.toggle("format", "add_emoji")
            self.api.edit_message(chat_id, message_id,
                "🤖 <b>Inteligência Artificial (Groq)</b>\n\n"
                "Use IA para filtrar, resumir e melhorar notícias.\n"
                f"🔑 Groq API: {'✅ Configurada' if GROQ_API_KEY else '❌ Não configurada'}",
                build_ai_menu(config))
        
        elif data == "set_openai_key":
            self.awaiting_input[user_id] = ("openai_key", None)
            self.api.send_message(chat_id,
                "🔑 Envie sua OpenAI API Key (backup):")
        
        # Analytics menu
        elif data == "menu_analytics":
            self.api.edit_message(chat_id, message_id,
                "📊 <b>Analytics & Relatórios</b>\n\n"
                "Acompanhe o desempenho das suas postagens:",
                build_analytics_menu())
        
        elif data == "analytics_today":
            self.show_analytics_today(chat_id, message_id)
        
        elif data == "analytics_week":
            self.show_analytics_week(chat_id, message_id)
        
        elif data == "analytics_top":
            self.show_top_posts(chat_id, message_id)
        
        elif data == "analytics_sources":
            data_week = self.get_analytics_week()
            text = "📰 <b>Analytics por Fonte</b>\n\n"
            sorted_sources = sorted(data_week['by_source'].items(), key=lambda x: x[1]['views'], reverse=True)
            for source, stats in sorted_sources:
                avg_views = stats['views'] // stats['posts'] if stats['posts'] > 0 else 0
                text += f"<b>{source}</b>\n"
                text += f"  Posts: {stats['posts']} | Views: {stats['views']} | Média: {avg_views}\n\n"
            if not sorted_sources:
                text += "<i>Sem dados ainda.</i>"
            keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_analytics"}]]}
            self.api.edit_message(chat_id, message_id, text, keyboard)
        
        elif data == "analytics_themes":
            week_ago = datetime.utcnow() - timedelta(days=7)
            posts = self.db.query(PostAnalytics).filter(PostAnalytics.posted_at >= week_ago).all()
            by_theme = {}
            for p in posts:
                theme = p.theme or "news"
                if theme not in by_theme:
                    by_theme[theme] = {"posts": 0, "views": 0}
                by_theme[theme]["posts"] += 1
                by_theme[theme]["views"] += p.views or 0
            
            theme_icons = {"news": "📰", "analysis": "📊", "onchain": "🔗", "whale": "🐋", 
                          "liquidation": "💥", "exchange": "🏦", "regulation": "⚖️", "defi": "🌾", "nft": "🎨"}
            
            text = "🏷️ <b>Analytics por Tema</b>\n\n"
            for theme, stats in sorted(by_theme.items(), key=lambda x: x[1]['views'], reverse=True):
                icon = theme_icons.get(theme, "📄")
                text += f"{icon} <b>{theme.title()}</b>: {stats['posts']} posts, {stats['views']} views\n"
            if not by_theme:
                text += "<i>Sem dados ainda.</i>"
            keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_analytics"}]]}
            self.api.edit_message(chat_id, message_id, text, keyboard)
        
        elif data == "analytics_refresh":
            self.refresh_analytics()
            self.api.edit_message(chat_id, message_id,
                "🔄 Métricas atualizadas!\n\n<i>Nota: O Telegram tem limitações na API de métricas para bots.</i>",
                build_analytics_menu())
        
        # ============================================================
        # Calendar Menu Handlers
        # ============================================================
        elif data == "menu_calendar":
            self.api.edit_message(chat_id, message_id,
                "📅 <b>Calendário Cripto 2026</b>\n\n"
                "Acompanhe eventos, conferências e discursos importantes!",
                build_calendar_menu())
        
        elif data == "calendar_today":
            self.show_calendar_today(chat_id, message_id)
        
        elif data == "calendar_week":
            self.show_calendar_week(chat_id, message_id)
        
        elif data == "calendar_month":
            self.show_calendar_month(chat_id, message_id)
        
        elif data == "calendar_speeches":
            self.show_calendar_speeches(chat_id, message_id)
        
        elif data == "calendar_conferences":
            self.show_calendar_conferences(chat_id, message_id)
        
        elif data == "calendar_launches":
            self.show_calendar_launches(chat_id, message_id)
        
        elif data == "calendar_alerts_config":
            self.api.edit_message(chat_id, message_id,
                "🔔 <b>Configuração de Alertas</b>\n\n"
                "Configure quais alertas deseja receber:",
                build_calendar_alerts_menu(config))
        
        elif data.startswith("toggle_cal_"):
            key = data.replace("toggle_cal_", "")
            config = self.config_mgr.get_config()
            if "calendar" not in config:
                config["calendar"] = {}
            cal_key_map = {
                "alerts": "alerts_enabled",
                "1day": "alert_1day",
                "1hour": "alert_1hour",
                "conferences": "alert_conferences",
                "speeches": "alert_speeches",
                "launches": "alert_launches"
            }
            actual_key = cal_key_map.get(key, key)
            config["calendar"][actual_key] = not config["calendar"].get(actual_key, True)
            self.config_mgr.save_config(config)
            self.api.edit_message(chat_id, message_id,
                "🔔 <b>Configuração de Alertas</b>\n\n"
                "Configure quais alertas deseja receber:",
                build_calendar_alerts_menu(config))
        
        elif data == "calendar_add":
            self.awaiting_input[user_id] = ("calendar_add", None)
            self.api.send_message(chat_id,
                "➕ <b>Adicionar Evento</b>\n\n"
                "Envie no formato:\n"
                "<code>YYYY-MM-DD|Título|categoria|local</code>\n\n"
                "<b>Categorias:</b> conference, speech, launch, update, airdrop\n\n"
                "<b>Exemplo:</b>\n"
                "<code>2026-03-15|ETH Mainnet Update|launch|Virtual</code>")
        
        elif data == "calendar_refresh":
            saved = fetch_and_save_events(self.db)
            self.api.edit_message(chat_id, message_id,
                f"🔄 Eventos atualizados!\n\n"
                f"✅ {saved} novos eventos adicionados.\n\n"
                "Os eventos são carregados de:\n"
                "• CoinMarketCal\n"
                "• Federal Reserve Calendar\n"
                "• Conferências 2026 pré-cadastradas",
                build_calendar_menu())
        
        elif data == "noop":
            pass  # Não faz nada (para separadores)
        
        # Status
        elif data == "menu_status":
            self.show_status(chat_id, message_id)
    
    # ============================================================
    # Calendar Display Methods
    # ============================================================
    def show_calendar_today(self, chat_id, message_id=None):
        """Mostra eventos de hoje."""
        today = datetime.utcnow().date()
        events = get_events_for_period(
            self.db,
            datetime.combine(today, datetime.min.time()),
            datetime.combine(today, datetime.max.time())
        )
        
        text = "📅 <b>Eventos de Hoje</b>\n\n"
        if events:
            for event in events:
                text += format_event_message(event) + "\n"
        else:
            text += "<i>Nenhum evento para hoje.</i>\n"
        
        keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_calendar"}]]}
        
        if message_id:
            self.api.edit_message(chat_id, message_id, text, keyboard)
        else:
            self.api.send_message(chat_id, text, keyboard)
    
    def show_calendar_week(self, chat_id, message_id=None):
        """Mostra eventos dos próximos 7 dias."""
        now = datetime.utcnow()
        events = get_events_for_period(self.db, now, now + timedelta(days=7))
        
        text = "📆 <b>Próximos 7 Dias</b>\n\n"
        if events:
            current_date = None
            for event in events:
                event_date = event.date_event.date()
                if event_date != current_date:
                    current_date = event_date
                    text += f"\n<b>📅 {event_date.strftime('%d/%m (%a)')}</b>\n"
                text += f"  • {event.title}"
                if event.coin:
                    text += f" [{event.coin}]"
                text += "\n"
        else:
            text += "<i>Nenhum evento nos próximos 7 dias.</i>\n"
        
        keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_calendar"}]]}
        
        if message_id:
            self.api.edit_message(chat_id, message_id, text, keyboard)
        else:
            self.api.send_message(chat_id, text, keyboard)
    
    def show_calendar_month(self, chat_id, message_id=None):
        """Mostra eventos dos próximos 30 dias."""
        now = datetime.utcnow()
        events = get_events_for_period(self.db, now, now + timedelta(days=30))
        
        text = "🗓️ <b>Próximos 30 Dias</b>\n\n"
        if events:
            # Agrupar por semana
            for event in events[:15]:  # Limitar para não ficar muito longo
                date_str = event.date_event.strftime("%d/%m")
                icon = {"conference": "🎪", "speech": "🎤", "launch": "🚀"}.get(event.category, "📅")
                text += f"{icon} <b>{date_str}</b> - {event.title[:40]}"
                if len(event.title) > 40:
                    text += "..."
                text += "\n"
            
            if len(events) > 15:
                text += f"\n<i>... e mais {len(events) - 15} eventos</i>"
        else:
            text += "<i>Nenhum evento nos próximos 30 dias.</i>\n"
        
        keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_calendar"}]]}
        
        if message_id:
            self.api.edit_message(chat_id, message_id, text, keyboard)
        else:
            self.api.send_message(chat_id, text, keyboard)
    
    def show_calendar_speeches(self, chat_id, message_id=None):
        """Mostra discursos e falas importantes."""
        now = datetime.utcnow()
        events = get_events_for_period(self.db, now, now + timedelta(days=90), category="speech")
        
        text = "🎤 <b>Discursos & Falas Importantes</b>\n\n"
        text += "<i>Impacto direto no mercado cripto!</i>\n\n"
        
        if events:
            for event in events[:10]:
                date_str = event.date_event.strftime("%d/%m/%Y")
                text += f"🎤 <b>{event.title}</b>\n"
                text += f"   📅 {date_str}"
                if event.location:
                    text += f" | 📍 {event.location}"
                text += "\n\n"
        else:
            text += "<i>Nenhum discurso agendado.</i>\n"
        
        text += "\n⚠️ <b>Dica:</b> Reuniões do FOMC e falas do Fed podem causar alta volatilidade!"
        
        keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_calendar"}]]}
        
        if message_id:
            self.api.edit_message(chat_id, message_id, text, keyboard)
        else:
            self.api.send_message(chat_id, text, keyboard)
    
    def show_calendar_conferences(self, chat_id, message_id=None):
        """Mostra conferências de 2026."""
        now = datetime.utcnow()
        events = get_events_for_period(self.db, now, now + timedelta(days=365), category="conference")
        
        text = "🎪 <b>Conferências Cripto 2026</b>\n\n"
        
        if events:
            for event in events[:12]:
                date_str = event.date_event.strftime("%d/%m")
                if event.end_date:
                    date_str += f"-{event.end_date.strftime('%d/%m')}"
                
                stars = "⭐" * min(event.importance // 2, 5) if event.importance >= 8 else ""
                
                text += f"🎪 <b>{event.title}</b> {stars}\n"
                text += f"   📅 {date_str}"
                if event.location:
                    text += f" | 📍 {event.location}"
                text += "\n\n"
        else:
            text += "<i>Nenhuma conferência cadastrada.</i>\n"
        
        keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_calendar"}]]}
        
        if message_id:
            self.api.edit_message(chat_id, message_id, text, keyboard)
        else:
            self.api.send_message(chat_id, text, keyboard)
    
    def show_calendar_launches(self, chat_id, message_id=None):
        """Mostra lançamentos e updates."""
        now = datetime.utcnow()
        events = get_events_for_period(self.db, now, now + timedelta(days=90), category="launch")
        
        text = "🚀 <b>Lançamentos & Updates</b>\n\n"
        
        if events:
            for event in events[:10]:
                date_str = event.date_event.strftime("%d/%m/%Y")
                text += f"🚀 <b>{event.title}</b>\n"
                text += f"   📅 {date_str}"
                if event.coin:
                    text += f" | 🪙 {event.coin}"
                text += "\n\n"
        else:
            text += "<i>Nenhum lançamento agendado.</i>\n"
        
        keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_calendar"}]]}
        
        if message_id:
            self.api.edit_message(chat_id, message_id, text, keyboard)
        else:
            self.api.send_message(chat_id, text, keyboard)
    
    def process_schedule_input(self, chat_id, text):
        try:
            parts = text.strip().split()
            time_parts = parts[0].split(":")
            hour = int(time_parts[0])
            minute = int(time_parts[1]) if len(time_parts) > 1 else 0
            theme = parts[1] if len(parts) > 1 else "news"
            max_posts = int(parts[2]) if len(parts) > 2 else 5
            
            sched = ScheduledPost(hour=hour, minute=minute, theme=theme, max_posts=max_posts)
            self.db.add(sched)
            self.db.commit()
            
            self.api.send_message(chat_id, f"✅ Horário adicionado: {hour:02d}:{minute:02d} - {theme} ({max_posts} posts)")
        except Exception as e:
            self.api.send_message(chat_id, f"❌ Formato inválido. Use: HH:MM tema quantidade\nErro: {e}")
    
    def process_openai_key(self, chat_id, text):
        global OPENAI_API_KEY
        OPENAI_API_KEY = text.strip()
        self.api.send_message(chat_id, "✅ API Key configurada! O resumo com IA agora está disponível.")
    
    def process_groq_key(self, chat_id, text):
        global GROQ_API_KEY
        GROQ_API_KEY = text.strip()
        # Testar a key
        test = call_groq_ai("Diga 'OK' se funcionou", max_tokens=10)
        if test:
            self.api.send_message(chat_id, "✅ Groq API Key configurada e funcionando!")
        else:
            self.api.send_message(chat_id, "⚠️ Key salva, mas teste falhou. Verifique se está correta.")
    
    def process_add_source(self, chat_id, text):
        """Processa adição de nova fonte."""
        try:
            parts = text.strip().split("|")
            
            if len(parts) < 2:
                self.api.send_message(chat_id, "❌ Formato inválido. Use: nome|url ou nome|url|seletor_lista|seletor_titulo|seletor_conteudo")
                return
            
            name = parts[0].strip()
            url = parts[1].strip()
            
            # Seletores genéricos se não fornecidos
            list_sel = parts[2].strip() if len(parts) > 2 else "h2 a, h3 a, article a"
            title_sel = parts[3].strip() if len(parts) > 3 else "h1"
            content_sel = parts[4].strip() if len(parts) > 4 else "div.content, div.post-content, div.entry-content, article"
            
            # Gerar key única
            source_key = "".join(x for x in name if x.isalnum()).lower()[:20]
            
            # Salvar na config
            config = self.config_mgr.get_config()
            config["sources_enabled"][source_key] = True
            if "custom_sources" not in config:
                config["custom_sources"] = {}
            config["custom_sources"][source_key] = {
                "name": name,
                "url": url,
                "list_selector": list_sel,
                "title_selector": title_sel,
                "content_selector": content_sel
            }
            self.config_mgr.save_config(config)
            
            self.api.send_message(chat_id, 
                f"✅ Fonte <b>{name}</b> adicionada!\n\n"
                f"🔗 URL: {url}\n"
                f"📋 Lista: <code>{list_sel}</code>\n"
                f"📰 Título: <code>{title_sel}</code>\n"
                f"📝 Conteúdo: <code>{content_sel}</code>\n\n"
                "Use /config para gerenciar fontes.",
                build_sources_menu(config))
                
        except Exception as e:
            self.api.send_message(chat_id, f"❌ Erro ao adicionar fonte: {e}")
    
    def process_calendar_add(self, chat_id, text):
        """Processa adição de novo evento ao calendário."""
        try:
            parts = text.strip().split("|")
            
            if len(parts) < 2:
                self.api.send_message(chat_id, "❌ Formato inválido. Use: YYYY-MM-DD|Título|categoria|local")
                return
            
            date_str = parts[0].strip()
            title = parts[1].strip()
            category = parts[2].strip().lower() if len(parts) > 2 else "conference"
            location = parts[3].strip() if len(parts) > 3 else None
            
            # Validar categoria
            valid_categories = ["conference", "speech", "launch", "update", "airdrop", "ama"]
            if category not in valid_categories:
                category = "conference"
            
            # Parsear data
            event_date = datetime.strptime(date_str, "%Y-%m-%d")
            
            # Criar evento
            event = CryptoEvent(
                title=title,
                date_event=event_date,
                category=category,
                location=location,
                source="manual",
                importance=7
            )
            self.db.add(event)
            self.db.commit()
            
            category_icons = {"conference": "🎪", "speech": "🎤", "launch": "🚀", "update": "⬆️", "airdrop": "🎁", "ama": "💬"}
            icon = category_icons.get(category, "📅")
            
            self.api.send_message(chat_id,
                f"✅ Evento adicionado!\n\n"
                f"{icon} <b>{title}</b>\n"
                f"📅 {event_date.strftime('%d/%m/%Y')}\n"
                f"📍 {location or 'Não especificado'}\n"
                f"🏷️ {category.title()}\n\n"
                "Você receberá alertas 1 dia e 1 hora antes!",
                build_calendar_menu())
            
        except ValueError as e:
            self.api.send_message(chat_id, f"❌ Data inválida. Use o formato YYYY-MM-DD (ex: 2026-03-15)\nErro: {e}")
        except Exception as e:
            self.api.send_message(chat_id, f"❌ Erro ao adicionar evento: {e}")
            self.db.rollback()
    
    def get_analytics_today(self):
        """Retorna métricas de hoje."""
        today = datetime.utcnow().date()
        posts = self.db.query(PostAnalytics).filter(
            PostAnalytics.posted_at >= datetime.combine(today, datetime.min.time())
        ).all()
        
        total_posts = len(posts)
        total_views = sum(p.views or 0 for p in posts)
        total_forwards = sum(p.forwards or 0 for p in posts)
        total_reactions = sum(p.reactions or 0 for p in posts)
        
        # Por fonte
        by_source = {}
        for p in posts:
            if p.source not in by_source:
                by_source[p.source] = {"posts": 0, "views": 0}
            by_source[p.source]["posts"] += 1
            by_source[p.source]["views"] += p.views or 0
        
        return {
            "total_posts": total_posts,
            "total_views": total_views,
            "total_forwards": total_forwards,
            "total_reactions": total_reactions,
            "by_source": by_source,
            "posts": posts
        }
    
    def get_analytics_week(self):
        """Retorna métricas da semana."""
        week_ago = datetime.utcnow() - timedelta(days=7)
        posts = self.db.query(PostAnalytics).filter(
            PostAnalytics.posted_at >= week_ago
        ).all()
        
        total_posts = len(posts)
        total_views = sum(p.views or 0 for p in posts)
        total_forwards = sum(p.forwards or 0 for p in posts)
        
        # Por dia
        by_day = {}
        for p in posts:
            day = p.posted_at.strftime("%a %d/%m")
            if day not in by_day:
                by_day[day] = {"posts": 0, "views": 0}
            by_day[day]["posts"] += 1
            by_day[day]["views"] += p.views or 0
        
        # Por fonte
        by_source = {}
        for p in posts:
            if p.source not in by_source:
                by_source[p.source] = {"posts": 0, "views": 0}
            by_source[p.source]["posts"] += 1
            by_source[p.source]["views"] += p.views or 0
        
        return {
            "total_posts": total_posts,
            "total_views": total_views,
            "total_forwards": total_forwards,
            "by_day": by_day,
            "by_source": by_source
        }
    
    def get_top_posts(self, limit=10):
        """Retorna os posts com mais visualizações."""
        return self.db.query(PostAnalytics).order_by(
            PostAnalytics.views.desc()
        ).limit(limit).all()
    
    def refresh_analytics(self):
        """Atualiza métricas dos posts via Telegram API."""
        posts = self.db.query(PostAnalytics).filter(
            PostAnalytics.posted_at >= datetime.utcnow() - timedelta(days=7)
        ).all()
        
        updated = 0
        for post in posts:
            if not post.message_id:
                continue
            try:
                # Telegram não tem API pública de views, mas channels sim
                # Tentamos via forwardMessageCount
                pass  # Placeholder - Telegram Bot API limitada para métricas
            except:
                pass
        
        return updated
    
    def show_analytics_today(self, chat_id, message_id=None):
        data = self.get_analytics_today()
        
        text = f"""📈 <b>Relatório de Hoje</b>

📊 <b>Resumo:</b>
• Posts enviados: {data['total_posts']}
• Visualizações: {data['total_views']}
• Encaminhamentos: {data['total_forwards']}
• Reações: {data['total_reactions']}

📰 <b>Por Fonte:</b>
"""
        for source, stats in data['by_source'].items():
            text += f"• {source}: {stats['posts']} posts, {stats['views']} views\n"
        
        if not data['by_source']:
            text += "<i>Nenhum post hoje ainda.</i>\n"
        
        keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_analytics"}]]}
        
        if message_id:
            self.api.edit_message(chat_id, message_id, text, keyboard)
        else:
            self.api.send_message(chat_id, text, keyboard)
    
    def show_analytics_week(self, chat_id, message_id=None):
        data = self.get_analytics_week()
        
        text = f"""📊 <b>Relatório Semanal</b>

📈 <b>Totais (7 dias):</b>
• Posts: {data['total_posts']}
• Visualizações: {data['total_views']}
• Encaminhamentos: {data['total_forwards']}

📅 <b>Por Dia:</b>
"""
        for day, stats in sorted(data['by_day'].items()):
            bar = "█" * min(stats['posts'], 20)
            text += f"{day}: {bar} {stats['posts']}\n"
        
        text += "\n📰 <b>Top Fontes:</b>\n"
        sorted_sources = sorted(data['by_source'].items(), key=lambda x: x[1]['views'], reverse=True)[:5]
        for source, stats in sorted_sources:
            text += f"• {source}: {stats['views']} views\n"
        
        keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_analytics"}]]}
        
        if message_id:
            self.api.edit_message(chat_id, message_id, text, keyboard)
        else:
            self.api.send_message(chat_id, text, keyboard)
    
    def show_top_posts(self, chat_id, message_id=None):
        posts = self.get_top_posts(10)
        
        text = "🏆 <b>Top 10 Posts (por views)</b>\n\n"
        
        for i, p in enumerate(posts, 1):
            title = (p.title[:40] + "...") if p.title and len(p.title) > 40 else (p.title or "Sem título")
            text += f"{i}. {p.views or 0} 👁 | {title}\n"
            text += f"   <i>{p.source} - {p.posted_at.strftime('%d/%m')}</i>\n\n"
        
        if not posts:
            text += "<i>Nenhum post registrado ainda.</i>"
        
        keyboard = {"inline_keyboard": [[{"text": "⬅️ Voltar", "callback_data": "menu_analytics"}]]}
        
        if message_id:
            self.api.edit_message(chat_id, message_id, text, keyboard)
        else:
            self.api.send_message(chat_id, text, keyboard)
    
    def show_main_menu(self, chat_id):
        self.api.send_message(chat_id, 
            "🤖 <b>Painel de Configuração</b>\n\nEscolha uma opção:",
            build_main_menu())
    
    def show_status(self, chat_id, message_id=None):
        config = self.config_mgr.get_config()
        sources_on = sum(1 for v in config.get("sources_enabled", {}).values() if v)
        themes_on = sum(1 for v in config.get("themes", {}).values() if v)
        fmt = config.get("format", {})
        
        text = f"""📊 <b>Status do Bot</b>

📰 Fontes ativas: {sources_on}
🏷️ Temas ativos: {themes_on}
🌐 Tradução: {'✅' if fmt.get('translate') else '❌'}
🤖 Resumo IA: {'✅' if fmt.get('summarize') else '❌'}
🔗 Mostrar link: {'✅' if fmt.get('show_link') else '❌'}
🖼️ Mostrar imagem: {'✅' if fmt.get('show_image') else '❌'}
📝 Estilo: {fmt.get('style', 'complete')}

⏱️ Intervalo: {config.get('cycle_interval', 300)}s
🔑 OpenAI: {'✅' if OPENAI_API_KEY else '❌'}
"""
        keyboard = {"inline_keyboard": [[{"text": "⬅️ Menu Principal", "callback_data": "menu_main"}]]}
        
        if message_id:
            self.api.edit_message(chat_id, message_id, text, keyboard)
        else:
            self.api.send_message(chat_id, text, keyboard)
    
    def show_help(self, chat_id):
        self.api.send_message(chat_id, """
📖 <b>Comandos Disponíveis</b>

/start ou /config - Abrir painel de configuração
/status - Ver status atual
/help - Esta mensagem

<b>Recursos:</b>
• Configure fontes de notícias
• Defina horários de postagem
• Escolha formato das mensagens
• Ative tradução automática
• Use IA para resumir notícias
• Filtre por temas específicos
""")
    
    def run(self):
        logger.info("Admin bot started. Listening for commands...")
        offset = None
        while self.running:
            try:
                updates = self.api.get_updates(offset)
                for update in updates:
                    offset = update["update_id"] + 1
                    self.handle_update(update)
            except Exception as e:
                logger.error(f"Error in admin bot loop: {e}")
                time.sleep(5)

# ============================================================
# News Fetcher (using existing NewsPostman)
# ============================================================
def safe_id_policy(link):
    return hashlib.md5(link.encode('utf-8')).hexdigest()[:10]

SOURCES_CONFIG = {
    "coindesk": ("CoinDesk", "https://www.coindesk.com/", "div.article-card, a.card-title", "h1", "div.at-text, div.content, article"),
    "cointelegraph": ("CoinTelegraph", "https://cointelegraph.com/", "li.posts-listing__item, article.post-card-inline", "h1", "div.post-content, article"),
    "decrypt": ("Decrypt", "https://decrypt.co/", "h3 a", "h1", "div.post-content"),
    "bitcoinmagazine": ("BitcoinMagazine", "https://bitcoinmagazine.com/", "h3 a", "h1", "div.m-detail--body, div.c-content, article"),
    "cryptoslate": ("CryptoSlate", "https://cryptoslate.com/", "div.list-post a, div.slate-post a", "h1", "div.post-content, article"),
    "utoday": ("UToday", "https://u.today/news", "div.news-item a, div.story-item a", "h1", "div.article-content, section.article_body"),
    "portaldobitcoin": ("PortalDoBitcoin", "https://portaldobitcoin.uol.com.br/", "h3 a, div.post-title a", "h1", "div.entry-content, div.post-content"),
    "cointelegraphbr": ("CoinTelegraphBR", "https://br.cointelegraph.com/", "li.posts-listing__item", "h1", "div.post-content"),
    "criptofacil": ("CriptoFacil", "https://www.criptofacil.com/", "div.posts-layout article", "h1", "div.entry-content"),
}

def run_news_fetcher(db_session, config_mgr):
    """Thread que busca e posta notícias."""
    logger.info("News fetcher started.")
    
    while True:
        try:
            config = config_mgr.get_config()
            sources_enabled = config.get("sources_enabled", {})
            custom_sources = config.get("custom_sources", {})
            fmt = config.get("format", {})
            cycle_interval = config.get("cycle_interval", 300)
            
            for source_key, enabled in sources_enabled.items():
                if not enabled:
                    continue
                
                # Verificar se é fonte built-in ou custom
                if source_key in SOURCES_CONFIG:
                    name, url, list_sel, title_sel, content_sel = SOURCES_CONFIG[source_key]
                elif source_key in custom_sources:
                    src = custom_sources[source_key]
                    name = src.get("name", source_key)
                    url = src.get("url")
                    list_sel = src.get("list_selector", "h2 a, h3 a")
                    title_sel = src.get("title_selector", "h1")
                    content_sel = src.get("content_selector", "div.content, article")
                elif source_key in POPULAR_SOURCES:
                    name, url, list_sel, title_sel, content_sel = POPULAR_SOURCES[source_key]
                else:
                    continue
                
                try:
                    ie = InfoExtractor()
                    ie._id_policy = safe_id_policy
                    ie.set_list_selector(list_sel)
                    ie.set_title_selector(title_sel)
                    ie.set_paragraph_selector(content_sel)
                    
                    np = NewsPostman(
                        listURLs=[url],
                        sendList=[CHANNEL_ID],
                        db=db_session,
                        tag=f"{name} (PT)" if fmt.get("translate") else name,
                        token=TOKEN
                    )
                    np.set_extractor(ie)
                    np.set_database(db_session)
                    np._table_name = source_key
                    
                    # Custom post-processing with AI
                    def process_data(data, src_name=name, src_key=source_key):
                        title = data.get("title", "")
                        content = data.get("paragraphs", "")
                        
                        # Filtrar por relevância com IA
                        if fmt.get("filter_relevance") and GROQ_API_KEY:
                            score = filter_news_relevance(title, content)
                            min_score = fmt.get("min_relevance_score", 5)
                            if score < min_score:
                                logger.info(f"Filtered out (score {score}): {title[:50]}")
                                return None  # Não posta
                        
                        # Classificar tema
                        theme = "news"
                        if GROQ_API_KEY:
                            theme = classify_news_theme(title, content)
                        
                        # Traduzir
                        if fmt.get("translate"):
                            if title:
                                data["title"] = translate_text(title)
                            if content:
                                data["paragraphs"] = translate_text(content)
                        
                        # Resumir com IA
                        if fmt.get("summarize") and data.get("paragraphs"):
                            data["paragraphs"] = summarize_with_ai(data["paragraphs"])
                        
                        # Adicionar emojis
                        if fmt.get("add_emoji") and data.get("title") and GROQ_API_KEY:
                            data["title"] = add_emojis_to_title(data["title"])
                        
                        # Aplicar estilo
                        if fmt.get("style") == "title_only":
                            data["paragraphs"] = ""
                        elif fmt.get("style") == "summary" and len(data.get("paragraphs", "")) > 300:
                            data["paragraphs"] = data["paragraphs"][:300] + "..."
                        
                        # Salvar analytics
                        try:
                            analytics = PostAnalytics(
                                source=src_name,
                                title=data.get("title", "")[:500],
                                link=data.get("link", ""),
                                theme=theme,
                                posted_at=datetime.utcnow()
                            )
                            db_session.add(analytics)
                            db_session.commit()
                        except Exception as e:
                            logger.error(f"Error saving analytics: {e}")
                            db_session.rollback()
                        
                        return data
                    
                    np._data_post_process = process_data
                    np._action()
                    
                    logger.info(f"Fetched {name}")
                except Exception as e:
                    logger.error(f"Error fetching {source_key}: {e}")
                
                time.sleep(2)
            
            logger.info(f"Cycle complete. Sleeping {cycle_interval}s...")
            time.sleep(cycle_interval)
            
        except Exception as e:
            logger.error(f"Error in news fetcher: {e}")
            time.sleep(60)

def run_event_alerts(db_session, config_mgr, api):
    """Thread separada para verificar e enviar alertas de eventos."""
    logger.info("Event alerts checker started.")
    
    # Carregar eventos iniciais
    fetch_and_save_events(db_session)
    logger.info("Initial events loaded.")
    
    while True:
        try:
            config = config_mgr.get_config()
            
            # Verificar e enviar alertas
            alerts_sent = check_and_send_event_alerts(db_session, api, CHANNEL_ID, config)
            if alerts_sent > 0:
                logger.info(f"Sent {alerts_sent} event alerts")
            
            # Atualizar eventos a cada 6 horas
            time.sleep(3600)  # Verificar alertas a cada hora
            
        except Exception as e:
            logger.error(f"Error in event alerts: {e}")
            time.sleep(300)

# ============================================================
# Main
# ============================================================
def main():
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN not set!")
        sys.exit(1)
    
    if not CHANNEL_ID:
        logger.error("CHANNEL_ID not set!")
        sys.exit(1)
    
    # Database setup
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    db_session = Session(bind=engine.connect())
    
    # Start admin bot
    admin_bot = AdminBot(TOKEN, db_session)
    config_mgr = admin_bot.config_mgr
    
    # Initialize calendar events
    logger.info("Loading crypto events...")
    fetch_and_save_events(db_session)
    
    # Start news fetcher in background
    news_thread = threading.Thread(target=run_news_fetcher, args=(db_session, config_mgr), daemon=True)
    news_thread.start()
    
    # Start event alerts checker in background
    alerts_thread = threading.Thread(target=run_event_alerts, args=(db_session, config_mgr, admin_bot.api), daemon=True)
    alerts_thread.start()
    
    # Run admin bot (blocking)
    admin_bot.run()

if __name__ == "__main__":
    main()
