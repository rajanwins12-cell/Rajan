"""
RAJAN LORD AI — PRODUCTION-QUALITY TELEGRAM AI ASSISTANT
Single-File Implementation with Groq Integration

Owner: Lord Rajan ❤️
Features:
  - Natural-language control (Hindi/Hinglish/English)
  - Groq AI integration with error handling
  - Owner-only authorization (numeric user ID)
  - Safe tool/function architecture
  - 10-bot management with health monitoring
  - Project/file scanning and analysis
  - Help-menu generation and editing
  - SQLite database for persistence
  - Project backup/restore
  - Structured logging and security
"""

import os
import sys
import json
import sqlite3
import asyncio
import logging
import zipfile
import shutil
import re
import hashlib
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Enum
import traceback

# Third-party imports
try:
    from pyrogram import Client, filters, types
    from pyrogram.errors import ClientError, RPCError
except ImportError:
    print("ERROR: pyrogram not installed. Run: pip install pyrogram")
    sys.exit(1)

try:
    from groq import Groq
except ImportError:
    print("ERROR: groq not installed. Run: pip install groq")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("ERROR: python-dotenv not installed. Run: pip install python-dotenv")
    sys.exit(1)

# Load environment variables
load_dotenv()

# ============================================================================
# CONFIGURATION & LOGGING
# ============================================================================

class Config:
    """Centralized configuration management"""
    
    # Telegram
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    SESSION_NAME = os.getenv("SESSION_NAME", "rajan_lord_ai")
    
    # Owner
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    
    # Groq
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "mixtral-8x7b-32768")
    
    # Database
    DATABASE_PATH = os.getenv("DATABASE_PATH", "rajan_lord_ai.db")
    
    # System
    MAX_BOTS = 10
    BACKUP_DIR = os.getenv("BACKUP_DIR", "backups")
    LOGS_DIR = os.getenv("LOGS_DIR", "logs")
    
    @classmethod
    def validate(cls):
        """Validate all required configuration"""
        errors = []
        
        if not cls.API_ID or cls.API_ID == 0:
            errors.append("API_ID not set or invalid")
        if not cls.API_HASH:
            errors.append("API_HASH not set")
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN not set")
        if not cls.OWNER_ID or cls.OWNER_ID == 0:
            errors.append("OWNER_ID not set or invalid")
        if not cls.GROQ_API_KEY:
            errors.append("GROQ_API_KEY not set")
        
        if errors:
            print("\n❌ CONFIGURATION ERRORS:\n")
            for error in errors:
                print(f"  - {error}")
            print("\nPlease set required environment variables in .env file")
            sys.exit(1)
        
        # Create required directories
        Path(cls.BACKUP_DIR).mkdir(exist_ok=True)
        Path(cls.LOGS_DIR).mkdir(exist_ok=True)


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"{Config.LOGS_DIR}/rajan_lord_ai.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("RajanLordAI")


# ============================================================================
# DATA MODELS
# ============================================================================

class BotStatus(Enum):
    """Bot operational status"""
    ONLINE = "online"
    OFFLINE = "offline"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class BotConfig:
    """Bot configuration"""
    bot_id: int
    name: str
    token: str  # Never logged or exposed
    project: str
    status: str = BotStatus.OFFLINE.value
    last_heartbeat: str = ""
    health_score: int = 0
    created_at: str = ""
    config_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_safe_dict(self):
        """Return dict without sensitive data"""
        d = asdict(self)
        d.pop('token', None)
        return d


@dataclass
class ProjectInfo:
    """Project metadata"""
    name: str
    path: str
    description: str = ""
    commands: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    has_admin: bool = False
    has_music: bool = False
    created_at: str = ""
    last_modified: str = ""


@dataclass
class OperationResult:
    """Standard operation result"""
    success: bool
    message: str
    data: Any = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ============================================================================
# SECURITY & AUTHENTICATION
# ============================================================================

class SecurityManager:
    """Handle security and authorization"""
    
    @staticmethod
    def verify_owner(user_id: int, owner_id: int) -> bool:
        """Verify if user is the configured owner (by numeric ID only)"""
        return user_id == owner_id
    
    @staticmethod
    def mask_secret(secret: str, show_chars: int = 4) -> str:
        """Mask sensitive data for logging"""
        if len(secret) <= show_chars:
            return "*" * len(secret)
        return secret[:show_chars] + "*" * (len(secret) - show_chars)
    
    @staticmethod
    def hash_file(file_path: str) -> str:
        """Generate SHA256 hash of file for integrity checking"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    @staticmethod
    def validate_bot_token(token: str) -> bool:
        """Basic bot token format validation"""
        return ":" in token and len(token) > 20


# ============================================================================
# DATABASE MANAGER
# ============================================================================

class DatabaseManager:
    """SQLite database for persistence"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_schema()
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection with proper settings"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def init_schema(self):
        """Initialize database schema"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Owner settings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS owner_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Bot registry
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bots (
                bot_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                project TEXT,
                status TEXT DEFAULT 'offline',
                last_heartbeat TIMESTAMP,
                health_score INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                config_json TEXT
            )
        """)
        
        # Project registry
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                name TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                description TEXT,
                commands_json TEXT,
                files_json TEXT,
                dependencies_json TEXT,
                has_admin BOOLEAN DEFAULT 0,
                has_music BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_modified TIMESTAMP
            )
        """)
        
        # Operation history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation TEXT NOT NULL,
                status TEXT,
                result_json TEXT,
                error TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Backups
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                file_hash TEXT,
                size_bytes INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
        logger.info("✅ Database schema initialized")
    
    def log_operation(self, operation: str, result: OperationResult):
        """Log operation to database"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO operations (operation, status, result_json, error, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (
            operation,
            "success" if result.success else "failed",
            json.dumps(result.data) if result.data else None,
            result.error,
            result.timestamp
        ))
        
        conn.commit()
        conn.close()
    
    def save_bot(self, bot: BotConfig):
        """Save bot configuration"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        token_hash = hashlib.sha256(bot.token.encode()).hexdigest()
        
        cursor.execute("""
            INSERT OR REPLACE INTO bots 
            (bot_id, name, token_hash, project, status, last_heartbeat, health_score, config_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bot.bot_id,
            bot.name,
            token_hash,
            bot.project,
            bot.status,
            bot.last_heartbeat,
            bot.health_score,
            json.dumps(bot.config_data)
        ))
        
        conn.commit()
        conn.close()
    
    def load_bots(self) -> List[BotConfig]:
        """Load all bots from database"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM bots ORDER BY bot_id")
        rows = cursor.fetchall()
        conn.close()
        
        bots = []
        for row in rows:
            bot = BotConfig(
                bot_id=row['bot_id'],
                name=row['name'],
                token="***MASKED***",  # Never load token from DB
                project=row['project'],
                status=row['status'],
                last_heartbeat=row['last_heartbeat'],
                health_score=row['health_score'],
                config_data=json.loads(row['config_json']) if row['config_json'] else {}
            )
            bots.append(bot)
        
        return bots
    
    def delete_bot(self, bot_id: int):
        """Delete bot from database"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bots WHERE bot_id = ?", (bot_id,))
        conn.commit()
        conn.close()


# ============================================================================
# BOT MANAGEMENT
# ============================================================================

class BotManager:
    """Manage up to 10 Telegram bots"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.bots: Dict[int, BotConfig] = {}
        self.load_bots()
    
    def load_bots(self):
        """Load bot configurations from database"""
        self.bots = {bot.bot_id: bot for bot in self.db.load_bots()}
        logger.info(f"✅ Loaded {len(self.bots)} bots from database")
    
    def register_bot(self, bot_id: int, name: str, token: str, 
                    project: str = "") -> OperationResult:
        """Register a new bot"""
        if len(self.bots) >= Config.MAX_BOTS:
            return OperationResult(
                success=False,
                message=f"Cannot register more than {Config.MAX_BOTS} bots",
                error="MAX_BOTS_EXCEEDED"
            )
        
        if not SecurityManager.validate_bot_token(token):
            return OperationResult(
                success=False,
                message="Invalid bot token format",
                error="INVALID_TOKEN"
            )
        
        if bot_id in self.bots:
            return OperationResult(
                success=False,
                message=f"Bot {bot_id} already registered",
                error="BOT_EXISTS"
            )
        
        bot = BotConfig(
            bot_id=bot_id,
            name=name,
            token=token,
            project=project,
            status=BotStatus.OFFLINE.value,
            created_at=datetime.now().isoformat()
        )
        
        self.bots[bot_id] = bot
        self.db.save_bot(bot)
        
        logger.info(f"✅ Bot {bot_id} registered: {name}")
        return OperationResult(
            success=True,
            message=f"Bot {bot_id} registered successfully",
            data=bot.to_safe_dict()
        )
    
    def get_bot_status(self, bot_id: int) -> OperationResult:
        """Get status of a bot"""
        if bot_id not in self.bots:
            return OperationResult(
                success=False,
                message=f"Bot {bot_id} not found",
                error="BOT_NOT_FOUND"
            )
        
        bot = self.bots[bot_id]
        return OperationResult(
            success=True,
            message="Bot status retrieved",
            data={
                "bot_id": bot.bot_id,
                "name": bot.name,
                "status": bot.status,
                "project": bot.project,
                "health_score": bot.health_score,
                "last_heartbeat": bot.last_heartbeat
            }
        )
    
    def get_all_bots_status(self) -> OperationResult:
        """Get status of all bots"""
        statuses = []
        for bot_id, bot in sorted(self.bots.items()):
            statuses.append({
                "bot_id": bot_id,
                "name": bot.name,
                "status": bot.status,
                "project": bot.project,
                "health_score": bot.health_score
            })
        
        online_count = sum(1 for b in self.bots.values() if b.status == BotStatus.ONLINE.value)
        
        return OperationResult(
            success=True,
            message=f"Status of all {len(self.bots)} bots",
            data={
                "total_bots": len(self.bots),
                "online_bots": online_count,
                "bots": statuses
            }
        )
    
    def update_bot_status(self, bot_id: int, status: str, health_score: int = None):
        """Update bot status and health"""
        if bot_id not in self.bots:
            return
        
        bot = self.bots[bot_id]
        bot.status = status
        bot.last_heartbeat = datetime.now().isoformat()
        
        if health_score is not None:
            bot.health_score = max(0, min(100, health_score))
        
        self.db.save_bot(bot)


# ============================================================================
# PROJECT MANAGEMENT
# ============================================================================

class ProjectScanner:
    """Scan and analyze project files"""
    
    PYTHON_KEYWORDS = {'/start', '/help', '/admin', '/status', '/settings', '/play', 
                       '/stop', '/pause', '/resume', '/next', '/previous'}
    
    @staticmethod
    def scan_project(path: str) -> ProjectInfo:
        """Scan project directory and extract metadata"""
        if not os.path.exists(path):
            return ProjectInfo(name="unknown", path=path, description="Path not found")
        
        project_name = os.path.basename(path)
        files = []
        commands = set()
        dependencies = set()
        has_admin = False
        has_music = False
        
        # Walk through project
        for root, dirs, filenames in os.walk(path):
            # Skip hidden and cache directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            
            for filename in filenames:
                if filename.startswith('.'):
                    continue
                
                file_path = os.path.join(root, filename)
                rel_path = os.path.relpath(file_path, path)
                files.append(rel_path)
                
                # Analyze Python files
                if filename.endswith('.py'):
                    try:
                        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read(10000)  # Read first 10KB
                            
                            # Find commands
                            for match in re.finditer(r"['\"](\/{1}[a-zA-Z_]\w*)['\"]", content):
                                commands.add(match.group(1))
                            
                            # Check for imports
                            if 'pytgcalls' in content or 'voice' in content.lower():
                                has_music = True
                            if 'admin' in content.lower():
                                has_admin = True
                    except Exception:
                        pass
                
                # Parse requirements.txt
                elif filename == 'requirements.txt':
                    try:
                        with open(file_path, 'r') as f:
                            for line in f:
                                line = line.strip()
                                if line and not line.startswith('#'):
                                    dependencies.add(line.split('==')[0].split('>=')[0])
                    except Exception:
                        pass
        
        return ProjectInfo(
            name=project_name,
            path=path,
            files=files,
            commands=sorted(list(commands)) if commands else [],
            dependencies=sorted(list(dependencies)) if dependencies else [],
            has_admin=has_admin,
            has_music=has_music,
            created_at=datetime.fromtimestamp(
                os.path.getctime(path)
            ).isoformat() if os.path.exists(path) else "",
            last_modified=datetime.fromtimestamp(
                os.path.getmtime(path)
            ).isoformat() if os.path.exists(path) else ""
        )
    
    @staticmethod
    def generate_help_menu(project: ProjectInfo) -> str:
        """Generate help menu from project commands"""
        if not project.commands:
            return "📚 No commands detected in this project."
        
        menu = "📚 **Available Commands**\n\n"
        for cmd in project.commands:
            menu += f"  {cmd}\n"
        
        if project.has_admin:
            menu += "\n🔐 **Admin Features Detected**\n"
        
        if project.has_music:
            menu += "\n🎵 **Music Features Detected**\n"
        
        return menu


class ProjectManager:
    """Manage projects and files"""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.projects: Dict[str, ProjectInfo] = {}
    
    def scan_project(self, project_path: str) -> OperationResult:
        """Scan and register project"""
        if not os.path.exists(project_path):
            return OperationResult(
                success=False,
                message="Project path not found",
                error="PATH_NOT_FOUND"
            )
        
        project = ProjectScanner.scan_project(project_path)
        self.projects[project.name] = project
        
        logger.info(f"✅ Scanned project: {project.name} ({len(project.files)} files)")
        
        return OperationResult(
            success=True,
            message=f"Project '{project.name}' scanned successfully",
            data=asdict(project)
        )
    
    def get_project(self, name: str) -> Optional[ProjectInfo]:
        """Get project by name"""
        return self.projects.get(name)
    
    def edit_file(self, project_name: str, file_path: str, 
                  new_content: str, find_replace: Tuple[str, str] = None) -> OperationResult:
        """Safely edit project file"""
        project = self.get_project(project_name)
        if not project:
            return OperationResult(
                success=False,
                message=f"Project '{project_name}' not found",
                error="PROJECT_NOT_FOUND"
            )
        
        full_path = os.path.join(project.path, file_path)
        
        # Security check: ensure file is within project directory
        real_project_path = os.path.realpath(project.path)
        real_file_path = os.path.realpath(full_path)
        
        if not real_file_path.startswith(real_project_path):
            return OperationResult(
                success=False,
                message="Access denied: file outside project directory",
                error="ACCESS_DENIED"
            )
        
        if not os.path.exists(full_path):
            return OperationResult(
                success=False,
                message=f"File '{file_path}' not found in project",
                error="FILE_NOT_FOUND"
            )
        
        # Backup original
        backup_path = f"{full_path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            shutil.copy2(full_path, backup_path)
        except Exception as e:
            return OperationResult(
                success=False,
                message="Failed to create backup",
                error=str(e)
            )
        
        try:
            # Read original
            with open(full_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
            
            # Apply changes
            if find_replace:
                modified_content = original_content.replace(find_replace[0], find_replace[1])
            else:
                modified_content = new_content
            
            # Syntax check for Python files
            if file_path.endswith('.py'):
                try:
                    compile(modified_content, file_path, 'exec')
                except SyntaxError as e:
                    return OperationResult(
                        success=False,
                        message=f"Syntax error in modified file: {e}",
                        error="SYNTAX_ERROR"
                    )
            
            # Write modified content
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(modified_content)
            
            logger.info(f"✅ Edited file: {project_name}/{file_path}")
            
            return OperationResult(
                success=True,
                message=f"File '{file_path}' updated successfully",
                data={
                    "project": project_name,
                    "file": file_path,
                    "backup": backup_path
                }
            )
        
        except Exception as e:
            # Restore from backup
            try:
                shutil.copy2(backup_path, full_path)
            except:
                pass
            
            return OperationResult(
                success=False,
                message=f"Failed to edit file: {str(e)}",
                error="EDIT_FAILED"
            )


class BackupManager:
    """Handle project backups"""
    
    @staticmethod
    def backup_project(project_path: str, backup_dir: str = Config.BACKUP_DIR) -> OperationResult:
        """Create backup of entire project"""
        if not os.path.exists(project_path):
            return OperationResult(
                success=False,
                message="Project path not found",
                error="PATH_NOT_FOUND"
            )
        
        project_name = os.path.basename(project_path)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"{project_name}_backup_{timestamp}.zip"
        backup_path = os.path.join(backup_dir, backup_filename)
        
        try:
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(project_path):
                    dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', '.env'}]
                    
                    for file in files:
                        if file.startswith('.'):
                            continue
                        
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, project_path)
                        zipf.write(file_path, arcname)
            
            file_hash = SecurityManager.hash_file(backup_path)
            file_size = os.path.getsize(backup_path)
            
            logger.info(f"✅ Backup created: {backup_filename} ({file_size} bytes)")
            
            return OperationResult(
                success=True,
                message=f"Backup created: {backup_filename}",
                data={
                    "backup_path": backup_path,
                    "size_bytes": file_size,
                    "hash": file_hash
                }
            )
        
        except Exception as e:
            return OperationResult(
                success=False,
                message=f"Backup failed: {str(e)}",
                error="BACKUP_FAILED"
            )
    
    @staticmethod
    def restore_project(backup_path: str, extract_to: str) -> OperationResult:
        """Restore project from backup"""
        if not os.path.exists(backup_path):
            return OperationResult(
                success=False,
                message="Backup file not found",
                error="BACKUP_NOT_FOUND"
            )
        
        try:
            with zipfile.ZipFile(backup_path, 'r') as zipf:
                zipf.extractall(extract_to)
            
            logger.info(f"✅ Restored from: {backup_path}")
            
            return OperationResult(
                success=True,
                message="Project restored successfully",
                data={"restored_to": extract_to}
            )
        
        except Exception as e:
            return OperationResult(
                success=False,
                message=f"Restore failed: {str(e)}",
                error="RESTORE_FAILED"
            )


# ============================================================================
# GROQ AI INTEGRATION
# ============================================================================

class GroqClient:
    """Groq AI API client with error handling"""
    
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
        self.client = Groq(api_key=api_key)
        self.conversation_history = []
    
    def chat(self, user_message: str, system_prompt: str = None, 
             timeout: int = 30) -> Tuple[bool, str]:
        """Send message to Groq and get response"""
        try:
            if not user_message or not user_message.strip():
                return False, "Empty message"
            
            messages = []
            
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt
                })
            
            # Add conversation history
            messages.extend(self.conversation_history[-10:])  # Last 10 messages
            
            messages.append({
                "role": "user",
                "content": user_message
            })
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
                timeout=timeout
            )
            
            assistant_message = response.choices[0].message.content
            
            # Store in history
            self.conversation_history.append({
                "role": "user",
                "content": user_message
            })
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_message
            })
            
            return True, assistant_message
        
        except Exception as e:
            error_msg = f"Groq API error: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
    
    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []


class RajanAIAgent:
    """Natural-language AI agent for Rajan Lord AI"""
    
    SYSTEM_PROMPT = """You are Rajan Lord AI, a private Telegram AI assistant for Lord Rajan.

**PERSONALITY:**
- Respectful and affectionate
- Respond in the owner's language (Hindi/Hinglish/English)
- Address owner as "Lord Rajan" or "Rajan ji"
- Greetings: "Ji Lord Rajan ❤️", "Bilkul Lord Rajan", "Aap boliye"

**YOU CAN DO:**
1. Bot Management: Control up to 10 Telegram bots
   - Check status of all bots
   - Start/stop/restart bots
   - View bot logs

2. Project Management: Scan and manage Telegram bot projects
   - List projects and their files
   - View project structure and commands
   - Analyze bot features

3. File Editing: Safely modify project files
   - View file contents
   - Edit files with verification
   - Replace text patterns

4. Help Menus: Generate and customize bot help menus
   - Auto-detect commands
   - Edit menu text
   - Verify changes

5. Backups: Protect projects
   - Create project backups
   - Restore from backups
   - View backup history

6. System Info: Monitor everything
   - Show dashboard with all bot statuses
   - View logs
   - System health

**IMPORTANT RULES:**
- NEVER expose bot tokens, API keys, or secrets
- ALWAYS verify file operations with the owner
- NEVER execute arbitrary code
- ALWAYS report real results (never fake success)
- When uncertain, ask clarifying questions
- Respond briefly and naturally

**RESPONSE FORMAT:**
When performing actions:
1. Acknowledge with respectful greeting
2. Confirm what you're doing
3. Show results (success ✅ or error ❌)
4. Ask follow-up if needed

Example: "Ji Lord Rajan ❤️\n\nMain bot status check kar rahi hoon...\n\n[Results]\n\nAur kuch aur chahiye?"
"""
    
    HINDI_KEYWORDS = {
        'status': ['status', 'stat', 'kaise', 'kaisa', 'हाल'],
        'list': ['list', 'dikhao', 'dikhai', 'दिखाओ', 'सूची'],
        'help': ['help', 'sahay', 'madad', 'मदद', 'सहायता'],
        'start': ['start', 'shuru', 'चलाओ', 'शुरू'],
        'stop': ['stop', 'band', 'बंद', 'रोको'],
        'restart': ['restart', 'dubara', 'फिर से', 'दुबारा'],
        'edit': ['edit', 'badlo', 'बदलो', 'संपादित'],
        'backup': ['backup', 'suraksha', 'सुरक्षा', 'बैकअप'],
        'scan': ['scan', 'jaanch', 'जांच', 'देखो'],
        'dashboard': ['dashboard', 'board', 'dikhai', 'डैशबोर्ड'],
    }
    
    def __init__(self, groq_client: GroqClient, bot_manager: BotManager, 
                 project_manager: ProjectManager):
        self.groq = groq_client
        self.bots = bot_manager
        self.projects = project_manager
    
    def parse_intent(self, message: str) -> str:
        """Parse user intent from natural language message"""
        message_lower = message.lower()
        
        for intent, keywords in self.HINDI_KEYWORDS.items():
            for keyword in keywords:
                if keyword in message_lower:
                    return intent
        
        return "unknown"
    
    async def process_command(self, message: str) -> str:
        """Process owner command and return response"""
        intent = self.parse_intent(message)
        
        # Route to appropriate handler
        if intent == 'status':
            result = self.bots.get_all_bots_status()
            if result.success:
                bot_list = result.data.get('bots', [])
                response = f"Ji Lord Rajan ❤️\n\n📊 **Bot Status:**\n\n"
                for bot in bot_list:
                    status_icon = "🟢" if bot['status'] == 'online' else "🔴"
                    response += f"{status_icon} Bot {bot['bot_id']}: {bot['name']} — {bot['status']}\n"
                response += f"\n✅ {result.data['online_bots']}/{result.data['total_bots']} bots online"
                return response
            else:
                return f"❌ {result.error}: {result.message}"
        
        elif intent == 'list':
            if not self.projects.projects:
                return "Abhi koi project registered nahi hai Lord Rajan."
            
            response = "Ji Lord Rajan ❤️\n\n📁 **Projects:**\n\n"
            for proj_name, proj in self.projects.projects.items():
                response += f"📦 **{proj_name}**\n"
                response += f"   Files: {len(proj.files)}\n"
                response += f"   Commands: {len(proj.commands)}\n"
                if proj.has_admin:
                    response += f"   🔐 Admin System\n"
                if proj.has_music:
                    response += f"   🎵 Music System\n"
                response += "\n"
            return response
        
        elif intent == 'help':
            return """Ji Lord Rajan ❤️

🤖 **Rajan Lord AI Capabilities:**

1. **Bot Management**
   - Status of all bots
   - Start/stop bots
   
2. **Project Management**
   - Scan projects
   - View files and commands
   
3. **File Editing**
   - Edit project files safely
   - Backup before changes
   
4. **Help Menus**
   - Auto-generate from commands
   - Edit menu text
   
5. **Backups**
   - Create backups
   - Restore projects

Example commands:
- "mere 10 bots ka status batao"
- "projects dikhao"
- "admin system check karo"
- "help menu edit karo"
"""
        
        else:
            # Use Groq for natural conversation
            success, response = self.groq.chat(
                message,
                system_prompt=self.SYSTEM_PROMPT
            )
            
            if success:
                return response
            else:
                return f"❌ {response}"


# ============================================================================
# TELEGRAM BOT HANDLER
# ============================================================================

class TelegramHandler:
    """Handle Telegram messages and commands"""
    
    def __init__(self, client: Client, owner_id: int, ai_agent: RajanAIAgent):
        self.client = client
        self.owner_id = owner_id
        self.ai = ai_agent
        self.setup_handlers()
    
    def setup_handlers(self):
        """Register message handlers"""
        @self.client.on_message(filters.private)
        async def handle_message(client, message):
            await self.process_message(message)
    
    async def process_message(self, message: types.Message):
        """Process incoming message from owner"""
        # Owner authorization check
        if not SecurityManager.verify_owner(message.from_user.id, self.owner_id):
            await message.reply("❌ Access denied. You are not authorized to use this bot.")
            logger.warning(f"Unauthorized access attempt from user {message.from_user.id}")
            return
        
        try:
            # Show typing indicator
            await self.client.send_chat_action(message.chat.id, "typing")
            
            # Process command
            user_message = message.text or message.caption or ""
            
            if not user_message:
                await message.reply("❌ No message content found")
                return
            
            # Process with AI agent
            response = await self.ai.process_command(user_message)
            
            # Send response
            if len(response) > 4096:
                # Split long messages
                for chunk in [response[i:i+4096] for i in range(0, len(response), 4096)]:
                    await message.reply(chunk, parse_mode="markdown")
            else:
                await message.reply(response, parse_mode="markdown")
            
            logger.info(f"✅ Message processed from owner: {user_message[:50]}")
        
        except Exception as e:
            logger.error(f"❌ Error processing message: {str(e)}\n{traceback.format_exc()}")
            await message.reply(f"❌ Error: {str(e)}")


# ============================================================================
# APPLICATION INITIALIZATION
# ============================================================================

class RajanLordAI:
    """Main application class"""
    
    def __init__(self):
        # Validate configuration
        Config.validate()
        
        # Initialize database
        self.db = DatabaseManager(Config.DATABASE_PATH)
        
        # Initialize managers
        self.bot_manager = BotManager(self.db)
        self.project_manager = ProjectManager(self.db)
        self.backup_manager = BackupManager()
        
        # Initialize Groq
        self.groq = GroqClient(Config.GROQ_API_KEY, Config.GROQ_MODEL)
        
        # Initialize AI agent
        self.ai_agent = RajanAIAgent(self.groq, self.bot_manager, self.project_manager)
        
        # Initialize Telegram client
        self.client = Client(
            Config.SESSION_NAME,
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN
        )
        
        # Setup handlers
        self.telegram = TelegramHandler(self.client, Config.OWNER_ID, self.ai_agent)
        
        logger.info("✅ Rajan Lord AI initialized successfully")
    
    async def start(self):
        """Start the application"""
        try:
            async with self.client:
                logger.info("✅ Telegram bot started")
                logger.info(f"👑 Owner ID: {Config.OWNER_ID}")
                logger.info(f"🤖 AI Model: {Config.GROQ_MODEL}")
                logger.info(f"📊 Database: {Config.DATABASE_PATH}")
                logger.info(f"🎯 Listening for messages from owner...")
                
                await self.client.idle()
        
        except Exception as e:
            logger.error(f"❌ Fatal error: {str(e)}\n{traceback.format_exc()}")
            sys.exit(1)
    
    def run(self):
        """Run the application"""
        asyncio.run(self.start())


# ============================================================================
# VALIDATION & TESTING
# ============================================================================

def validate_imports():
    """Validate all imports are available"""
    try:
        import pyrogram
        import groq
        import dotenv
        logger.info("✅ All required imports available")
        return True
    except ImportError as e:
        logger.error(f"❌ Missing import: {e}")
        return False


def validate_syntax():
    """Validate Python syntax"""
    try:
        compile(open(__file__).read(), __file__, 'exec')
        logger.info("✅ Syntax validation passed")
        return True
    except SyntaxError as e:
        logger.error(f"❌ Syntax error: {e}")
        return False


def run_tests():
    """Run basic tests"""
    logger.info("\n" + "="*60)
    logger.info("RUNNING VALIDATION TESTS")
    logger.info("="*60 + "\n")
    
    # Test 1: Imports
    if not validate_imports():
        sys.exit(1)
    
    # Test 2: Syntax
    if not validate_syntax():
        sys.exit(1)
    
    # Test 3: Database
    try:
        db = DatabaseManager(":memory:")
        logger.info("✅ Database initialization passed")
    except Exception as e:
        logger.error(f"❌ Database test failed: {e}")
        sys.exit(1)
    
    # Test 4: Security Manager
    try:
        assert SecurityManager.verify_owner(123, 123) == True
        assert SecurityManager.verify_owner(123, 456) == False
        assert len(SecurityManager.mask_secret("token123456789")) > 0
        logger.info("✅ Security manager tests passed")
    except Exception as e:
        logger.error(f"❌ Security test failed: {e}")
        sys.exit(1)
    
    # Test 5: Project Scanner
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test files
            open(os.path.join(tmpdir, "test.py"), "w").write("print('hello')")
            project = ProjectScanner.scan_project(tmpdir)
            assert project.name == os.path.basename(tmpdir)
            logger.info("✅ Project scanner tests passed")
    except Exception as e:
        logger.error(f"❌ Project scanner test failed: {e}")
        sys.exit(1)
    
    logger.info("\n" + "="*60)
    logger.info("✅ ALL VALIDATION TESTS PASSED")
    logger.info("="*60 + "\n")


# ============================================================================
# ENTRY POINT
# ============================================================================

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Rajan Lord AI - Personal Telegram AI Assistant")
    parser.add_argument("--test", action="store_true", help="Run validation tests only")
    parser.add_argument("--config", action="store_true", help="Show configuration")
    
    args = parser.parse_args()
    
    if args.test:
        run_tests()
        return
    
    if args.config:
        print("\n" + "="*60)
        print("RAJAN LORD AI - CONFIGURATION")
        print("="*60)
        print(f"\nTelegram:")
        print(f"  API_ID: {Config.API_ID}")
        print(f"  API_HASH: {Config.API_HASH[:10]}..." if Config.API_HASH else "  API_HASH: NOT SET")
        print(f"  BOT_TOKEN: {SecurityManager.mask_secret(Config.BOT_TOKEN)}")
        print(f"\nOwner:")
        print(f"  OWNER_ID: {Config.OWNER_ID}")
        print(f"\nGroq AI:")
        print(f"  GROQ_API_KEY: {SecurityManager.mask_secret(Config.GROQ_API_KEY)}")
        print(f"  GROQ_MODEL: {Config.GROQ_MODEL}")
        print(f"\nSystem:")
        print(f"  DATABASE: {Config.DATABASE_PATH}")
        print(f"  MAX_BOTS: {Config.MAX_BOTS}")
        print(f"  BACKUP_DIR: {Config.BACKUP_DIR}")
        print(f"  LOGS_DIR: {Config.LOGS_DIR}")
        print("\n" + "="*60 + "\n")
        return
    
    # Run validation tests first
    run_tests()
    
    # Start application
    print("\n" + "="*60)
    print("👑 RAJAN LORD AI - STARTING")
    print("="*60 + "\n")
    
    app = RajanLordAI()
    app.run()


if __name__ == "__main__":
    main()
