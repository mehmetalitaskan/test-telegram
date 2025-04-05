import os
import asyncio
from telethon.sync import TelegramClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram API credentials
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
PHONE_NUMBER = os.getenv('PHONE_NUMBER')

# Session name
SESSION_NAME = 'telegram_session'

async def authenticate():
    """Authenticate the Telegram client and create session file"""
    print(f"API_ID: {API_ID}")
    print(f"API_HASH: {API_HASH}")
    print(f"PHONE_NUMBER: {PHONE_NUMBER}")
    
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("Need to login...")
        # Send code (automatically sends to PHONE_NUMBER)
        await client.send_code_request(PHONE_NUMBER)
        
        # Ask for the code that Telegram sent
        verification_code = input("Enter the verification code you received: ")
        
        try:
            # Try to sign in with the provided code
            await client.sign_in(PHONE_NUMBER, verification_code)
            print("Successfully logged in!")
        except Exception as e:
            print(f"Error signing in: {e}")
            
            # Check if two-factor authentication is enabled
            if "2FA" in str(e) or "password" in str(e).lower():
                password = input("Enter your two-factor authentication password: ")
                await client.sign_in(password=password)
                print("Successfully logged in with 2FA!")
    else:
        print("Already authenticated!")
        
    # Get and display some account info
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (ID: {me.id})")
    
    # Create listener session by copying the main session
    # Use same auth credentials for listener
    listener_client = TelegramClient(f"{SESSION_NAME}_listener", API_ID, API_HASH)
    await listener_client.connect()
    
    if not await listener_client.is_user_authorized():
        # Copy auth credentials from main session to listener session
        await listener_client.sign_in(phone=PHONE_NUMBER)
        print("Listener session authenticated!")
    else:
        print("Listener session already authenticated!")
    
    # Close connections
    await listener_client.disconnect()
    await client.disconnect()
    
    return True

if __name__ == "__main__":
    # Run the authentication
    loop = asyncio.get_event_loop()
    loop.run_until_complete(authenticate())
    
    print("\nAuthentication complete! You can now run the main API.")
    print("Run: python telegram_api.py")