# app.py - Dedicated Maya AI Brain Server
import os
import re
import asyncio
import tempfile
import aiohttp
from datetime import datetime
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from gTTS import gTTS
from pydub import AudioSegment
from rapidfuzz import fuzz

app = FastAPI(title="Maya AI Central Engine")

# ==========================================
# ⚙️ কনফিগারেশন (আপনার মেইন ডাটাবেসের সাথে কানেক্টেড)
# ==========================================
MONGO_URL = os.getenv("MONGO_URL", "mongodb+srv://MoviaXBot270:MoviaXBot270@cluster0.kbkpgt6.mongodb.net/?appName=Cluster0")
client = AsyncIOMotorClient(MONGO_URL)
db = client['movie_database']

class ChatRequest(BaseModel):
    user_id: int
    user_name: str
    user_text: str

# 🔍 ডাটাবেসে রিয়েল-টাইম মুভি খোঁজা
async def check_movie_availability(query: str):
    try:
        clean_q = re.sub(r"[^a-zA-Z0-9\s\u0980-\u09FF]", "", query).lower().strip()
        for word in ["movie", "download", "video", "মুভি", "ভিডিও", "আছে", "হবে", "dao", "den"]:
            clean_q = clean_q.replace(word, "").strip()

        if len(clean_q) < 2:
            return None

        exact = await db.movies.find_one({"title": {"$regex": f"^{re.escape(clean_q)}$", "$options": "i"}})
        if exact:
            return exact.get("title")

        movies = await db.movies.find({}, {"title": 1}).to_list(300)
        best_match, best_score = None, 0
        for m in movies:
            t = m.get("title", "")
            score = fuzz.token_sort_ratio(clean_q, t.lower())
            if score > best_score:
                best_score, best_match = score, t

        if best_match and best_score >= 65:
            return best_match
    except Exception:
        pass
    return None

# 🎙️ ভয়েস তৈরি ইঞ্জিন (MP3 -> Telegram OGG Opus)
async def generate_voice_file(text: str) -> str:
    clean_text = re.sub(r"[^\w\s\u0980-\u09FF,!?]", "", text).strip()
    if not clean_text:
        clean_text = "আমি শুনতে পাচ্ছি বন্ধু!"

    loop = asyncio.get_running_loop()

    def _tts():
        tts_obj = gTTS(text=clean_text[:200], lang="bn", slow=False)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_mp3:
            p = tmp_mp3.name
        tts_obj.save(p)
        return p

    mp3_path = await loop.run_in_executor(None, _tts)

    def _to_ogg(src):
        audio = AudioSegment.from_mp3(src)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_ogg:
            o_p = tmp_ogg.name
        audio.export(o_p, format="ogg", codec="libopus")
        return o_p

    ogg_path = await loop.run_in_executor(None, _to_ogg, mp3_path)
    if os.path.exists(mp3_path):
        os.unlink(mp3_path)
    return ogg_path

# 🧠 বুদ্ধিমান চ্যাট ইঞ্জিন (মেমোরি + আনলিমিটেড ফ্রি AI)
async def think_reply(user_id: int, user_name: str, user_text: str) -> str:
    matched_movie = await check_movie_availability(user_text)

    # মেমোরি রিড
    history = await db.maya_memory.find({"user_id": user_id}).sort("created_at", -1).limit(4).to_list(4)
    history.reverse()

    context_str = ""
    for h in history:
        context_str += f"User: {h['user']}\nMaya: {h['maya']}\n"

    movie_hint = f"\n[তথ্য: ইউজারের কাঙ্ক্ষিত ভিডিও '{matched_movie}' আমাদের অ্যাপে আছে! ওকে বোলো অ্যাপে ঢুকলেই পাবে।]" if matched_movie else ""

    prompt = f"""
তুমি "মায়া", একজন অত্যন্ত মিষ্টি, চটপটে ও বন্ধুসুলভ বাংলাদেশি মেয়ে।
- তুমি কোনো রোবট নও, ইউজারের প্রিয় বান্ধবী।
- কথা বলবে বাস্তব বাংলাদেশি মিষ্টি কথ্য বাংলায় (যেমন: 'আরেহ শুনো না', 'কী খবর তোমার?', 'বলো কি হেল্প লাগবে')।
- উত্তর ১ থেকে সর্বোচ্চ ২ বাক্যের মধ্যে দেবে। কখনোই বড় লেকচার দেবে না।
{movie_hint}

পূর্বের আলাপ:
{context_str}
User: {user_text}
Maya:"""

    reply = None
    # Pollinations AI ফ্রি ইঞ্জিন
    try:
        url = "https://text.pollinations.ai/"
        payload = {
            "messages": [
                {"role": "system", "content": "You are Maya, a sweet friendly Bangladeshi girl. Reply strictly in conversational Bengali."},
                {"role": "user", "content": prompt.strip()}
            ],
            "model": "openai"
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=6) as resp:
                if resp.status == 200:
                    text_resp = await resp.text()
                    if text_resp and len(text_resp.strip()) > 1:
                        reply = text_resp.strip()
    except Exception:
        pass

    if not reply:
        if matched_movie:
            reply = f"আরে {user_name}! তুমি যেটা খুঁজছো '{matched_movie}' তো অ্যাপেই আপলোড করা আছে, জলদি দেখে নাও! 😍"
        else:
            reply = f"হুম {user_name}, শুনতেছি তো! বলো কী খবর তোমার?"

    clean_reply = re.sub(r"[\*\_#]", "", reply).replace("Maya:", "").replace("মায়া:", "").strip()

    # মেমোরিতে সংরক্ষণ
    try:
        await db.maya_memory.insert_one({
            "user_id": user_id,
            "user": user_text,
            "maya": clean_reply,
            "created_at": datetime.utcnow()
        })
    except Exception:
        pass

    return clean_reply

# ==========================================
# 🌐 API এন্ডপয়েন্ট (যা আপনার মেইন বটের সাথে কথা বলবে)
# ==========================================
@app.post("/api/maya/chat")
async def maya_chat_api(req: ChatRequest):
    reply_text = await think_reply(req.user_id, req.user_name, req.user_text)
    return {"reply": reply_text}

@app.post("/api/maya/voice")
async def maya_voice_api(req: ChatRequest, background_tasks: BackgroundTasks):
    reply_text = await think_reply(req.user_id, req.user_name, req.user_text)
    ogg_file = await generate_voice_file(reply_text)
    
    if not ogg_file or not os.path.exists(ogg_file):
        raise HTTPException(status_code=500, detail="Voice generation failed")

    # ফাইল পাঠানোর পর স্বয়ংক্রিয় ক্লিনআপ
    background_tasks.add_task(lambda p: os.unlink(p) if os.path.exists(p) else None, ogg_file)
    
    return FileResponse(
        path=ogg_file, 
        media_type="audio/ogg", 
        headers={"X-Maya-Reply": reply_text.encode('utf-8').decode('latin1', 'ignore')}
    )

@app.get("/")
def home():
    return {"status": "Maya Brain is Active & Thinking 🧠"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
