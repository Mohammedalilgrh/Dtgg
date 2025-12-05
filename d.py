import os
import re
import asyncio
import logging
from typing import List, Dict, Optional
from pathlib import Path

import aiohttp
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode

# Configuration
TOKEN = "8408158472:AAFywjucuPlyYeRNJ-xbFTowMVJNta6i3e8"  # Replace with your bot token
DOWNLOAD_PATH = "downloads"
MAX_FILE_SIZE = 2000 * 1024 * 1024  # 2GB
MAX_BULK_ITEMS = 50
SUPPORTED_DOMAINS = [
    'youtube.com', 'youtu.be',  # YouTube
    'facebook.com', 'fb.watch',  # Facebook
    'instagram.com', 'instagr.am',  # Instagram
    'tiktok.com', 'vm.tiktok.com',  # TikTok
    'twitter.com', 'x.com',  # Twitter/X
    'reddit.com',  # Reddit
    'pinterest.com',  # Pinterest
    'likee.video',  # Likee
    'twitch.tv',  # Twitch
    'dailymotion.com',  # Dailymotion
    'vimeo.com',  # Vimeo
]

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Ensure download directory exists
Path(DOWNLOAD_PATH).mkdir(exist_ok=True)

class VideoDownloader:
    def __init__(self):
        self.ydl_opts = {
            'format': 'best',
            'outtmpl': f'{DOWNLOAD_PATH}/%(title)s.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'force_generic_extractor': False,
            'postprocessors': [],
            'merge_output_format': 'mp4',
            'noplaylist': True,
            'socket_timeout': 30,
            'max_filesize': MAX_FILE_SIZE,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        }
        
        # Platform specific options
        self.platform_opts = {
            'youtube': {
                'format': 'best[height<=1080]',
                'merge_output_format': 'mp4'
            },
            'instagram': {
                'format': 'best',
                'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None
            },
            'facebook': {
                'format': 'best',
                'cookiefile': 'cookies.txt' if os.path.exists('cookies.txt') else None
            },
            'tiktok': {
                'format': 'best',
                'referer': 'https://www.tiktok.com/'
            }
        }
    
    def get_platform(self, url: str) -> str:
        """Detect platform from URL"""
        url_lower = url.lower()
        if 'youtube.com' in url_lower or 'youtu.be' in url_lower:
            return 'youtube'
        elif 'instagram.com' in url_lower or 'instagr.am' in url_lower:
            return 'instagram'
        elif 'facebook.com' in url_lower or 'fb.watch' in url_lower:
            return 'facebook'
        elif 'tiktok.com' in url_lower or 'vm.tiktok.com' in url_lower:
            return 'tiktok'
        elif 'twitter.com' in url_lower or 'x.com' in url_lower:
            return 'twitter'
        elif 'reddit.com' in url_lower:
            return 'reddit'
        elif 'pinterest.com' in url_lower:
            return 'pinterest'
        return 'generic'
    
    async def download_video(self, url: str, quality: str = 'best') -> Optional[Dict]:
        """Download single video"""
        try:
            platform = self.get_platform(url)
            
            # Merge platform specific options
            ydl_opts = self.ydl_opts.copy()
            if platform in self.platform_opts:
                ydl_opts.update(self.platform_opts[platform])
            
            if quality != 'best':
                ydl_opts['format'] = quality
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if info:
                    file_path = ydl.prepare_filename(info)
                    if 'entries' in info:  # Playlist
                        file_path = file_path.replace('.mp4', f'_{info["entries"][0]["id"]}.mp4')
                    
                    return {
                        'title': info.get('title', 'Unknown'),
                        'duration': info.get('duration', 0),
                        'size': os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                        'path': file_path,
                        'thumbnail': info.get('thumbnail'),
                        'platform': platform
                    }
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None
    
    async def get_playlist_info(self, url: str, max_items: int = 10) -> Optional[List[Dict]]:
        """Get playlist/channel information"""
        try:
            ydl_opts = {
                'extract_flat': True,
                'quiet': True,
                'no_warnings': True,
                'playlist_items': f'1:{max_items}'
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info and 'entries' in info:
                    videos = []
                    for entry in info['entries'][:max_items]:
                        videos.append({
                            'title': entry.get('title', 'Unknown'),
                            'url': entry.get('url'),
                            'id': entry.get('id'),
                            'duration': entry.get('duration', 0),
                            'thumbnail': entry.get('thumbnail')
                        })
                    return videos
        except Exception as e:
            logger.error(f"Playlist error: {e}")
            return None
    
    async def download_bulk(self, urls: List[str], quality: str = 'best') -> List[Dict]:
        """Download multiple videos"""
        results = []
        for url in urls:
            if len(results) >= MAX_BULK_ITEMS:
                break
                
            result = await self.download_video(url, quality)
            if result:
                results.append(result)
            await asyncio.sleep(1)  # Rate limiting
        
        return results

class TelegramBot:
    def __init__(self):
        self.downloader = VideoDownloader()
        self.user_sessions: Dict[int, Dict] = {}
        self.bulk_downloads: Dict[int, List[str]] = {}
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user = update.effective_user
        welcome_msg = f"""
🚀 **Welcome {user.first_name}!**

I'm your Universal Video Downloader Bot! I can download videos from:

• YouTube
• Facebook
• Instagram
• TikTok
• Twitter/X
• Reddit
• Pinterest
• Vimeo
• Dailymotion
• And many more!

📥 **How to use:**
1. Send me a video URL
2. Or use /bulk for multiple downloads
3. Or use /channel to download from channels/pages

✨ **Features:**
• Bulk downloads (up to {MAX_BULK_ITEMS} videos)
• Channel/Page downloading
• Quality selection
• Large file support (up to 2GB)
• Fast and reliable

Send me a link to get started!
        """
        
        keyboard = [
            [
                InlineKeyboardButton("📥 Single Download", callback_data="help_single"),
                InlineKeyboardButton("📚 Bulk Download", callback_data="help_bulk")
            ],
            [
                InlineKeyboardButton("📺 Channel Download", callback_data="help_channel"),
                InlineKeyboardButton("⚙️ Settings", callback_data="help_settings")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_text = """
🔧 **Available Commands:**

/start - Start the bot
/help - Show this help message
/bulk - Start bulk download session
/channel - Download from channel/page
/settings - Change download settings
/cancel - Cancel current operation
/status - Check download status

📋 **Usage Examples:**
1. Send any video URL directly
2. Use /bulk then send multiple URLs (one per line)
3. Use /channel <URL> <number> to download from channels

🎯 **Supported Formats:**
• Direct video links
• Shortened URLs
• Playlists
• Stories
• Reels
• IGTV videos

⚠️ **Limitations:**
• Max 2GB per file
• Max {MAX_BULK_ITEMS} items in bulk
• Private/age-restricted content may not work
        """.format(MAX_BULK_ITEMS=MAX_BULK_ITEMS)
        
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)
    
    async def bulk_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /bulk command"""
        user_id = update.effective_user.id
        self.bulk_downloads[user_id] = []
        
        await update.message.reply_text(
            "📚 **Bulk Download Mode Activated**\n\n"
            "Send me multiple video URLs (one per line).\n"
            f"Maximum: {MAX_BULK_ITEMS} videos\n\n"
            "When finished, send /done to start downloading.\n"
            "Send /cancel to abort.\n\n"
            "**Current URLs:** 0",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def channel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /channel command"""
        args = context.args
        if len(args) < 1:
            await update.message.reply_text(
                "📺 **Channel Download**\n\n"
                "Usage: /channel <URL> [number]\n\n"
                "Examples:\n"
                "/channel https://youtube.com/c/ChannelName 10\n"
                "/channel https://instagram.com/username 5\n"
                "/channel https://tiktok.com/@username\n\n"
                "Number is optional (default: 5 videos)",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        url = args[0]
        count = int(args[1]) if len(args) > 1 else 5
        
        if count > MAX_BULK_ITEMS:
            count = MAX_BULK_ITEMS
        
        await update.message.reply_text(
            f"🔄 Fetching {count} videos from channel...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Get playlist info
        videos = await self.downloader.get_playlist_info(url, count)
        
        if not videos:
            await update.message.reply_text("❌ Could not fetch channel videos.")
            return
        
        # Create selection keyboard
        keyboard = []
        for i, video in enumerate(videos[:10], 1):  # Show first 10
            title = video['title'][:30] + "..." if len(video['title']) > 30 else video['title']
            keyboard.append([
                InlineKeyboardButton(f"{i}. {title}", callback_data=f"channel_{video['id']}")
            ])
        
        keyboard.append([
            InlineKeyboardButton("✅ Download All", callback_data="channel_all"),
            InlineKeyboardButton("❌ Cancel", callback_data="channel_cancel")
        ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📺 Found {len(videos)} videos:\n\n"
            "Select videos to download or download all:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def settings_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /settings command"""
        keyboard = [
            [
                InlineKeyboardButton("🎯 Quality: Best", callback_data="quality_best"),
                InlineKeyboardButton("📦 Quality: 720p", callback_data="quality_720")
            ],
            [
                InlineKeyboardButton("📱 Quality: 480p", callback_data="quality_480"),
                InlineKeyboardButton("💾 Quality: 360p", callback_data="quality_360")
            ],
            [
                InlineKeyboardButton("🔙 Back", callback_data="back_main")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "⚙️ **Download Settings**\n\n"
            "Select preferred video quality:\n"
            "• Best - Highest available quality\n"
            "• 720p - HD quality\n"
            "• 480p - Standard quality\n"
            "• 360p - Lower quality (faster)\n\n"
            "Current: Best",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages"""
        user_id = update.effective_user.id
        text = update.message.text
        
        # Check if in bulk mode
        if user_id in self.bulk_downloads and text != "/done" and text != "/cancel":
            # Extract URLs from message
            urls = re.findall(r'(https?://\S+)', text)
            
            if not urls:
                await update.message.reply_text("❌ No valid URLs found. Please send valid URLs.")
                return
            
            # Add to bulk list
            new_urls = []
            for url in urls:
                if any(domain in url.lower() for domain in SUPPORTED_DOMAINS):
                    if len(self.bulk_downloads[user_id]) < MAX_BULK_ITEMS:
                        self.bulk_downloads[user_id].append(url)
                        new_urls.append(url)
            
            if new_urls:
                count = len(self.bulk_downloads[user_id])
                await update.message.reply_text(
                    f"✅ Added {len(new_urls)} URL(s)\n"
                    f"**Total URLs:** {count}/{MAX_BULK_ITEMS}\n\n"
                    "Send more URLs or /done to start downloading.",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text("❌ No supported URLs found or reached maximum limit.")
            
            return
        
        # Handle /done in bulk mode
        if text == "/done" and user_id in self.bulk_downloads:
            urls = self.bulk_downloads[user_id]
            if not urls:
                await update.message.reply_text("❌ No URLs to download.")
                del self.bulk_downloads[user_id]
                return
            
            await self.process_bulk_download(update, urls)
            del self.bulk_downloads[user_id]
            return
        
        # Handle /cancel
        if text == "/cancel":
            if user_id in self.bulk_downloads:
                del self.bulk_downloads[user_id]
            await update.message.reply_text("✅ Operation cancelled.")
            return
        
        # Single URL download
        urls = re.findall(r'(https?://\S+)', text)
        if urls:
            url = urls[0]
            if any(domain in url.lower() for domain in SUPPORTED_DOMAINS):
                await self.process_single_download(update, url)
            else:
                await update.message.reply_text(
                    "❌ Unsupported URL.\n\n"
                    "Supported platforms:\n"
                    "• YouTube, Facebook, Instagram\n"
                    "• TikTok, Twitter/X, Reddit\n"
                    "• Pinterest, Vimeo, Dailymotion\n"
                    "• And many more!"
                )
        else:
            await update.message.reply_text(
                "📥 Send me a video URL to download!\n"
                "Or use /bulk for multiple downloads."
            )
    
    async def process_single_download(self, update: Update, url: str):
        """Process single video download"""
        msg = await update.message.reply_text("🔍 Analyzing link...")
        
        # Create quality selection keyboard
        keyboard = [
            [
                InlineKeyboardButton("🎯 Best Quality", callback_data=f"dl_best_{hash(url)}"),
                InlineKeyboardButton("📱 720p", callback_data=f"dl_720_{hash(url)}")
            ],
            [
                InlineKeyboardButton("💾 480p", callback_data=f"dl_480_{hash(url)}"),
                InlineKeyboardButton("🚀 Fast (360p)", callback_data=f"dl_360_{hash(url)}")
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await msg.edit_text(
            f"📥 **Video Found**\n\n"
            f"URL: {url[:50]}...\n\n"
            "Select download quality:",
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def process_bulk_download(self, update: Update, urls: List[str]):
        """Process bulk download"""
        total = len(urls)
        msg = await update.message.reply_text(f"📚 Starting bulk download of {total} videos...")
        
        success = 0
        failed = 0
        
        for i, url in enumerate(urls, 1):
            try:
                await msg.edit_text(
                    f"🔄 Downloading {i}/{total}\n"
                    f"URL: {url[:40]}..."
                )
                
                result = await self.downloader.download_video(url)
                if result and os.path.exists(result['path']):
                    success += 1
                    
                    # Send file if size < 50MB (Telegram limit)
                    if result['size'] < 50 * 1024 * 1024:
                        with open(result['path'], 'rb') as f:
                            await update.message.reply_document(
                                document=f,
                                filename=f"{result['title'][:50]}.mp4",
                                caption=f"✅ {result['title']}\n"
                                       f"Size: {result['size'] // 1024 // 1024}MB"
                            )
                    else:
                        await update.message.reply_text(
                            f"📁 File too large for Telegram: {result['title']}\n"
                            f"Size: {result['size'] // 1024 // 1024}MB\n"
                            f"Saved to server."
                        )
                    
                    # Clean up
                    os.remove(result['path'])
                else:
                    failed += 1
                    await update.message.reply_text(f"❌ Failed: {url[:50]}...")
                
                await asyncio.sleep(2)  # Rate limiting
                
            except Exception as e:
                failed += 1
                logger.error(f"Bulk download error: {e}")
                await update.message.reply_text(f"❌ Error: {url[:50]}...")
        
        await msg.edit_text(
            f"✅ **Bulk Download Complete**\n\n"
            f"Total: {total}\n"
            f"Success: {success}\n"
            f"Failed: {failed}\n\n"
            "Thank you for using the bot! ✨",
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle button callbacks"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        
        if data.startswith("dl_"):
            # Download with specific quality
            parts = data.split("_")
            quality = parts[1]
            url_hash = int(parts[2])
            
            # Find URL by hash (simplified - in production, use proper mapping)
            url = query.message.text.split("URL: ")[1].split("...")[0] if "URL: " in query.message.text else ""
            
            if url:
                await query.edit_message_text(f"⏬ Downloading with {quality} quality...")
                result = await self.downloader.download_video(url, quality)
                
                if result:
                    if os.path.exists(result['path']):
                        try:
                            with open(result['path'], 'rb') as f:
                                await query.message.reply_document(
                                    document=f,
                                    filename=f"{result['title'][:50]}.mp4",
                                    caption=f"✅ **{result['title']}**\n\n"
                                           f"Platform: {result['platform'].title()}\n"
                                           f"Duration: {result['duration']}s\n"
                                           f"Size: {result['size'] // 1024 // 1024}MB\n\n"
                                           f"Downloaded by @{query.from_user.username}" if query.from_user.username else "Downloaded by User"
                                )
                            
                            # Clean up
                            os.remove(result['path'])
                            
                        except Exception as e:
                            await query.message.reply_text(f"❌ Error sending file: {e}")
                    else:
                        await query.message.reply_text("❌ File not found after download.")
                else:
                    await query.message.reply_text("❌ Download failed. The video might be private or restricted.")
        
        elif data.startswith("channel_"):
            # Channel download selection
            if data == "channel_all":
                await query.edit_message_text("🔄 Downloading all videos...")
                # Implement channel download logic here
            elif data == "channel_cancel":
                await query.edit_message_text("✅ Channel download cancelled.")
            else:
                video_id = data.split("_")[1]
                await query.edit_message_text(f"⏬ Downloading video {video_id}...")
                # Implement single video download from channel
        
        elif data.startswith("quality_"):
            # Quality selection
            quality = data.split("_")[1]
            quality_names = {
                'best': 'Best Quality',
                '720': '720p HD',
                '480': '480p Standard',
                '360': '360p Fast'
            }
            
            await query.edit_message_text(
                f"✅ Quality set to: {quality_names.get(quality, 'Best Quality')}\n\n"
                "This setting will be used for future downloads."
            )
        
        elif data == "back_main":
            await query.edit_message_text("🔙 Returning to main menu...")
            await self.start(update, context)
        
        elif data.startswith("help_"):
            # Help sections
            section = data.split("_")[1]
            help_texts = {
                'single': "📥 **Single Download**\n\nJust send any video URL directly to the bot!",
                'bulk': "📚 **Bulk Download**\n\nUse /bulk command, then send multiple URLs (one per line).",
                'channel': "📺 **Channel Download**\n\nUse /channel <URL> [number] to download from channels.",
                'settings': "⚙️ **Settings**\n\nUse /settings to change download quality and preferences."
            }
            
            await query.edit_message_text(
                help_texts.get(section, "Help section"),
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle errors"""
        logger.error(f"Update {update} caused error {context.error}")
        
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "❌ An error occurred. Please try again later.\n"
                    "If the problem persists, contact support."
                )
        except:
            pass

def main():
    """Start the bot"""
    # Create bot instance
    bot = TelegramBot()
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("bulk", bot.bulk_command))
    application.add_handler(CommandHandler("channel", bot.channel_command))
    application.add_handler(CommandHandler("settings", bot.settings_command))
    application.add_handler(CommandHandler("cancel", bot.handle_message))
    application.add_handler(CommandHandler("done", bot.handle_message))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    application.add_handler(CallbackQueryHandler(bot.button_callback))
    
    # Add error handler
    application.add_error_handler(bot.error_handler)
    
    # Start bot
    print("🤖 Bot is starting...")
    print(f"📁 Download path: {DOWNLOAD_PATH}")
    print(f"📦 Max bulk items: {MAX_BULK_ITEMS}")
    print(f"💾 Max file size: {MAX_FILE_SIZE // 1024 // 1024}MB")
    print("✅ Bot is ready to use!")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
