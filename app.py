from flask import Flask, request, jsonify, send_file, render_template
import os, zipfile, tempfile, shutil, subprocess
from werkzeug.utils import secure_filename
from PIL import Image
import uuid
import threading

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

tasks = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    uploaded_file = request.files.get('file')
    compression = request.form.get('compression', 'medium')  # default medium

    if not uploaded_file or not uploaded_file.filename.lower().endswith('.zip'):
        return jsonify({'error': 'Invalid file'}), 400

    if compression not in ['high', 'medium', 'low']:
        compression = 'medium'

    task_id = str(uuid.uuid4())
    tasks[task_id] = {'progress': 0, 'zip_path': None, 'current_file': ''}

    temp_dir = tempfile.mkdtemp()
    zip_path = os.path.join(temp_dir, secure_filename(uploaded_file.filename))
    uploaded_file.save(zip_path)

    threading.Thread(target=process_zip, args=(task_id, zip_path, temp_dir, compression)).start()

    return jsonify({'task_id': task_id})

@app.route('/progress/<task_id>')
def get_progress(task_id):
    task = tasks.get(task_id)
    if not task:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify({
        'progress': task['progress'],
        'current_file': task.get('current_file', '')
    })

@app.route('/download/<task_id>')
def download(task_id):
    task = tasks.get(task_id)
    if not task or not task.get('zip_path') or not os.path.exists(task['zip_path']):
        return 'File not ready or not found.', 404
    return send_file(task['zip_path'], as_attachment=True, download_name='optimized_export.zip')

def update_progress(task_id, percent, current_file=None):
    if task_id in tasks:
        tasks[task_id]['progress'] = percent
        if current_file is not None:
            tasks[task_id]['current_file'] = current_file

def process_zip(task_id, zip_path, temp_dir, compression):
    try:
        extract_dir = os.path.join(temp_dir, 'extracted')
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # Determine quality and bitrate based on compression level
        if compression == 'high':
            img_quality = 90
            audio_bitrate = '128k'
        elif compression == 'medium':
            img_quality = 80
            audio_bitrate = '96k'
        else:  # low
            img_quality = 60
            audio_bitrate = '64k'

        image_files = []
        audio_files = []

        images_folder = os.path.join(extract_dir, 'images')
        if os.path.isdir(images_folder):
            for root, _, files in os.walk(images_folder):
                for file in files:
                    if file.endswith('.webp'):
                        image_files.append(os.path.join(root, file))

        media_folder = os.path.join(extract_dir, 'media')
        if os.path.isdir(media_folder):
            for root, _, files in os.walk(media_folder):
                for file in files:
                    if file.endswith('.webm'):
                        audio_files.append(os.path.join(root, file))

        total_files = len(image_files) + len(audio_files)
        processed_files = 0

        if total_files == 0:
            update_progress(task_id, 100, current_file='No files to optimize')
        else:
            for path in image_files:
                file_name = os.path.basename(path)
                try:
                    img = Image.open(path)
                    img.save(path, format='WEBP', quality=img_quality, method=6)
                except Exception as e:
                    print(f"Image optimization failed: {e}")
                processed_files += 1
                percent = int((processed_files / total_files) * 100)
                update_progress(task_id, percent, current_file=file_name)

            for path in audio_files:
                file_name = os.path.basename(path)
                try:
                    out_path = path + "_opt.webm"
                    result = subprocess.run([
                        'ffmpeg', '-y', '-i', path,
                        '-c:a', 'libvorbis', '-b:a', audio_bitrate,
                        out_path
                    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                    if result.returncode == 0:
                        os.replace(out_path, path)
                    else:
                        print(f"Audio optimization failed: {result.stderr.decode()}")
                except Exception as e:
                    print(f"Audio optimization error: {e}")
                processed_files += 1
                percent = int((processed_files / total_files) * 100)
                update_progress(task_id, percent, current_file=file_name)

        final_zip_path = os.path.join(temp_dir, 'final.zip')
        with zipfile.ZipFile(final_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, _, files in os.walk(extract_dir):
                for file in files:
                    full_path = os.path.join(root, file)
                    arcname = os.path.relpath(full_path, extract_dir)
                    zipf.write(full_path, arcname)

        tasks[task_id]['zip_path'] = final_zip_path
        update_progress(task_id, 100, current_file='Done')

    except Exception as e:
        print(f"Processing failed for {task_id}: {e}")
        update_progress(task_id, 100, current_file='Error')

if __name__ == '__main__':
    app.run(debug=True)
