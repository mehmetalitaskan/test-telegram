from flask import Flask, request, jsonify
import os
import sys
import asyncio
import threading
from telethon.sync import TelegramClient
from telethon import events
from telethon.tl.functions.channels import CreateChannelRequest, GetFullChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest
from telethon.tl.types import InputPeerChannel
from telethon.errors.rpcerrorlist import PeerFloodError, UserPrivacyRestrictedError
from dotenv import load_dotenv
import time
import re

# Load environment variables
load_dotenv()

# Telegram API credentials
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
PHONE_NUMBER = os.getenv('PHONE_NUMBER')

# Initialize Flask app
app = Flask(__name__)

# Client session name
SESSION_NAME = 'telegram_session'

# Global variables for message listener
message_listener_client = None
active_listeners = {}  # Dictionary to track active listeners: {group_id: callback_url}
listener_running = False
message_history = {}  # Dictionary to store message history: {group_id: [messages]}

async def create_client_for_request():
    """Create a new client for each request"""
    client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
    await client.connect()
    
    if not await client.is_user_authorized():
        print("You need to authorize the Telegram client first.")
        print("Run the telegram_group_inviter.py script to authenticate.")
        await client.disconnect()
        return None
    
    return client

async def create_telegram_group(client, group_name, group_description):
    """
    Create a new Telegram group (supergroup/channel) with the given name and description
    """
    try:
        # Create a supergroup (channel)
        result = await client(CreateChannelRequest(
            title=group_name,
            about=group_description,
            megagroup=True  # Set to True for supergroups
        ))
        
        channel = result.chats[0]
        return channel, None
    except Exception as e:
        error_msg = f"Error creating group: {e}"
        return None, error_msg

async def get_invite_link(client, channel):
    """
    Generate an invite link for the given channel/group
    """
    try:
        # First approach: Try to get existing invite link
        try:
            full_channel = await client(GetFullChannelRequest(channel))
            if hasattr(full_channel.full_chat, 'invite_link') and full_channel.full_chat.invite_link:
                return full_channel.full_chat.invite_link, None
        except Exception as e:
            print(f"Could not get existing invite link: {e}")
        
        # Second approach: Try to create a new invite link
        try:
            # Create an invite link directly using the client method
            link = await client.export_chat_invite_link(channel.id)
            if link:
                return link, None
        except Exception as e:
            print(f"Could not create invite link with client method: {e}")
        
        # Third approach: Try using the ExportChatInviteRequest
        try:
            # First convert channel to InputPeerChannel
            input_peer = InputPeerChannel(channel.id, channel.access_hash)
            result = await client(ExportChatInviteRequest(peer=input_peer))
            if result and hasattr(result, 'link'):
                return result.link, None
        except Exception as e:
            print(f"Could not create invite link with ExportChatInviteRequest: {e}")
        
        # If all methods fail
        error_msg = "Could not generate invite link after trying multiple methods"
        return None, error_msg
    except Exception as e:
        error_msg = f"Error generating invite link: {e}"
        return None, error_msg

async def send_invites_to_phone_numbers(client, phone_numbers, invite_link, message_text):
    """
    Send invitation messages with the invite link to a list of phone numbers
    """
    results = []
    
    for phone in phone_numbers:
        try:
            # Try to find the user by phone number
            try:
                user = await client.get_entity(phone)
                
                # Send message with invite link
                await client.send_message(
                    user,
                    f"{message_text}\n\n{invite_link}"
                )
                
                results.append({
                    "phone": phone,
                    "status": "success",
                    "message": "Invitation sent successfully"
                })
                
                # Sleep to avoid hitting rate limits
                time.sleep(1)
                
            except Exception as e:
                results.append({
                    "phone": phone,
                    "status": "error",
                    "message": f"Could not find user: {str(e)}"
                })
                
        except PeerFloodError:
            results.append({
                "phone": phone,
                "status": "error",
                "message": "Telegram flood error. Try again later."
            })
        except UserPrivacyRestrictedError:
            results.append({
                "phone": phone,
                "status": "error",
                "message": "User has privacy restrictions"
            })
        except Exception as e:
            results.append({
                "phone": phone,
                "status": "error",
                "message": str(e)
            })
    
    return results

async def extract_group_entity_from_link(client, invite_link):
    """
    Extract group entity from invite link
    """
    try:
        # Join the group using the invite link if not already a member
        try:
            # Extract the group username or hash from the link
            if 't.me/' in invite_link:
                if '+' in invite_link:
                    # This is a private group invite link (e.g., https://t.me/+abcdef123456)
                    # We need to join the group first
                    group_entity = await client.get_entity(invite_link)
                    await client(JoinChannelRequest(group_entity))
                else:
                    # This is a public group/channel (e.g., https://t.me/groupname)
                    username = invite_link.split('t.me/')[1].strip('/')
                    group_entity = await client.get_entity(username)
            else:
                return None, "Invalid invite link format"
                
            return group_entity, None
        except Exception as e:
            error_msg = f"Error joining group: {e}"
            return None, error_msg
    except Exception as e:
        error_msg = f"Error extracting group from link: {e}"
        return None, error_msg

async def send_message_as_user_to_group(client, group_entity, sender_name, sender_phone, message_text):
    """
    Send a message to a group that appears to be from another user
    """
    try:
        # Format message to appear from the user
        formatted_message = f"📱 **Mesaj: {sender_name} ({sender_phone})** 📱\n\n{message_text}"
        
        # Send the formatted message
        await client.send_message(group_entity, formatted_message)
        
        return True, None
    except Exception as e:
        error_msg = f"Error sending message to group: {e}"
        return False, error_msg

async def start_message_listener():
    """
    Start a background client that listens for messages in groups
    """
    global message_listener_client
    global listener_running
    
    # Only start if not already running
    if listener_running:
        return True
    
    try:
        # Use a completely different session name for the listener
        listener_session = f"{SESSION_NAME}_listener_separate"
        
        # Initialize the message listener client with a separate session
        message_listener_client = TelegramClient(listener_session, API_ID, API_HASH)
        await message_listener_client.connect()
        
        if not await message_listener_client.is_user_authorized():
            print("Listener client needs authorization. Starting authorization process...")
            # Copy auth from main session
            try:
                # First try to log in using the phone number from .env
                await message_listener_client.start(phone=PHONE_NUMBER)
                print("Listener client authorized successfully!")
            except Exception as e:
                print(f"Failed to authorize listener client: {e}")
                return False
        
        # Register the message handler
        @message_listener_client.on(events.NewMessage())
        async def message_handler(event):
            """Handle new messages in any chat"""
            try:
                # Check if this is a message from a group we're listening to
                chat = await event.get_chat()
                chat_id = chat.id
                
                if chat_id in active_listeners:
                    # Get message details
                    message = event.message
                    sender = await event.get_sender()
                    
                    # Extract sender info
                    sender_info = {
                        "id": sender.id,
                        "first_name": getattr(sender, 'first_name', None),
                        "last_name": getattr(sender, 'last_name', None),
                        "username": getattr(sender, 'username', None),
                        "phone": getattr(sender, 'phone', None)
                    }
                    
                    # Create message info
                    message_info = {
                        "id": message.id,
                        "text": message.text,
                        "date": message.date.isoformat(),
                        "sender": sender_info
                    }
                    
                    # Add to message history
                    if chat_id not in message_history:
                        message_history[chat_id] = []
                    
                    message_history[chat_id].append(message_info)
                    
                    # Keep only the last 100 messages
                    if len(message_history[chat_id]) > 100:
                        message_history[chat_id] = message_history[chat_id][-100:]
                    
                    # Format sender name
                    sender_name = f"{sender_info['first_name'] or ''} {sender_info['last_name'] or ''}".strip()
                    if not sender_name and sender_info['username']:
                        sender_name = f"@{sender_info['username']}"
                    if not sender_name:
                        sender_name = f"ID: {sender_info['id']}"
                    
                    # Print detailed message info to console
                    print("\n" + "="*50)
                    print(f"💬 YENİ MESAJ ALINDI: {chat.title}")
                    print(f"📅 Tarih: {message.date.strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"👤 Gönderen: {sender_name}")
                    if sender_info['username']:
                        print(f"🔖 Kullanıcı Adı: @{sender_info['username']}")
                    print(f"🆔 Kullanıcı ID: {sender_info['id']}")
                    if sender_info['phone']:
                        print(f"📱 Telefon: {sender_info['phone']}")
                    print(f"📝 Mesaj: {message.text}")
                    
                    # If message has media, show that as well
                    if message.media:
                        print(f"📷 Medya: {type(message.media).__name__}")
                    
                    # If message is a reply to another message
                    if message.reply_to:
                        print(f"↩️ Yanıt Verilen Mesaj ID: {message.reply_to.reply_to_msg_id}")
                    
                    print("="*50 + "\n")
            except Exception as e:
                print(f"Error in message handler: {e}")
        
        # Start the client
        listener_running = True
        print("Message listener started successfully")
        return True
        
    except Exception as e:
        print(f"Error starting message listener: {e}")
        return False

async def stop_message_listener():
    """
    Stop the message listener client
    """
    global message_listener_client
    global listener_running
    
    if message_listener_client and listener_running:
        await message_listener_client.disconnect()
        message_listener_client = None
        listener_running = False
        print("Message listener stopped")
        return True
    
    return False

async def add_group_to_listeners(group_link):
    """
    Add a group to the active listeners
    """
    global active_listeners
    
    # Create a temporary client to get the group entity
    client = await create_client_for_request()
    if not client:
        return None, "Failed to initialize client"
    
    try:
        # Get the group entity
        group_entity, error = await extract_group_entity_from_link(client, group_link)
        if error:
            await client.disconnect()
            return None, error
        
        # Add to active listeners
        group_id = group_entity.id
        active_listeners[group_id] = group_link
        
        # Initialize message history for this group
        if group_id not in message_history:
            message_history[group_id] = []
        
        await client.disconnect()
        return group_entity, None
    except Exception as e:
        await client.disconnect()
        return None, f"Error adding group to listeners: {e}"

def run_listener_in_background():
    """
    Run the message listener in a background thread
    """
    async def _run_listener():
        success = await start_message_listener()
        if success:
            # Keep the client running indefinitely
            while listener_running:
                await asyncio.sleep(1)
    
    # Run in a new thread
    def _thread_target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run_listener())
    
    thread = threading.Thread(target=_thread_target)
    thread.daemon = True  # Thread will exit when the main program exits
    thread.start()
    return thread

@app.route('/create-telegram-group', methods=['POST'])
def create_group():
    """
    API endpoint to create a Telegram group and invite users
    
    Expected JSON input:
    {
        "group_name": "Group Name",
        "group_description": "Group Description",
        "phones": ["+905551112233", "+905551112244"],
        "invite_message": "You are invited to join our group!"
    }
    """
    # Get request data
    data = request.json
    
    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    if 'group_name' not in data:
        return jsonify({"error": "group_name is required"}), 400
    
    if 'phones' not in data or not isinstance(data['phones'], list):
        return jsonify({"error": "phones list is required"}), 400
    
    # Extract data
    group_name = data['group_name']
    group_description = data.get('group_description', f"Group created via API: {group_name}")
    phones = data['phones']
    invite_message = data.get('invite_message', f"You are invited to join the group: {group_name}")
    
    # Create async function to handle the process
    async def process_request():
        # Create a new client for this request
        client = await create_client_for_request()
        if client is None:
            return {"error": "Failed to initialize Telegram client"}, 500
        
        try:
            # Create the group
            channel, error = await create_telegram_group(client, group_name, group_description)
            
            if error:
                return {"error": error}, 500
            
            # Generate invite link
            invite_link, error = await get_invite_link(client, channel)
            
            if error:
                return {"error": error}, 500
            
            # Send invites
            invite_results = await send_invites_to_phone_numbers(client, phones, invite_link, invite_message)
            
            # Return the result
            return {
                "success": True,
                "group": {
                    "name": group_name,
                    "invite_link": invite_link
                },
                "invitations": invite_results
            }, 200
        finally:
            # Always disconnect the client when done
            await client.disconnect()
    
    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, status_code = loop.run_until_complete(process_request())
    loop.close()
    
    # Return the result
    return jsonify(result), status_code

@app.route('/send-telegram-group-message', methods=['POST'])
def send_group_message():
    """
    API endpoint to send a message to a Telegram group
    
    Expected JSON input:
    {
        "group_link": "https://t.me/+abcdef123456",
        "sender_name": "John Doe",
        "sender_phone": "+905551112233",
        "message": "Hello, this is a test message!"
    }
    """
    # Get request data
    data = request.json
    
    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    if 'group_link' not in data:
        return jsonify({"error": "group_link is required"}), 400
    
    if 'sender_name' not in data:
        return jsonify({"error": "sender_name is required"}), 400
    
    if 'sender_phone' not in data:
        return jsonify({"error": "sender_phone is required"}), 400
    
    if 'message' not in data:
        return jsonify({"error": "message is required"}), 400
    
    # Extract data
    group_link = data['group_link']
    sender_name = data['sender_name']
    sender_phone = data['sender_phone']
    message = data['message']
    
    # Create async function to handle the process
    async def process_request():
        # Create a new client for this request
        client = await create_client_for_request()
        if client is None:
            return {"error": "Failed to initialize Telegram client"}, 500
        
        try:
            # Get group entity from link
            group_entity, error = await extract_group_entity_from_link(client, group_link)
            
            if error:
                return {"error": error}, 500
            
            # Send message
            success, error = await send_message_as_user_to_group(client, group_entity, sender_name, sender_phone, message)
            
            if error:
                return {"error": error}, 500
            
            # Return the result
            return {
                "success": True,
                "group_link": group_link,
                "message": "Message sent successfully"
            }, 200
        finally:
            # Always disconnect the client when done
            await client.disconnect()
    
    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, status_code = loop.run_until_complete(process_request())
    loop.close()
    
    # Return the result
    return jsonify(result), status_code

@app.route('/listen-to-group', methods=['POST'])
def listen_to_group():
    """
    API endpoint to start listening to messages in a Telegram group
    
    Expected JSON input:
    {
        "group_links": ["https://t.me/+abcdef123456", "https://t.me/groupname"]
    }
    
    You can also provide a single group link:
    {
        "group_link": "https://t.me/+abcdef123456"
    }
    """
    # Get request data
    data = request.json
    
    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    group_links = []
    
    # Handle both single group_link and multiple group_links
    if 'group_link' in data:
        group_links.append(data['group_link'])
    elif 'group_links' in data and isinstance(data['group_links'], list):
        group_links = data['group_links']
    else:
        return jsonify({"error": "Either group_link or group_links (array) is required"}), 400
    
    if not group_links:
        return jsonify({"error": "No valid group links provided"}), 400
    
    # Create async function to handle the process
    async def process_request():
        # Make sure the listener is running
        global listener_running
        if not listener_running:
            # Start the listener in a background thread
            run_listener_in_background()
            # Wait for the listener to start
            for _ in range(5):  # Wait up to 5 seconds
                if listener_running:
                    break
                await asyncio.sleep(1)
        
        if not listener_running:
            return {"error": "Failed to start message listener"}, 500
        
        results = []
        errors = []
        
        # Add each group to the listeners
        for group_link in group_links:
            group_entity, error = await add_group_to_listeners(group_link)
            
            if error:
                errors.append({
                    "group_link": group_link,
                    "error": error
                })
            else:
                results.append({
                    "id": group_entity.id,
                    "title": group_entity.title,
                    "link": group_link
                })
        
        # Return the result
        return {
            "success": len(results) > 0,
            "groups": results,
            "errors": errors,
            "message": f"Now listening to {len(results)} group(s)" if results else "Failed to listen to any groups"
        }, 200 if results else 500
    
    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, status_code = loop.run_until_complete(process_request())
    loop.close()
    
    # Return the result
    return jsonify(result), status_code

@app.route('/get-group-messages', methods=['POST'])
def get_group_messages():
    """
    API endpoint to get messages from a Telegram group
    
    Expected JSON input:
    {
        "group_link": "https://t.me/+abcdef123456"
    }
    """
    # Get request data
    data = request.json
    
    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    if 'group_link' not in data:
        return jsonify({"error": "group_link is required"}), 400
    
    group_link = data['group_link']
    
    # Create async function to handle the process
    async def process_request():
        # Create a temporary client
        client = await create_client_for_request()
        if not client:
            return {"error": "Failed to initialize client"}, 500
        
        try:
            # Get the group entity
            group_entity, error = await extract_group_entity_from_link(client, group_link)
            if error:
                return {"error": error}, 500
            
            # Check if we're listening to this group
            group_id = group_entity.id
            if group_id not in active_listeners:
                # Add it to listeners if not already listening
                await add_group_to_listeners(group_link)
                return {
                    "success": True,
                    "group": {
                        "id": group_id,
                        "title": group_entity.title,
                        "link": group_link
                    },
                    "messages": [],
                    "message": "Started listening to group, no messages yet"
                }, 200
            
            # Get messages for this group
            messages = message_history.get(group_id, [])
            
            # Return the result
            return {
                "success": True,
                "group": {
                    "id": group_id,
                    "title": group_entity.title,
                    "link": group_link
                },
                "messages": messages
            }, 200
        finally:
            await client.disconnect()
    
    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, status_code = loop.run_until_complete(process_request())
    loop.close()
    
    # Return the result
    return jsonify(result), status_code

@app.route('/stop-listening', methods=['POST'])
def stop_listening():
    """
    API endpoint to stop listening to messages in a Telegram group
    
    Expected JSON input:
    {
        "group_link": "https://t.me/+abcdef123456"
    }
    """
    # Get request data
    data = request.json
    
    # Validate input
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    if 'group_link' not in data:
        return jsonify({"error": "group_link is required"}), 400
    
    group_link = data['group_link']
    
    # Create async function to handle the process
    async def process_request():
        # Create a temporary client
        client = await create_client_for_request()
        if not client:
            return {"error": "Failed to initialize client"}, 500
        
        try:
            # Get the group entity
            group_entity, error = await extract_group_entity_from_link(client, group_link)
            if error:
                return {"error": error}, 500
            
            # Check if we're listening to this group
            group_id = group_entity.id
            if group_id in active_listeners:
                # Remove from active listeners
                del active_listeners[group_id]
                
                # Clear message history for this group
                if group_id in message_history:
                    del message_history[group_id]
                
                # If no more active listeners, stop the listener
                if not active_listeners and listener_running:
                    await stop_message_listener()
                
                return {
                    "success": True,
                    "message": f"Stopped listening to group: {group_entity.title}"
                }, 200
            else:
                return {
                    "success": False,
                    "message": "Not listening to this group"
                }, 400
        finally:
            await client.disconnect()
    
    # Run the async function
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    result, status_code = loop.run_until_complete(process_request())
    loop.close()
    
    # Return the result
    return jsonify(result), status_code

# Initialize the message listener when the app starts
if __name__ == '__main__':
    # Start the message listener in a background thread
    run_listener_in_background()
    
    # Run Flask app
    app.run(debug=True, port=5000)