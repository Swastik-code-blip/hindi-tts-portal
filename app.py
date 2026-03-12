"""
Hindi News TTS Portal - Railway Deployment Ready
=================================================
"""

from flask import Flask, request, send_file, jsonify, render_template
from flask_cors import CORS
import asyncio, io, os, json, math

# TTS Libraries
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

try:
    import edge_tts
    EDGE_AVAILABLE = True
except ImportError:
    EDGE_AVAILABLE = False

try:
    from pydub import AudioSegment
    from pydub.effects import normalize, compress_dynamic_range
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False

app = Flask(__name__)
CORS(app)

# ═══════════════════════════════════════════
# HINDI VOICES CATALOG
# ═══════════════════════════════════════════
HINDI_VOICES = {
    "hi-IN-SwaraNeural":   {"name": "Swara",   "gender": "Female", "desc": "प्राकृतिक महिला आवाज़",  "engine": "edge"},
    "hi-IN-MadhurNeural":  {"name": "Madhur",  "gender": "Male",   "desc": "न्यूज़ पुरुष आवाज़",    "engine": "edge"},
    "hi-IN-AaravNeural":   {"name": "Aarav",   "gender": "Male",   "desc": "युवा पुरुष आवाज़",      "engine": "edge"},
    "hi-IN-AnanyaNeural":  {"name": "Ananya",  "gender": "Female", "desc": "फ्रेश महिला आवाज़",    "engine": "edge"},
    "hi-IN-KavyaNeural":   {"name": "Kavya",   "gender": "Female", "desc": "न्यूज़ महिला आवाज़",   "engine": "edge"},
    "hi-IN-RehaanNeural":  {"name": "Rehaan",  "gender": "Male",   "desc": "डीप पुरुष आवाज़",      "engine": "edge"},
    "hi-IN-NeerjaNeural":  {"name": "Neerja",  "gender": "Female", "desc": "क्लासिक महिला आवाज़",  "engine": "edge"},
    "hi-IN-PrabhatNeural": {"name": "Prabhat", "gender": "Male",   "desc": "औपचारिक पुरुष आवाज़",  "engine": "edge"},
    "gtts-hi":             {"name": "Google",  "gender": "Female", "desc": "Google TTS हिंदी",      "engine": "gtts"},
    "gtts-hi-slow":        {"name": "Google (धीमा)", "gender": "Female", "desc": "Google TTS धीमा", "engine": "gtts"},
}


# ═══════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/voices', methods=['GET'])
def get_voices():
    voices_list = []
    for vid, info in HINDI_VOICES.items():
        voices_list.append({
            "id": vid,
            "name": info["name"],
            "gender": info["gender"],
            "desc": info["desc"],
            "engine": info["engine"],
            "available": True
        })
    return jsonify({
        "voices": voices_list,
        "engines": {
            "edge": EDGE_AVAILABLE,
            "gtts": GTTS_AVAILABLE,
            "pyttsx3": PYTTSX3_AVAILABLE
        }
    })


@app.route('/api/generate', methods=['POST'])
def generate_tts():
    try:
        data = request.get_json()

        text        = data.get('text', '').strip()
        voice       = data.get('voice', 'hi-IN-SwaraNeural')
        speed       = float(data.get('speed', 1.0))
        pitch       = int(data.get('pitch', 0))
        volume      = float(data.get('volume', 1.0))
        fmt         = data.get('format', 'wav').lower()
        engine      = data.get('engine', 'edge').lower()
        effects     = data.get('effects', {})
        pause_level = int(data.get('pause_level', 3))

        if not text:
            return jsonify({"error": "Text is required"}), 400

        text = preprocess_hindi_text(text, pause_level)

        if engine == 'edge' and EDGE_AVAILABLE:
            audio = asyncio.run(generate_edge_tts(text, voice, speed, pitch, volume))
        elif engine == 'gtts' and GTTS_AVAILABLE:
            audio = generate_gtts(text, speed, volume, slow=(voice.endswith('slow')))
        elif EDGE_AVAILABLE:
            audio = asyncio.run(generate_edge_tts(text, voice, speed, pitch, volume))
        elif GTTS_AVAILABLE:
            audio = generate_gtts(text, speed, volume)
        else:
            return jsonify({"error": "No TTS engine available"}), 500

        if not PYDUB_AVAILABLE:
            return jsonify({"error": "pydub not installed"}), 500

        audio = apply_effects(audio, effects, volume)

        buf = io.BytesIO()
        if fmt == 'mp3':
            try:
                audio.export(buf, format='mp3', bitrate='192k')
            except Exception:
                audio.export(buf, format='wav')
                fmt = 'wav'
        elif fmt == 'ogg':
            audio.export(buf, format='ogg', codec='libvorbis')
        else:
            audio.export(buf, format='wav')

        buf.seek(0)
        mime = {'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg'}.get(fmt, 'audio/wav')

        return send_file(buf, mimetype=mime, as_attachment=True,
                         download_name=f'hindi_news.{fmt}')

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════
# TTS ENGINES
# ═══════════════════════════════════════════

async def generate_edge_tts(text, voice, speed, pitch, volume):
    rate_pct = int((speed - 1) * 100)
    rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"
    pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"
    vol_pct = int((volume - 1) * 100)
    vol_str = f"+{vol_pct}%" if vol_pct >= 0 else f"{vol_pct}%"

    communicate = edge_tts.Communicate(text=text, voice=voice,
                                        rate=rate_str, pitch=pitch_str, volume=vol_str)
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    buf.seek(0)
    if buf.getbuffer().nbytes == 0:
        raise ValueError("Edge TTS returned empty audio")
    return AudioSegment.from_mp3(buf)


def generate_gtts(text, speed, volume, slow=False):
    tts = gTTS(text=text, lang='hi', slow=slow or (speed < 0.8), tld='co.in')
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    buf.seek(0)
    audio = AudioSegment.from_mp3(buf)
    if abs(speed - 1.0) > 0.1:
        audio = speed_change(audio, speed)
    return audio


# ═══════════════════════════════════════════
# AUDIO EFFECTS
# ═══════════════════════════════════════════

def apply_effects(audio, effects, volume):
    if volume != 1.0:
        db_change = 20 * math.log10(volume) if volume > 0 else -60
        audio = audio + db_change
    if effects.get('normalize'):
        audio = normalize(audio, headroom=1.0)
    if effects.get('broadcast'):
        try:
            audio = compress_dynamic_range(audio, threshold=-20.0, ratio=3.0)
        except Exception:
            pass
        audio = audio + 2
    if effects.get('studio'):
        if audio.channels == 1:
            left = audio
            right = AudioSegment.silent(duration=20) + audio
            right = right[:len(left)]
            audio = AudioSegment.from_mono_audiosegments(left, right)
    if effects.get('echo'):
        silence = AudioSegment.silent(duration=300, frame_rate=audio.frame_rate)
        echo = silence + (audio - 12)
        combined_len = max(len(audio), len(echo))
        orig = audio + AudioSegment.silent(duration=max(0, combined_len - len(audio)))
        echo_pad = echo + AudioSegment.silent(duration=max(0, combined_len - len(echo)))
        audio = orig.overlay(echo_pad)
    peak = audio.max_dBFS
    if peak > -0.5:
        audio = audio - (peak + 0.5)
    return audio


def speed_change(audio, speed):
    altered = audio._spawn(audio.raw_data, overrides={
        "frame_rate": int(audio.frame_rate * speed)
    })
    return altered.set_frame_rate(audio.frame_rate)


def preprocess_hindi_text(text, pause_level=3):
    import re
    replacements = {
        'PM': 'प्रधानमंत्री', 'CM': 'मुख्यमंत्री',
        'BJP': 'बीजेपी', 'CBI': 'सीबीआई',
        'ED': 'ईडी', 'GDP': 'जीडीपी', 'RBI': 'आरबीआई',
    }
    for abbr, full in replacements.items():
        text = re.sub(r'\b' + abbr + r'\b', full, text)
    return re.sub(r'\s+', ' ', text).strip()


# ═══════════════════════════════════════════
# MAIN — Railway uses PORT env variable
# ═══════════════════════════════════════════

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
