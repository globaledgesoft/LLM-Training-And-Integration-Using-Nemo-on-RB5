from flask import Flask, render_template, request, jsonify
import torch
from peft import PeftModel, PeftConfig
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
import pyaudio
import wave
from array import array
from google.cloud import speech
import os
import io
import sys
import nemollm
from nemollm.api import NemoLLM
from gtts import gTTS
import argparse
import time
from threading import Thread

app = Flask(__name__)

parser = argparse.ArgumentParser(description="Voice-Bot Argument Parser")
parser.add_argument("--nemo", action='store_true')
args = parser.parse_args()

if args.nemo:
    conn = NemoLLM(
        api_key="NGC-API-KEY-ADDED-HERE",
        org_id="ORIGINAL-ID-ADDED-HERE"
    )

    def asr_nemo(user_code):
        if user_code != "":
            response = conn.generate(
                prompt=user_code,
                model="gpt-43b-002",
                customization_id="567089f8-5052-456f-bef1-7b99c0fa0210",
                stop=[],
                tokens_to_generate=100,
                temperature=1.0,
                top_k=1,
                top_p=0.0,
                random_seed=0,
                beam_search_diversity_rate=0.0,
                beam_width=1,
                repetition_penalty=1.0,
                length_penalty=1.0,
            )
        generated_text = response['text']
        return generated_text

else:
    # Load PEFT configuration and model
    peft_model_id = "rb5_model"
    config = PeftConfig.from_pretrained(peft_model_id)
    model = AutoModelForSeq2SeqLM.from_pretrained(config.base_model_name_or_path)
    tokenizer = AutoTokenizer.from_pretrained(config.base_model_name_or_path)
    model = PeftModel.from_pretrained(model, peft_model_id)
    model.eval()

    print("Peft model loaded")

    def generate_response(question):
        input_ids = tokenizer(question, return_tensors="pt", truncation=True).input_ids.cpu()
        start_time = time.time()
        outputs = model.generate(input_ids=input_ids, max_new_tokens=500, do_sample=True, top_p=0.9)
        end_time = time.time()
        sum_time = end_time - start_time
        response = tokenizer.batch_decode(outputs.detach().cpu().numpy(), skip_special_tokens=True)[0]

        print("Response: {}".format(response))
        print("Time taken for inference: {:.2f} seconds".format(sum_time))

        return response

# Set up Google Cloud Speech-to-Text credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'google_secret_key.json'

# Initialize Google Cloud Speech client
client = speech.SpeechClient()

def record_audio(file_name="output.wav", record_seconds=30, device_index=None):
    chunk = 1024  # Record in chunks of 1024 samples
    sample_format = pyaudio.paInt16  # 16 bits per sample
    channels = 1
    fs = 16000  # Record at 16000 samples per second

    p = pyaudio.PyAudio()  # Create an interface to PortAudio
    try:
        stream = p.open(format=sample_format,
                        channels=channels,
                        rate=fs,
                        frames_per_buffer=chunk,
                        input_device_index=device_index,
                        input=True)
    except OSError as e:
        print(f"Could not open audio device: {e}")
        p.terminate()
        return

    print('Recording...')
    slnc = 0
    frames = []
    while True:
        stream.start_stream()
        data = stream.read(chunk)
        data_chunk = array('h', data)
        vol = max(data_chunk)
        if vol > 200:
            print("Listening...")
            frames.append(data)
        else:
            continue

        for i in range(0, int(fs / chunk * record_seconds)):
            data = stream.read(chunk)
            data_chunk = array('h', data)
            vol = max(data_chunk)
            frames.append(data)
            if vol < 200:
                slnc += 1
                if slnc > 20:
                    slnc = 0
                    print("Stopped due to silence")
                    break
            elif vol > 3000:
                slnc = 0
        stream.stop_stream()
        break

    stream.close()
    p.terminate()

    print('Finished recording')

    wf = wave.open(file_name, 'wb')
    wf.setnchannels(channels)
    wf.setsampwidth(p.get_sample_size(sample_format))
    wf.setframerate(fs)
    wf.writeframes(b''.join(frames))
    wf.close()

def transcribe_audio(file_name="output.wav"):
    with io.open(file_name, "rb") as audio_file:
        content = audio_file.read()
        audio = speech.RecognitionAudio(content=content)

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        enable_automatic_punctuation=True,
        audio_channel_count=1,
        language_code="en-US",
    )

    response = client.recognize(request={"config": config, "audio": audio})
    transcript = ""
    for result in response.results:
        transcript = result.alternatives[0].transcript
        print("Transcription: {}".format(transcript))

    return transcript

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/record', methods=['POST'])
def record():
    record_audio(device_index=0)
    question = transcribe_audio()
    return jsonify({'question': question})

@app.route('/generate', methods=['POST'])
def generate():
    question = request.json.get('question')
    if args.nemo:
        response = asr_nemo(question)
    else:
        response = generate_response(question)
    return jsonify({'response': response})

if __name__ == '__main__':
    app.run(debug=True, host="0.0.0.0", port=5000)
