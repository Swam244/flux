from flux import RedisClient
import sys

def main():
    print("--- Flux Connectivity Test ---")
    
    try:
        client = RedisClient()
        print("[INFO] Client initialized successfully.")

        # Execute PING command
        response = client.ping()
        print(f"[SUCCESS] Redis responded: {response}")

    except RuntimeError as e:
        print(f"[ERROR] Connection failed: {e}")
        print("Ensure Redis is running: 'redis-server'")
        sys.exit(1)
    except ImportError:
        print("[FATAL] Could not import Flux C++ core.")
        sys.exit(1)

if __name__ == "__main__":
    main()