import os
import threading
import asyncio
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
from main import run_bot, otp_queue

app = Flask(__name__)
# Vercel/Render needs the 'app' variable to be exposed
handler = app

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'vfs_secret_key_change_me')
# Standard SocketIO setup
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global state to keep track of the bot thread
bot_thread = None
loop = None

def start_async_loop(new_loop):
    asyncio.set_event_loop(new_loop)
    new_loop.run_forever()

# Initialize the async loop in a separate thread
loop = asyncio.new_event_loop()
thread = threading.Thread(target=start_async_loop, args=(loop,), daemon=True)
thread.start()

async def socket_callback(message, level):
    socketio.emit('bot_status', {'message': message, 'level': level})

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('start_bot')
def handle_start_bot(data):
    global bot_thread
    email = data.get('email')
    password = data.get('password')
    refs = data.get('refs', '').split(',')
    
    if not email or not password:
        emit('bot_status', {'message': 'Hata: Email ve Şifre zorunludur.', 'level': 'error'})
        return

    emit('bot_status', {'message': 'Bot başlatma isteği alındı...', 'level': 'info'})
    
    # Run the bot in the async loop
    asyncio.run_coroutine_threadsafe(
        run_bot(email, password, refs, socket_callback),
        loop
    )

@socketio.on('submit_otp')
def handle_submit_otp(data):
    otp_code = data.get('otp')
    if otp_code:
        asyncio.run_coroutine_threadsafe(otp_queue.put(otp_code), loop)
        emit('bot_status', {'message': f'OTP Gönderildi: {otp_code}', 'level': 'success'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)
else:
    # This part is for Vercel/Serverless
    pass
