"""
Hindi News TTS Portal - All 12 Hindi Voices
"""

from flask import Flask, request, send_file, jsonify, render_template
from flask_cors import CORS
import asyncio, io, os, math, re

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

app = Flask(__name__)
CORS(app)

# All 12 confirmed Microsoft Hindi voices
HINDI_VOICES = {
    "hi-IN-SwaraNeural":   {"name": "Swara",   "gender": "Female", "desc": "प्राकृतिक महिला",  "tld": "co.in",  "slow": False, "speed": 1.0,  "pitch_shift": 0},
    "hi-IN-MadhurNeural":  {"name": "Madhur",  "gender": "Male",   "desc": "न्यूज़ पुरुष",    "tld": "co.in",  "slow": False, "speed": 0.95, "pitch_shift": -3},
    "hi-IN-AaravNeural":   {"name": "Aarav",   "gender": "Male",   "desc": "युवा पुरुष",      "tld": "com",    "slow": False, "speed": 1.05, "pitch_shift": -2},
    "hi-IN-AnanyaNeural":  {"name": "Ananya",  "gender": "Female", "desc": "फ्रेश महिला",    "tld": "com.au", "slow": False, "speed": 1.1,  "pitch_shift": 2},
    "hi-IN-KavyaNeural":   {"name": "Kavya",   "gender": "Female", "desc": "न्यूज़ महिला",   "tld": "co.uk",  "slow": False, "speed": 1.0,  "pitch_shift": 1},
    "hi-IN-RehaanNeural":  {"name": "Rehaan",  "gender": "Male",   "desc": "डीप पुरुष",      "tld": "co.in",  "slow": True,  "speed": 0.9,  "pitch_shift": -4},
    "hi-IN-AasthiNeural":  {"name": "Aasthi",  "gender": "Female", "desc": "सॉफ्ट महिला",   "tld": "co.in",  "slow": False, "speed": 1.0,  "pitch_shift": 1},
    "hi-IN-HemantNeural":  {"name": "Hemant",  "gender": "Male",   "desc": "गंभीर पुरुष",   "tld": "com",    "slow": False, "speed": 0.92, "pitch_shift": -3},
    "hi-IN-PrabhatNeural": {"name": "Prabhat", "gender": "Male",   "desc": "औपचारिक पुरुष",  "tld": "com",    "slow": False, "speed": 0.9,  "pitch_shift": -2},
    "hi-IN-NeerjaNeural":  {"name": "Neerja",  "gender": "Female", "desc": "एक्सप्रेसिव",   "tld": "co.in",  "slow": True,  "speed": 0.95, "pitch_shift": 1},
    "hi-IN-ShubhNeural":   {"name": "Shubh",   "gender": "Male",   "desc": "शुभ पुरुष",     "tld": "co.in",  "slow": False, "speed": 1.0,  "pitch_shift": -1},
    "hi-IN-RukminiNeural": {"name": "Rukmini", "gender": "Female", "desc": "क्लासिक महिला",  "tld": "co.uk",  "slow": False, "speed": 0.98, "pitch_shift": 0},
}

DEFAULT_VOICE = "hi-IN-SwaraNeural"


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/voices', methods=['GET'])
def get_voices():
    return jsonify({
        "voices": [
            {"id": vid, "name": info["name"], "gender": info["gender"],
             "desc": info["desc"], "engine": "edge", "available": True}
            for vid, info in HINDI_VOICES.items()
        ],
        "engines": {"edge": EDGE_AVAILABLE, "gtts": GTTS_AVAILABLE}
    })


@app.route('/api/test-voices', methods=['GET'])
def test_voices():
    """Test which Edge TTS voices actually work on this server"""
    results = {}
    test_text = "नमस्ते"
    
    async def test_one(voice_id):
        try:
            communicate = edge_tts.Communicate(text=test_text, voice=voice_id)
            buf = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buf.write(chunk["data"])
            return buf.getbuffer().nbytes > 0
        except:
            return False

    if EDGE_AVAILABLE:
        for vid in HINDI_VOICES.keys():
            works = asyncio.run(test_one(vid))
            results[vid] = "✅ works" if works else "❌ failed"
    
    return jsonify(results)


@app.route('/api/generate', methods=['POST'])
def generate_tts():
    try:
        data        = request.get_json()
        text        = data.get('text', '').strip()
        voice       = data.get('voice', DEFAULT_VOICE)
        speed       = float(data.get('speed', 1.0))
        pitch       = int(data.get('pitch', 0))
        volume      = float(data.get('volume', 1.0))
        fmt         = data.get('format', 'wav').lower()
        engine      = data.get('engine', 'edge').lower()
        effects     = data.get('effects', {}  )
        pause_level = int(data.get('pause_level', 3))

        if not text:
            return jsonify({"error": "Text is required"}), 400

        text = preprocess_hindi_text(text, pause_level)

        if voice.startswith('browser-') or voice not in HINDI_VOICES:
            voice = DEFAULT_VOICE

        voice_info = HINDI_VOICES[voice]
        audio = None

        # Try Edge TTS first
        if engine != 'gtts' and EDGE_AVAILABLE:
            try:
                audio = asyncio.run(generate_edge_tts(text, voice, speed, pitch, volume))
                print(f"✅ Edge TTS success: {voice}")
            except Exception as e:
                print(f"❌ Edge TTS failed ({voice}): {e}")
                audio = None

        # Fallback to gTTS with voice variety
        if audio is None and GTTS_AVAILABLE:
            print(f"Using gTTS fallback for {voice}")
            audio = generate_gtts_voice(text, voice_info, speed, volume)

        if audio is None:
            return jsonify({"error": "Could not generate audio"}), 500

        audio = apply_effects(audio, effects, volume)

        buf = io.BytesIO()
        if fmt == 'mp3':
            try:
                audio.export(buf, format='mp3', bitrate='192k')
            except Exception:
                audio.export(buf, format='wav'); fmt = 'wav'
        elif fmt == 'ogg':
            try:
                audio.export(buf, format='ogg', codec='libvorbis')
            except Exception:
                audio.export(buf, format='wav'); fmt = 'wav'
        else:
            audio.export(buf, format='wav')

        buf.seek(0)
        mime = {'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg'}.get(fmt, 'audio/wav')
        return send_file(buf, mimetype=mime, as_attachment=True,
                         download_name=f'hindi_news.{fmt}')

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500


async def generate_edge_tts(text, voice, speed, pitch, volume):
    rate_pct = int((speed - 1) * 100)
    rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"
    pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"
    vol_pct = int((volume - 1) * 100)
    vol_str = f"+{vol_pct}%" if vol_pct >= 0 else f"{vol_pct}%"

    communicate = edge_tts.Communicate(
        text=text, voice=voice,
        rate=rate_str, pitch=pitch_str, volume=vol_str
    )
    buf = io.BytesIO()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            buf.write(chunk["data"])
    buf.seek(0)
    if buf.getbuffer().nbytes == 0:
        raise ValueError("Empty audio")
    return AudioSegment.from_mp3(buf)


def generate_gtts_voice(text, voice_info, user_speed, user_volume):
    tld         = voice_info.get("tld", "co.in")
    slow        = voice_info.get("slow", False)
    v_speed     = voice_info.get("speed", 1.0) * user_speed
    pitch_shift = voice_info.get("pitch_shift", 0)

    tts = gTTS(text=text, lang='hi', slow=slow, tld=tld)
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    buf.seek(0)
    audio = AudioSegment.from_mp3(buf)

    if abs(v_speed - 1.0) > 0.05:
        audio = speed_change(audio, v_speed)

    if pitch_shift != 0:
        new_rate = int(audio.frame_rate * (2 ** (pitch_shift / 12.0)))
        audio = audio._spawn(audio.raw_data, overrides={"frame_rate": new_rate})
        audio = audio.set_frame_rate(44100)

    return audio


def apply_effects(audio, effects, volume):
    if volume != 1.0:
        db = 20 * math.log10(volume) if volume > 0 else -60
        audio = audio + db
    if effects.get('normalize'):
        audio = normalize(audio, headroom=1.0)
    if effects.get('broadcast'):
        try: audio = compress_dynamic_range(audio, threshold=-20.0, ratio=3.0)
        except: pass
        audio = audio + 2
    if effects.get('studio') and audio.channels == 1:
        left = audio
        right = (AudioSegment.silent(duration=20) + audio)[:len(left)]
        audio = AudioSegment.from_mono_audiosegments(left, right)
    if effects.get('echo'):
        silence = AudioSegment.silent(duration=300, frame_rate=audio.frame_rate)
        echo = silence + (audio - 12)
        cl = max(len(audio), len(echo))
        audio = (audio + AudioSegment.silent(duration=max(0,cl-len(audio)))).overlay(
                 echo + AudioSegment.silent(duration=max(0,cl-len(echo))))
    peak = audio.max_dBFS
    if peak > -0.5: audio = audio - (peak + 0.5)
    return audio


def speed_change(audio, speed):
    return audio._spawn(audio.raw_data, overrides={
        "frame_rate": int(audio.frame_rate * speed)
    }).set_frame_rate(audio.frame_rate)


def preprocess_hindi_text(text, pause_level=3):
    for abbr, full in {
        'PM':'प्रधानमंत्री','CM':'मुख्यमंत्री',
        'BJP':'बीजेपी','CBI':'सीबीआई','ED':'ईडी',
        'GDP':'जीडीपी','RBI':'आरबीआई'
    }.items():
        text = re.sub(r'\b' + abbr + r'\b', full, text)
    return re.sub(r'\s+', ' ', text).strip()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
