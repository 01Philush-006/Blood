import discord
from discord.ext import commands
import os
from datetime import datetime
import json
from typing import Dict, Optional
import asyncio
from flask import Flask, request, jsonify
from threading import Thread
import ipaddress

# Initialize bot with intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

bot = commands.Bot(command_prefix='!', intents=intents)

# Storage class for managing data
class Storage:
    def __init__(self):
        self.urls: Dict[str, dict] = {}
        self.servers: Dict[str, dict] = {}
        self.logs: Dict[str, list] = {}

    def add_server(self, guild_id: str, settings: dict = None):
        if settings is None:
            settings = {
                'logging_enabled': False,
                'security_channel': None,
                'server_log_channel': None,
                'message_log_channel': None
            }
        self.servers[guild_id] = settings
        self.logs[guild_id] = []

    def log_event(self, guild_id: str, event: str):
        if guild_id in self.logs:
            self.logs[guild_id].append({
                'timestamp': datetime.now().isoformat(),
                'event': event
            })

storage = Storage()

# Bot event handlers
@bot.event
async def on_ready():
    print(f'Bot logged in as {bot.user}')
    for guild in bot.guilds:
        storage.add_server(str(guild.id))

@bot.event
async def on_guild_join(guild):
    storage.add_server(str(guild.id))
    print(f'Joined new guild: {guild.name}')

@bot.event
async def on_member_join(member):
    channel = member.guild.system_channel
    if channel:
        await channel.send(f'Welcome {member.mention} to the server!')
    storage.log_event(str(member.guild.id), f'Member joined: {member.name}')

# URL Management Commands
@bot.command(name='createurl')
async def create_url(ctx, original_url: str, alias: str = None):
    if not original_url.startswith(('http://', 'https://')):
        await ctx.send('❌ Please provide a valid URL starting with http:// or https://')
        return

    short_code = alias or str(len(storage.urls) + 1)
    storage.urls[short_code] = {
        'original_url': original_url,
        'created_by': ctx.author.id,
        'created_at': datetime.now(),
        'usage_count': 0
    }

    base_url = os.getenv('REPLIT_DOMAINS', 'your-repl-url.replit.app').split(',')[0]
    short_url = f'https://{base_url}/u/{short_code}'

    await ctx.send(f'✅ URL created successfully!\nShort URL: {short_url}')

@bot.command(name='deleteurl')
async def delete_url(ctx, short_code: str):
    if short_code not in storage.urls:
        await ctx.send('❌ URL not found')
        return

    url_data = storage.urls[short_code]
    if url_data['created_by'] != ctx.author.id and not ctx.author.guild_permissions.manage_messages:
        await ctx.send('❌ You do not have permission to delete this URL')
        return

    del storage.urls[short_code]
    await ctx.send('✅ URL deleted successfully!')

@bot.command(name='urls')
async def list_urls(ctx, page: int = 1):
    if not storage.urls:
        await ctx.send('No URLs found.')
        return

    items_per_page = 5
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page

    url_list = list(storage.urls.items())[start_idx:end_idx]
    if not url_list:
        await ctx.send(f'❌ Invalid page number. Max page: {len(storage.urls) // items_per_page + 1}')
        return

    base_url = os.getenv('REPLIT_DOMAINS', 'your-repl-url.replit.app').split(',')[0]
    response = f'📋 URLs (Page {page}/{len(storage.urls) // items_per_page + 1}):\n\n'

    for short_code, data in url_list:
        short_url = f'https://{base_url}/u/{short_code}'
        original_url = data['original_url']
        created_at = data['created_at'].strftime('%Y-%m-%d %H:%M:%S')
        response += f'• {short_url} → {original_url[:30]}{"..." if len(original_url) > 30 else ""}\n'
        response += f'  Created: {created_at}\n'
        response += f'  Uses: {data["usage_count"]}\n\n'

    await ctx.send(response)

# Setup Command
@bot.command(name='setup')
@commands.has_permissions(administrator=True)
async def setup(ctx):
    guild = ctx.guild
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True)
    }

    channels = {
        'security-logs': 'Security events logging',
        'server-logs': 'Server events logging',
        'message-logs': 'Message events logging'
    }

    created_channels = {}
    for name, topic in channels.items():
        channel = await guild.create_text_channel(
            name,
            topic=topic,
            overwrites=overwrites
        )
        created_channels[name] = channel

    storage.servers[str(guild.id)] = {
        'logging_enabled': True,
        'security_channel': created_channels['security-logs'].id,
        'server_log_channel': created_channels['server-logs'].id,
        'message_log_channel': created_channels['message-logs'].id
    }

    response = "✅ Setup completed!\n\n"
    for name, channel in created_channels.items():
        response += f"📊 {name}: {channel.mention}\n"

    await ctx.send(response)

@bot.command(name='help')
async def help_command(ctx):
    help_text = """
**BLOODFORGED SENTINEL Bot Commands**

**🛠️ Setup Commands**
`!setup` - Initialize bot setup
`!help` - Show this help message

**🔗 URL System Commands**
`!createurl [url] [optional: alias]` - Create a new short URL
`!deleteurl [shortcode]` - Delete a short URL
`!urls [page]` - List all URLs (paginated)

For more help, contact server administrators.
"""
    await ctx.send(help_text)

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.errors.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this command!")
    elif isinstance(error, commands.errors.MissingRequiredArgument):
        await ctx.send("❌ Missing required argument! Use !help to see command usage.")
    else:
        await ctx.send(f"❌ An error occurred: {str(error)}")

# Flask app for internal network endpoint
app = Flask(__name__)

@app.route('/api/private/internal', methods=['POST'])
def internal_endpoint():
    # Process internal command
    data = request.get_json()
    command = data.get('command')

    if not command:
        return jsonify({'error': 'Command required'}), 400

    # Handle internal commands
    if command == 'status':
        return jsonify({
            'status': 'ok',
            'serverCount': len(bot.guilds),
            'userCount': sum(g.member_count for g in bot.guilds),
            'uptime': datetime.now().timestamp() - bot.user.created_at.timestamp() if bot.user else 0
        })

    return jsonify({'error': 'Invalid command'}), 400

@app.before_request
def check_private_network():
    # Allow internal Railway network
    if request.headers.get('X-Railway-Auth'):
        return None
    # Check private network ranges
    client_ip = request.remote_addr
    private_ranges = [
        ipaddress.ip_network('10.0.0.0/8'),
        ipaddress.ip_network('172.16.0.0/12'),
        ipaddress.ip_network('192.168.0.0/16')
    ]
    try:
        client_ip_obj = ipaddress.ip_address(client_ip)
        if not any(client_ip_obj in network for network in private_ranges):
            return jsonify({'error': 'Access denied'}), 403
    except ValueError:
        return jsonify({'error': 'Invalid IP'}), 400
    return None


# Main execution
if __name__ == "__main__":
    TOKEN = os.getenv('DISCORD_BOT_TOKEN')
    if not TOKEN:
        raise ValueError('DISCORD_BOT_TOKEN not found in environment variables')

    # Run Flask in a separate thread
    thread = Thread(target=app.run, kwargs={
        'host': '0.0.0.0',
        'port': 5000,
        'ssl_context': 'adhoc' if os.getenv('PRODUCTION') else None
    })
    thread.start()

    # Run Discord bot
    bot.run(TOKEN)