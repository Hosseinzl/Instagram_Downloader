import asyncio
import random
import requests
from service import download  # Save the provided code as main.py

async def main():
    # Example Instagram post URL
    url = "https://www.instagram.com/reel/DO0RUBgiBe-/?igsh=MTdwNWZ2dm5icXQxOQ=="
    
    max_attempts = 100  # Maximum number of requests to test
    success_count = 0   # Track successful requests

    for attempt in range(1, max_attempts + 1):
        delay_between_requests = random.randint(2, 10)  # Seconds to wait between requests to avoid immediate blocking

        print(f"Attempt {attempt}/{max_attempts}: Requesting URL...")
        try:
            # Call the download function
            result, status_code = await download(url)
            
            if result:
                success_count += 1
                print(f"Success {success_count}: Post Code: {result['code']}, Type: {result['type']}, Status Code: {status_code}")
                # print(f"  Caption: {result['caption'][:50]}...")  # Truncate for brevity
                # print(f"  Images: {result['images']}")
                print(f"  Video: {result['video']}")
                # print(f"  Carousel: {result['carousel']}")
            else:
                print(f"Attempt {attempt} failed: No data returned (Status Code: {status_code}).")
                if status_code in [429, 403]:
                    print(f"Likely IP blocked (Status Code: {status_code}).")
                    break
                break  # Stop on failure (adjust if you want to continue)

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if hasattr(e, 'response') else None
            print(f"Attempt {attempt} failed: HTTP {status_code} - {e}")
            if status_code in [429, 403]:
                print(f"Likely IP blocked (Status Code: {status_code}).")
                break
            break  # Stop on other HTTP errors
        except Exception as e:
            print(f"Attempt {attempt} failed: {e} (Status Code: {status_code})")
            break  # Stop on any other error (e.g., connection issues)

        print(f"Waiting {delay_between_requests} seconds before next request...")
        await asyncio.sleep(delay_between_requests)

    print(f"\nTest complete: {success_count} successful requests before stopping.")
    if success_count < max_attempts:
        print("Stopped due to failure or potential IP block.")
    else:
        print("Reached maximum attempts without being blocked.")

if __name__ == "__main__":
    asyncio.run(main())