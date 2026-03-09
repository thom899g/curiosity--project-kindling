"""
Project Forge - Main Engine
Architectural Choice: Event-driven main loop with health-checked RPC failover
and circuit breaker pattern for system resilience.
"""
import asyncio
import logging
import logging.config
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from decimal import Decimal
import json

from web3 import Web3, AsyncWeb3
from web3.exceptions import TransactionNotFound, BlockNotFound
from eth_account import Account

from config import LOGGING_CONFIG, RPC, WALLET, BREAKER, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from firebase_client import FirebaseClient
from auctioneer import Auctioneer
from senses.orchestrator import SenseOrchestrator
from telegram_alerter import TelegramAlerter

logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger('forge')

class ForgeEngine:
    """Main trading engine orchestrating all components"""
    
    def __init__(self):
        self.web3_clients: Dict[str, AsyncWeb3] = {}
        self.active_rpc: str = RPC.primary_url
        self.rpc_health: Dict[str, Dict[str, Any]] = {}
        self.firebase = FirebaseClient()
        self.auctioneer: Optional[Auctioneer] = None
        self.orchestrator: Optional[SenseOrchestrator] = None
        self.alerter = TelegramAlerter(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        self.circuit_breaker_triggered = False
        self.mission_start_time: Optional[datetime] = None
        self.consecutive_failures = 0
        
    async def initialize(self) -> bool:
        """Initialize all system components with error handling"""
        try:
            logger.info("Initializing Project Forge Engine...")
            
            # Initialize Web3 clients
            await self._initialize_web3_clients()
            
            # Initialize Firebase
            if not await self.firebase.initialize():
                logger.error("Failed to initialize Firebase")
                return False
            
            # Initialize Auctioneer
            self.auctioneer = Auctioneer(self.web3_clients[self.active_rpc], self.firebase)
            
            # Initialize Sense Orchestrator
            self.orchestrator = SenseOrchestrator(self.web3_clients[self.active_rpc], self.firebase)
            
            # Set mission start time
            self.mission_start_time = datetime.utcnow()
            await self.firebase.update_mission_state({
                'mission_start_time': self.mission_start_time.isoformat(),
                'status': 'initializing'
            })
            
            logger.info("Forge Engine initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Engine initialization failed: {e}", exc_info=True)
            await self.alerter.send_critical(f"Engine init failed: {str(e)[:100]}")
            return False
    
    async def _initialize_web3_clients(self):
        """Initialize multiple Web3 clients for redundancy"""
        rpcs = {
            'primary': RPC.primary_url,
            'secondary': RPC.secondary_url,
            'fallback': RPC.fallback_url
        }
        
        for name, url in rpcs.items():
            try:
                # Initialize async Web3 client
                w3 = AsyncWeb3(AsyncWeb3.AsyncHTTPProvider(url))
                
                # Test connection
                block = await w3.eth.block_number
                if block > 0:
                    self.web3_clients[url] = w3
                    self.rpc_health[url] = {
                        'latency': 0,
                        'last_check': datetime.utcnow(),
                        'error_count': 0,
                        'healthy': True
                    }
                    logger.info(f"RPC {name} connected at block {block}")
                else:
                    logger.warning(f"RPC {name} returned invalid block number")
                    
            except Exception as e:
                logger.warning(f"Failed to initialize RPC {name}: {e}")
    
    async def _check_rpc_health(self) -> bool:
        """Health check all RPC endpoints and failover if needed"""
        current_time = datetime.utcnow()
        
        for url, health in self.rpc_health.items():
            try:
                start = datetime.utcnow()
                block = await self.web3_clients[url].eth.block_number
                latency = (datetime.utcnow() - start).total_seconds() * 1000
                
                health['latency'] = latency
                health['last_check'] = current_time
                
                if latency > RPC.max_latency_ms:
                    health['error_count'] += 1
                    logger.warning(f"RPC {url} latency high: {latency:.2f}ms")
                
                health['healthy'] = (health['error_count'] < 3 and latency <= RPC.max_latency_ms)
                
            except Exception as e:
                health['error_count'] += 1
                health['healthy'] = False
                logger.error(f"RPC {url} health check failed: {e}")
        
        # Select best RPC
        healthy_rpcs = [url for url, health in self.rpc_health.items() 
                       if health['healthy']]
        
        if not healthy_rpcs:
            logger.critical("No healthy RPC endpoints available")
            await self.alerter.send_critical("ALL RPCs unhealthy - system halt")
            return False
        
        # Choose RPC with lowest latency
        best_rpc = min(healthy_rpcs, key=lambda x: self.rpc_health[x]['latency'])
        
        if best_rpc != self.active_rpc:
            logger.info(f"RPC failover: {self.active_rpc} -> {best_rpc}")
            self.active_rpc = best_rpc
            await self.alerter.send_alert(f"RPC failover to {best_rpc}")
        
        return True
    
    async def _check_circuit_breaker(self) -> bool:
        """Check system health and trigger circuit breaker if needed"""
        try:
            state = await self.firebase.get_mission_state()
            
            if not state:
                logger.error("Cannot read mission state for circuit breaker")
                return True
            
            net_worth = Decimal(state.get('net_worth_usd', '0'))
            ppgu_trend = state.get('ppgu_trend', [])
            
            # Condition 1: Net worth below catastrophic threshold
            if net_worth < BREAKER.min_net_worth_usd:
                logger.critical(f"Circuit breaker: NW ${net_worth} < ${BREAKER.min_net_worth_usd}")
                await self.alerter.send_critical(f"CATACLYSMIC LOSS: NW ${net_worth}")
                return False
            
            # Condition 2: Negative PPGU trend
            if len(ppgu_trend) >= BREAKER.negative_ppgu_streak:
                recent_ppgu = ppgu_trend[-BREAKER.negative_ppgu_streak:]
                if all(p.get('value', 0) < 0 for p in recent_ppgu):
                    logger.critical(f"Circuit breaker: {BREAKER.negative_ppgu_streak} consecutive negative PPGU")
                    await self.alerter.send_critical("Negative PPGU streak - system losing value")
                    return False
            
            # Condition 3: Consecutive trade failures
            if self.consecutive_failures >= 3:
                logger.critical(f"Circuit breaker: {self.consecutive_failures} consecutive failures")
                await self.alerter.send_critical(f"{self.consecutive_failures} consecutive trade failures")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Circuit breaker check failed: {e}")
            # Fail open - don't trigger breaker on check failure
            return True
    
    async def run(self):
        """Main event loop with health monitoring"""
        logger.info("Starting Forge Engine main loop")
        await self.alerter.send_alert("🚀 Project Forge Engine started")
        
        last_health_check = datetime.utcnow()
        last_block = 0
        
        try:
            while True:
                current_time = datetime.utcnow()
                
                # Health check every 30 seconds
                if (current_time - last_health_check).total_seconds() >= 30:
                    if not await self._check_rpc_health():
                        break
                    
                    if not await self._check_circuit_breaker():
                        self.circuit_breaker_triggered = True
                        await self.alerter.send_critical("🔴 CIRCUIT BREAKER TRIGGERED - System halted")
                        break
                    
                    last_health_check = current_time
                
                # Get latest block
                try:
                    current_block = await self.web3_clients[self.active_rpc].eth.block_number
                    
                    if current_block > last_block:
                        logger.debug(f"New block: {current_block}")
                        
                        # Scan for opportunities
                        opportunities = await self.orchestrator.scan(current_block)
                        
                        # Process opportunities if system is healthy
                        if opportunities and not self.circuit_breaker_triggered:
                            for opportunity in opportunities:
                                success = await self.auctioneer.process_opportunity(opportunity)
                                
                                if success:
                                    self.consecutive_failures = 0
                                else:
                                    self