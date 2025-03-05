# config.py
import os
import configparser

config = configparser.ConfigParser()
config.read(os.path.join(os.path.dirname(__file__), 'config.ini'))

BOT_TOKEN = config.get('Bot', 'BOT_TOKEN', fallback='YOUR_TOKEN_HERE')
TOKEN_ADDRESS = config.get('Bot', 'TOKEN_ADDRESS', fallback='YOUR_TOKEN_ADDRESS_HERE')
ADMIN_ID = int(config.get('Bot', 'ADMIN_ID', fallback='1231828775'))
API_URL = f"https://api.dexscreener.com/latest/dex/pairs/ton/{TOKEN_ADDRESS}"