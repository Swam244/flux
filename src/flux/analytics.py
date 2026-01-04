import threading
import json
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from redis import Redis
import socket

# Configure logging
logger = logging.getLogger("flux.analytics")

class MetricsHandler(BaseHTTPRequestHandler):
    """
    Handles /metrics requests by fetching data from Redis.
    """
    
    def do_GET(self):
        if self.path == '/metrics' or self.path == '/stats':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            # Fetch metrics from Redis
            # We need to access the Redis client. 
            # Ideally passed down, but for simplicity in this handler we might need a reference or new connection.
            # Since this is a lightweight thread inside the app, we can use a new connection or shared one.
            # Let's generate the response using the StatsProvider logic (reimplemented for zero-dep simplicity or import).
            
            try:
                metrics = self.server.stats_provider.get_stats()
                response = json.dumps(metrics).encode('utf-8')
                self.wfile.write(response)
            except Exception as e:
                logger.error(f"Error fetching metrics: {e}")
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not Found"}')
    
    def log_message(self, format, *args):
        # Silence default logging
        pass

class AnalyticsServer:
    """
    Background analytics server that exposes metrics via HTTP.
    Runs in a daemon thread.
    """
    
    def __init__(self, config, stats_provider):
        self.config = config
        self.port = config.analytics_port
        self.stats_provider = stats_provider
        self.server = None
        self.thread = None
        self._running = False
        
    def start(self):
        """Start the background server."""
        if self._running:
            return
            
        try:
            # Create server
            self.server = HTTPServer(('localhost', self.port), MetricsHandler)
            # Inject dependency into server instance so handler can access it
            self.server.stats_provider = self.stats_provider
            
            # Start thread
            self.thread = threading.Thread(target=self._run_server, daemon=True)
            self.thread.start()
            self._running = True
            logger.info(f"Analytics server started on port {self.port}")
            print(f"[flux] Analytics server listening on localhost:{self.port}")
        except OSError as e:
            if e.errno == 98: # Address already in use
                logger.warning(f"Port {self.port} already in use. Analytics server not started.")
                print(f"[flux] Warning: Port {self.port} in use. Analytics unavailable.")
            else:
                raise
                
    def _run_server(self):
        """Thread target."""
        if self.server:
            self.server.serve_forever()

    def stop(self):
        """Stop the server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self._running = False
