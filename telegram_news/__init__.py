# -*- coding: UTF-8 -*-

"""This package provides templates, utilities and display policies."""

from .template import NewsPostman

LOGO = r'''
      ______     __
     /_  __/__  / /__  ____ __________ _____ ___        ____  ___ _      _______
      / / / _ \/ / _ \/ __ `/ ___/ __ `/ __ `__ \______/ __ \/ _ \ | /| / / ___/
     / / /  __/ /  __/ /_/ / /  / /_/ / / / / / /_____/ / / /  __/ |/ |/ (__  )
    /_/  \___/_/\___/\__, /_/   \__,_/_/ /_/ /_/     /_/ /_/\___/|__/|__/____/
                    /____/
	                https://github.com/ESWZY/telegram-news
'''

def set_bot_token(token):
    """Set the default telegram bot token."""
    NewsPostman.set_bot_token(token)

__all__ = ['LOGO', 'set_bot_token']
