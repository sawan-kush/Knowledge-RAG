import os
from dotenv import load_dotenv

load_dotenv()

NEO4J_URI = os.getenv("NEO4J_URI", "")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Safety limits
MAX_ROWS = int(os.getenv("MAX_ROWS", "200"))
QUERY_TIMEOUT_SECONDS = int(os.getenv("QUERY_TIMEOUT_SECONDS", "20"))

missing = []
if not NEO4J_URI:
    missing.append("NEO4J_URI")
if not NEO4J_PASSWORD:
    missing.append("NEO4J_PASSWORD")
if not GROQ_API_KEY:
    missing.append("GROQ_API_KEY")

if missing:
    print(f"[config] WARNING: missing env vars: {', '.join(missing)}. "
          f"Copy .env.example to .env and fill these in.")
