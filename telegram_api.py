from flask import Flask, request, jsonify
import os
import sys
import asyncio
from telethon.sync import TelegramClient
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

if __name__ == '__main__':
    # Run Flask app
    app.run(debug=True, port=5000)