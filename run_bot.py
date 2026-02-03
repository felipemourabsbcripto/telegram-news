import os
import sys
import time
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from telegram_news.template import InfoExtractor, NewsPostman

# ============================================================
# 🔧 CONFIGURAÇÕES PRINCIPAIS - EDITE AQUI!
# ============================================================

# ⏰ TEMPO (em segundos)
SLEEP_BETWEEN_SOURCES = 2      # Tempo entre cada fonte (evita spam)
SLEEP_BETWEEN_CYCLES = 60      # Tempo entre ciclos de verificação (60 = 1 min, 300 = 5 min)

# 📝 ESTILO DA MENSAGEM
MAX_MESSAGE_LENGTH = 1000       # Tamanho máximo do texto (caracteres)
MAX_PARAGRAPHS = 15             # Número máximo de parágrafos

# 🌐 IDIOMA DA TRADUÇÃO
TARGET_LANGUAGE = 'pt'          # Idioma destino: 'pt' = Português, 'en' = Inglês, 'es' = Espanhol

# ============================================================

# Try to import translator
try:
    from deep_translator import GoogleTranslator
    HAS_TRANSLATOR = True
except ImportError:
    HAS_TRANSLATOR = False
    print("Warning: 'deep-translator' not found. Translation will be disabled.")
    print("Run: pip install deep-translator")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import hashlib

# Check for token
token = os.getenv("TELEGRAM_TOKEN") or os.getenv("TOKEN")
if not token:
    logger.error("TELEGRAM_TOKEN environment variable not set.")
    sys.exit(1)

# Better ID Policy
def safe_id_policy(link):
    """
    Generates a unique ID from the link using hash.
    Standard policy tries to find digits, but many crypto sites use slug-only URLs.
    """
    return hashlib.md5(link.encode('utf-8')).hexdigest()[:10]

# Database Setup
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///crypto_news.db")
try:
    engine = create_engine(DATABASE_URL)
    db = Session(bind=engine.connect())
except Exception as e:
    logger.error(f"Database error: {e}")
    sys.exit(1)

CHANNEL_ID = os.getenv("CHANNEL_ID") or os.getenv("TELEGRAM_CHANNEL") or "@test_channel_placeholder"

# --- Translation Logic ---
def translate_data(data):
    """Translates title and paragraphs to Portuguese."""
    if not HAS_TRANSLATOR:
        return data
    
    translator = GoogleTranslator(source='auto', target=TARGET_LANGUAGE)

    try:
        # Translate Title
        if data.get('title'):
            data['title'] = translator.translate(data['title'])
        
        # Translate Paragraphs (Context)
        # Paragraphs is usually a string (all text joined) or list. 
        # Looking at common.py, it seems to be a string joined by \n usually, or list.
        # Let's handle both.
        content = data.get('paragraphs', '')
        if isinstance(content, list):
            content = "\n".join(content)
        
        if content:
            # Chunking might be needed for very long texts, but for summary news often ok.
            # deep-translator handles limits by default usually? No, it might fail on 5k chars.
            # Simple truncation for safety
            if len(content) > 4000: 
                content = content[:4000] + "..."
            
            data['paragraphs'] = translator.translate(content)
            
    except Exception as e:
        logger.error(f"Translation failed for {data.get('link')}: {e}")
    
    return data

# --- Source Configuration ---
class NewsSource:
    def __init__(self, name, url, tag, list_selector, title_selector, content_selector, need_translation=False):
        self.name = name
        self.url = url
        self.tag = tag
        self.list_selector = list_selector
        self.title_selector = title_selector
        self.content_selector = content_selector
        self.need_translation = need_translation
        self.table_name = "".join(x for x in name if x.isalnum()).lower()[:50] # sanitize table name

# Define Sources
# Note: CSS Selectors are "best guess" generic ones to start with. 
# You might need to refine them using browser DevTools (Inspect Element).
sources = [
    # --- International (English) ---
    NewsSource(
        "CoinDesk", 
        "https://www.coindesk.com/", 
        "CoinDesk (PT)", 
        "div.article-card, a.card-title", # Generic card selector
        "h1", 
        "div.at-text, div.content, article", 
        need_translation=True
    ),
    # NewsSource(
    #     "TheBlock", 
    #     "https://www.theblock.co/", 
    #     "TheBlock (PT)", 
    #     "div.articleCard, a.app-link", 
    #     "h1", 
    #     "div.articleContent, div.post-content", 
    #     need_translation=True
    # ),
    NewsSource(
        "CoinTelegraph", 
        "https://cointelegraph.com/", 
        "CoinTelegraph (PT)", 
        "li.posts-listing__item, article.post-card-inline", 
        "h1", 
        "div.post-content, article", 
        need_translation=True
    ),
    NewsSource(
        "Decrypt", 
        "https://decrypt.co/", 
        "Decrypt (PT)", 
        "h3 a", 
        "h1", 
        "div.post-content", 
        need_translation=True
    ),
    NewsSource(
        "BitcoinMagazine", 
        "https://bitcoinmagazine.com/", 
        "Bitcoin Magazine (PT)", 
        "h3 a", 
        "h1", 
        "div.m-detail--body, div.c-content, article", 
        need_translation=True
    ),
    NewsSource(
        "CryptoSlate", 
        "https://cryptoslate.com/", 
        "CryptoSlate (PT)", 
        "div.list-post a, div.slate-post a", 
        "h1", 
        "div.post-content, article", 
        need_translation=True
    ),
    NewsSource(
        "UToday", 
        "https://u.today/news", 
        "U.Today (PT)", 
        "div.news-item a, div.story-item a", 
        "h1", 
        "div.article-content, section.article_body", 
        need_translation=True
    ),

    # --- National (Portuguese) ---
    NewsSource(
        "PortalDoBitcoin", 
        "https://portaldobitcoin.uol.com.br/", 
        "Portal do Bitcoin", 
        "h3 a, div.post-title a", 
        "h1", 
        "div.entry-content, div.post-content"
    ),
    NewsSource(
        "CoinTelegraphBR", 
        "https://br.cointelegraph.com/", 
        "CoinTelegraph BR", 
        "li.posts-listing__item", 
        "h1", 
        "div.post-content"
    ),
    NewsSource(
        "CriptoFacil", 
        "https://www.criptofacil.com/", 
        "CriptoFácil", 
        "div.posts-layout article", 
        "h1", 
        "div.entry-content"
    ),
   
    # --- Aggregators (might be hard to scrape detailed content from list only) ---
    # Cryptopanic and CMC usually link out. The logic below scrapes the LINK destination.
    # If the link is external, the generic selectors might fail on the destination site 
    # unless we have a 'generic' extractor.
    # For now, let's keep them but warn they might be flaky without specific domain handling.
]

def run_loop():
    logger.info(f"Starting Multi-Source News Bot... Target Channel: {CHANNEL_ID}")
    
    # Initialize Postmen
    postmen = []
    
    for source in sources:
        try:
            ie = InfoExtractor()
            ie._id_policy = safe_id_policy # Use hash-based ID to avoid 'list index out of range' on URLs without numbers
            ie.set_list_selector(source.list_selector)
            ie.set_title_selector(source.title_selector)
            ie.set_paragraph_selector(source.content_selector)
            
            # Using generic selectors for list items if specifics fail
            # ie.set_list_selector("a[href*='/news/'], a[href*='/article/']") 

            np = NewsPostman(
                listURLs=[source.url],
                sendList=[CHANNEL_ID],
                db=db,
                tag=source.tag,
                token=token
            )
            np.set_extractor(ie)
            np.set_database(db)
            
            # Monkey-patch or set table name safely
            try:
                np.set_table_name(source.table_name)
            except Exception:
                # Fallback for SQLite or if table exists
                np._table_name = source.table_name

            # Set Translation Hook
            if source.need_translation:
                # We connect the hook. 
                # Note: `_data_post_process` is not a public API but we saw it in common.py
                np._data_post_process = translate_data
            
            postmen.append((source.name, np))
            logger.info(f"Initialized {source.name}")
            
        except Exception as e:
            logger.error(f"Failed to init {source.name}: {e}")

    # Main Loop
    while True:
        logger.info("--- Starting Fetch Cycle ---")
        for name, np in postmen:
            try:
                logger.info(f"Fetching {name}...")
                # Run once
                np._action()
            except Exception as e:
                logger.error(f"Error running {name}: {e}")
            
            # Be polite to servers
            time.sleep(SLEEP_BETWEEN_SOURCES) 
        
        logger.info(f"Cycle complete. Sleeping {SLEEP_BETWEEN_CYCLES}s...")
        time.sleep(SLEEP_BETWEEN_CYCLES)

if __name__ == "__main__":
    run_loop()
