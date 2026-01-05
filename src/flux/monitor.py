import sys
import time
import json
import urllib.request
import os

# ANSI Colors
RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
GREY = "\033[90m"
RESET = "\033[0m"

# ANSI Config
CLEAR = "\033[H\033[J" # Move to home, clear screen from cursor down

def fetch_metrics(port=4444):
    try:
        url = f"http://localhost:{port}/metrics"
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode())
    except Exception:
        return None

def draw_progress_bar(percent, width=30):
    # Ensure percent is 0-100
    if percent < 0: percent = 0
    if percent > 100: percent = 100
    
    fill = int(width * percent / 100)
    empty = width - fill
    
    # Colors
    color = GREEN
    if percent > 50: color = YELLOW
    if percent > 85: color = RED
    
    bar = "█" * fill
    bg = "░" * empty
    return f"{color}{bar}{GREY}{bg}{RESET}"

def normalize_usage(raw_usage, policy, requests, period, burst, last_updated_ms=0):
    # Apply Visual Decay
    # If the metrics are stale, simulate the refill
    now_ms = time.time() * 1000
    elapsed_ms = max(0, now_ms - last_updated_ms) if last_updated_ms > 0 else 0
    
    # 1. Decay the raw value first
    if policy == "gcra":
        # GCRA: usage is (TAT - now). It naturally decreases 1ms per 1ms of real time.
        # But raw_usage here is the snapshot of (TAT - now) from when it was recorded.
        # So we just subtract elapsed time.
        current_usage_ms = max(0, raw_usage - elapsed_ms)
        
        # Convert to requests
        if requests <= 0: return 0
        emission_interval = (period * 1000) / requests
        if emission_interval > 0:
            return current_usage_ms / emission_interval
            
    else: # Token Bucket / Leaky Bucket
        # Usage is "Tokens Used" (Capacity - Tokens Available)
        # It decreases at refill rate (tokens/sec)
        # Refill amount = elapsed_seconds * rate
        # Rate = requests / period
        
        if period <= 0: return raw_usage
        refill_amount = (elapsed_ms / 1000.0) * (requests / period)
        current_usage_tokens = max(0, raw_usage - refill_amount)
        return current_usage_tokens
        
    return 0

def format_time_to_full(usage_raw, policy, requests, period):
    if usage_raw <= 0:
        return f"{GREEN}0.0s{RESET}"
        
    seconds = 0
    if policy == "gcra":
        seconds = usage_raw / 1000.0
    else:
        # Token/Leaky
        if requests > 0 and period > 0:
            rate = requests / period
            seconds = usage_raw / rate
            
    color = YELLOW if seconds < 5 else RED
    return f"{color}{seconds:.1f}s{RESET}"

def render_tui(metrics, last_metrics, dt, peak_rps_map):
    # Calculate global deltas
    # (Actually we do per-endpoint deltas)
    
    print(CLEAR, end="")
    print(f"{BLUE}Flux Limiter Monitor{RESET}")
    print(f"{GREY}Connected to Analytics Server{RESET}")
    print("-" * 60)
    
    if not metrics:
        print(f"{RED}Waiting for connection...{RESET}")
        return

    # Filter out stale endpoints (inactive for > 60s) to prevent UI overflow
    now_ms = time.time() * 1000
    active_endpoints = []
    for ep_data in metrics:
        last = ep_data.get('last_updated', 0)
        if (now_ms - last) < 60000:  # 60s window
            active_endpoints.append(ep_data)

    # Sort endpoints
    endpoints = sorted(active_endpoints, key=lambda x: x['endpoint'])
    
    for ep_data in endpoints:
        ep = ep_data['endpoint']
        limit = ep_data['limit_info']
        usage_raw = ep_data.get('utilization_raw', 0)
        
        # Calculate Utilization %
        # Assume burst is the capacity
        capacity = limit.get('burst', 0) or 1
        used_requests = normalize_usage(
            usage_raw, 
            limit.get('policy', 'unknown'),
            limit.get('requests', 1),
            limit.get('period', 1),
            capacity,
            ep_data.get('last_updated', 0)
        )
        # Cap at 0-100% roughly (can go over if burst allows or lag)
        pct = (used_requests / capacity) * 100
        pct = max(0, min(100, pct))
        
        # Calculate RPS
        rps = 0
        last_item = next((x for x in last_metrics if x['endpoint'] == ep), None)
        if last_item and dt > 0:
            diff = ep_data['total'] - last_item['total']
            rps = diff / dt
            
        # Update Peak RPS
        peak = peak_rps_map.get(ep, 0)
        if rps > peak:
            peak = rps
            peak_rps_map[ep] = peak
            
        # Time to full
        # 1. Get raw decayed value
        now_ms = time.time() * 1000
        elapsed_ms = max(0, now_ms - ep_data.get('last_updated', 0)) if ep_data.get('last_updated') > 0 else 0
        
        current_raw = 0
        current_tokens_used = 0.0
        
        if limit.get('policy') == "gcra":
             current_raw = max(0, usage_raw - elapsed_ms)
             # Normalize to tokens for display
             requests = limit.get('requests', 1) or 1
             period = limit.get('period', 1) or 1
             emission = (period * 1000) / requests
             if emission > 0:
                current_tokens_used = current_raw / emission
        else:
             # Token/Leaky
             if limit.get('period') > 0:
                 refill_amount = (elapsed_ms / 1000.0) * (limit.get('requests') / limit.get('period'))
                 current_raw = max(0, usage_raw - refill_amount)
                 current_tokens_used = current_raw
        
        ttf = format_time_to_full(
             current_raw,
             limit.get('policy', 'unknown'),
             limit.get('requests'),
             limit.get('period')
        )
        
        # Raw Display Context (Normalized to "Used")
        raw_display = f"{current_tokens_used:.1f} used"

        # Prepare Rows with Fixed Width
        # Target inner width: 56 chars
        # │ <content> │
        
        policy_str = f"[{limit.get('policy','???').upper()}]"
        header = f"{ep} {policy_str}"
        # Truncate if too long
        if len(header) > 54: header = header[:54]
        
        limit_str = f"Limit: {limit.get('requests')}/{limit.get('period')}s | Burst: {limit.get('burst')}"
        
        stats_line_1 = f"RPS: {rps:<5.1f} (Peak: {peak:<5.1f}) | Reset in: {ttf}"
        stats_line_2 = f"Allowed: {ep_data['allowed']:<6} Blocked: {ep_data['blocked']:<4} | {raw_display}"

        print(f"┌─ {BLUE}{header:<54}{RESET} ─┐")
        print(f"│ {limit_str:<56} │")
        print(f"│                                                        │")
        bar = draw_progress_bar(pct, width=40)
        print(f"│ {bar} {int(pct):>3}%          │")
        print(f"│                                                        │")
        # Note: stats_line_1 contains ANSI codes (in ttf), so logic len calculation is tricky for padding.
        # We manually pad roughly or strip ansi for len calc.
        # ttf has color codes. length of visible chars is roughly 7-8 chars (e.g. 12.3s).
        # string len with color is much longer.
        # simpler approach: use fixed spacing in f-string
        
        print(f"│ RPS: {rps:<5.1f} (Peak: {peak:<5.1f}) | Reset in: {ttf:<17}   │") 
        print(f"│ Allowed: {ep_data['allowed']:<6} Blocked: {ep_data['blocked']:<4} | {raw_display:<14} │")
        print(f"└────────────────────────────────────────────────────────┘")
        print("")
    
    sys.stdout.flush()

def main():
    port = int(os.environ.get("FLUX_MONITOR_PORT", 4444))
    
    last_metrics = []
    last_time = time.time()
    
    peak_rps_map = {}
    
    try:
        while True:
            metrics = fetch_metrics(port)
            now = time.time()
            dt = now - last_time
            
            if metrics:
                render_tui(metrics, last_metrics, dt, peak_rps_map)
                last_metrics = metrics
                last_time = now
            else:
                print(CLEAR)
                print(f"{RED}Could not connect to localhost:{port}{RESET}")
                print(f"Ensure your app is running with analytics_enabled=true")
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print(f"\n{GREY}Exiting monitor.{RESET}")

if __name__ == "__main__":
    main()
