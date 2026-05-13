import uuid
from io import BytesIO

import redis
from flask import Flask, request, jsonify, send_file

from tasks import upscale_task

app = Flask(__name__)

redis_input = redis.Redis(host='redis', port=6379, db=1)
redis_output = redis.Redis(host='redis', port=6379, db=2)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'bmp', 'tiff'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/upscale', methods=['POST'])
def upscale():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400

    task_id = str(uuid.uuid4())
    redis_input.setex(task_id, 3600, file.read())
    upscale_task.apply_async(args=(task_id,), task_id=task_id)
    return jsonify({'task_id': task_id}), 202


@app.route('/tasks/<task_id>', methods=['GET'])
def get_task_state(task_id):
    task = upscale_task.AsyncResult(task_id)
    if task.state == 'PENDING':
        return jsonify({'status': 'PENDING'}), 200
    elif task.state == 'SUCCESS':
        return jsonify({
            'status': 'SUCCESS',
            'download_url': f'/processed/{task_id}'
        }), 200
    elif task.state == 'FAILURE':
        return jsonify({'status': 'FAILURE', 'error': str(task.info)}), 200
    else:
        return jsonify({'status': task.state}), 200


@app.route('/processed/<file_id>', methods=['GET'])
def get_processed(file_id):
    data = redis_output.get(file_id)
    if data is None:
        task = upscale_task.AsyncResult(file_id)
        if task.state == 'PENDING':
            return jsonify({'error': 'Still processing'}), 202
        return jsonify({'error': 'File not found'}), 404

    return send_file(
        BytesIO(data),
        mimetype='image/png',
        as_attachment=True,
        download_name=f'{file_id}.png'
    )
