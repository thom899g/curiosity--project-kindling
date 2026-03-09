"""
Project Forge - Core Configuration
Architectural Choice: Centralized configuration with environment variable fallbacks
enables easy deployment across different environments (local, VPS, testnet)
"""
import os
from dataclasses import dataclass
from typing import Optional
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

@dataclass
class RPCConfig:
    """Multi-RPC configuration for redundancy and failover"""
    primary_url: str
    secondary_url: str
    fallback_url: str = "https://mainnet.base.org"
    health_check_interval: int = 30  # seconds
    max_latency_ms: int = 150
    max_error_rate: float = 0.02

@dataclass
class WalletConfig:
    """Dual-wallet security architecture (Vault & Clerk)"""
    vault_address: str  # Safe wallet address
    clerk_private_key: str  # EOA private key (encrypted in .env)
    clerk_address: str
    min_clerk_balance_eth: Decimal = Decimal('0.01')
    allowance_timeout_blocks: int = 100  # Blocks until allowance expires

@dataclass
class TradingConfig:
    """Dynamic trading parameters that scale with Net Worth"""
    min_profit_threshold_usd: Decimal = Decimal('0.30')
    min_profit_percentage_of_nw: Decimal = Decimal('0.005')  # 0.5%
    max_slippage_percentage: Decimal = Decimal('0.02')  # 2%
    gas_price_multiplier: Decimal = Decimal('1.3')
    priority_fee_percentage: Decimal = Decimal('0.80')  # 80% of profit to builder
    max_trade_failure_streak: int = 3

@dataclass
class CircuitBreakerConfig:
    """System protection thresholds"""
    min_net_worth_usd: Decimal = Decimal('5.00')
    negative_ppgu_streak: int = 5  # 5-minute negative PPGU average
    system_halt: bool = False

@dataclass
class FirebaseConfig:
    """Observability and state management configuration"""
    project_id: str
    service_account_path: str = "./serviceAccountKey.json"
    collections: dict = None
    
    def __post_init__(self):
        if self.collections is None:
            self.collections = {
                'mission_state': 'mission_state',
                'trade_logs': 'trade_logs',
                'system_metrics': 'system_metrics',
                'sense_performance': 'sense_performance'
            }

# Initialize configurations
try:
    RPC = RPCConfig(
        primary_url=os.getenv('RPC_PRIMARY_URL', ''),
        secondary_url=os.getenv('RPC_SECONDARY_URL', ''),
        fallback_url=os.getenv('RPC_FALLBACK_URL', 'https://mainnet.base.org')
    )
    
    WALLET = WalletConfig(
        vault_address=os.getenv('VAULT_ADDRESS', ''),
        clerk_private_key=os.getenv('CLERK_PRIVATE_KEY', ''),
        clerk_address=os.getenv('CLERK_ADDRESS', '')
    )
    
    TRADING = TradingConfig()
    BREAKER = CircuitBreakerConfig()
    FIREBASE = FirebaseConfig(project_id=os.getenv('FIREBASE_PROJECT_ID', ''))
    
    # Telegram alerting
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
    
    # Mission parameters
    MISSION_DURATION_HOURS = 72
    SUCCESS_THRESHOLD_USD = Decimal('50.00')
    
except KeyError as e:
    raise EnvironmentError(f"Missing required environment variable: {e}")

# Logging configuration
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
            'stream': 'ext://sys.stdout',
        },
        'file': {
            'level': 'DEBUG',
            'formatter': 'standard',
            'class': 'logging.FileHandler',
            'filename': 'forge_engine.log',
            'mode': 'a',
        },
    },
    'loggers': {
        'forge': {
            'handlers': ['default', 'file'],
            'level': 'INFO',
            'propagate': False
        },
        'senses': {
            'handlers': ['default', 'file'],
            'level': 'INFO',
            'propagate': False
        },
        'auctioneer': {
            'handlers': ['default', 'file'],
            'level': 'INFO',
            'propagate': False
        }
    }
}