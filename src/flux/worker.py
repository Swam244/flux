import time
import threading
import logging
import redis
import json
from typing import Dict, Any, Optional, List
from .config import FluxConfig

logger = logging.getLogger("flux.worker")

class AnalyticsWorker:
    """
    Asynchronous worker that consumes rate limit events from a Redis Stream
    and aggregates them into metrics hashes.
    """
    def __init__(self, config: FluxConfig):
        self.config = config
        # Use a dedicated connection for the worker with higher timeout for blocking reads
        self.redis = redis.Redis(
            host=config.redis_host,
            port=config.redis_port,
            decode_responses=True,
            socket_timeout=5.0, # 5s timeout for block=2000ms
        )
        self.stream_key = config.analytics_stream
        self.group_name = "flux_analytics_group"
        self.consumer_name = f"worker:{config.analytics_port}" # Simple unique name
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def start(self):
        """Start the worker thread."""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self._ensure_group()
        self.thread.start()
        logger.info("Analytics Worker started.")

    def stop(self):
        """Stop the worker thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1.0)
            
    def _ensure_group(self):
        """Ensure consumer group exists."""
        try:
            self.redis.xgroup_create(self.stream_key, self.group_name, id='0', mkstream=True)
        except redis.exceptions.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                logger.error(f"Failed to create consumer group: {e}")

    def _run_loop(self):
        """Main processing loop."""
        while self.running:
            try:
                # Read new messages
                entries = self.redis.xreadgroup(
                    self.group_name, 
                    self.consumer_name, 
                    {self.stream_key: '>'}, 
                    count=100, 

                    block=200 
                )
                
                if not entries:
                    continue
                    
                stream_name, messages = entries[0]
                if not messages:
                    continue
                
                self._process_messages(messages)
                
            except Exception as e:
                logger.error(f"Error in analytics worker loop: {e}")
                time.sleep(1)

    def _process_messages(self, messages: List[Any]):
        """Process a batch of messages."""
        if not messages:
            return

        pipeline = self.redis.pipeline()
        ack_ids = []
        
        prefix = self.config.key_prefix
        
        for msg_id, data in messages:
            try:
                # data is {b'ts': b'123', b'key': b'foo', ...}
                # redis-py decoding depends on client setting. Assuming decode_responses=True
                
                # Parse fields
                # Note: Fields might be bytes if client not decoding.
                # Since we passed decode_responses=True in limiter.py -> metrics_client,
                # we assume this client does too.
                
                endpoint = data.get('ep') or data.get(b'ep')
                if not endpoint:
                    ack_ids.append(msg_id)
                    continue

                decision = int(data.get('d') or data.get(b'd') or 0)
                usage = int(data.get('u') or data.get(b'u') or 0)
                now = int(data.get('ts') or data.get(b'ts') or 0)
                
                # Metadata (limit info)
                m_requests = int(data.get('mr') or data.get(b'mr') or 0)
                m_period = int(data.get('mp') or data.get(b'mp') or 0)
                m_burst = int(data.get('mb') or data.get(b'mb') or 0)
                m_policy = data.get('p') or data.get(b'p') or "unknown"
                if isinstance(m_policy, bytes):
                    m_policy = m_policy.decode('utf-8')
                
                # Reconstruct Legacy Keys
                stats_ep_key = f"{prefix}stats:ep:{endpoint}"
                stats_global_key = f"{prefix}stats:global"
                stats_ep_set = f"{prefix}stats:endpoints"
                stats_ttl = 3600
                
                # Accrue cmds to pipeline
                pipeline.sadd(stats_ep_set, endpoint)
                pipeline.expire(stats_ep_set, stats_ttl)
                
                status_field = "c:allowed" if decision == 1 else "c:blocked"
                pipeline.hincrby(stats_ep_key, status_field, 1)
                
                # Update usage and metadata
                # We update metadata on every hit (idempotent but frequent) - cheap enough in pipeline
                pipeline.hset(stats_ep_key, mapping={
                    'u:raw': usage,
                    'm:last_updated': now,
                    'm:requests': m_requests,
                    'm:period': m_period,
                    'm:burst': m_burst,
                    'm:policy': m_policy
                })
                pipeline.expire(stats_ep_key, stats_ttl)
                
                pipeline.hincrby(stats_global_key, 'l:count', 1)
                pipeline.expire(stats_global_key, stats_ttl)
                
                ack_ids.append(msg_id)
                
            except Exception as e:
                logger.error(f"Failed to process message {msg_id}: {e}")
                # Still ack? Or retry? For metrics, maybe ack to avoid poison pill loop.
                ack_ids.append(msg_id)

        # Execute updates
        if ack_ids:
            pipeline.xack(self.stream_key, self.group_name, *ack_ids)
            pipeline.execute()
