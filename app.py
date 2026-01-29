import os
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, session
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
import psycopg2
from datetime import datetime
import io

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Настройки загрузки файлов
UPLOAD_FOLDER = '/tmp/uploads'
MAX_FILE_SIZE = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'zip', 'rar'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Пароль для доступа к файлообменнику
APP_PASSWORD_HASH = generate_password_hash(os.environ.get('APP_PASSWORD', 'changeme'))

def get_db_connection():
    """Подключение к PostgreSQL базе данных Aiven"""
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise Exception("DATABASE_URL environment variable is not set")
    
    try:
        conn = psycopg2.connect(database_url)
        return conn
    except psycopg2.OperationalError as e:
        print(f"Database connection error: {e}")
        print(f"Attempting to connect to: {database_url.split('@')[1] if '@' in database_url else 'unknown'}")
        raise

def init_db():
    """Инициализация базы данных"""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id SERIAL PRIMARY KEY,
            filename VARCHAR(255) NOT NULL,
            original_filename VARCHAR(255) NOT NULL,
            upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            file_size INTEGER,
            file_data BYTEA
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    if 'authenticated' not in session:
        return redirect(url_for('login'))
    
    # Получение списка файлов
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Автоматическая инициализация таблицы если её нет
    try:
        cur.execute('SELECT id, original_filename, upload_date, file_size FROM files ORDER BY upload_date DESC')
        files = cur.fetchall()
    except psycopg2.errors.UndefinedTable:
        # Таблица не существует - создаём её
        conn.rollback()
        init_db()
        # Пробуем снова
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('SELECT id, original_filename, upload_date, file_size FROM files ORDER BY upload_date DESC')
        files = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return render_template('index.html', files=files)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password', '')
        if check_password_hash(APP_PASSWORD_HASH, password):
            session['authenticated'] = True
            flash('Вход выполнен успешно!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неверный пароль!', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'authenticated' not in session:
        return redirect(url_for('login'))
    
    if 'file' not in request.files:
        flash('Файл не выбран', 'error')
        return redirect(url_for('index'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('Файл не выбран', 'error')
        return redirect(url_for('index'))
    
    if file and allowed_file(file.filename):
        original_filename = secure_filename(file.filename)
        file_data = file.read()
        file_size = len(file_data)
        
        if file_size > MAX_FILE_SIZE:
            flash(f'Файл слишком большой. Максимальный размер: {MAX_FILE_SIZE // (1024*1024)}MB', 'error')
            return redirect(url_for('index'))
        
        # Сохранение в базу данных
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO files (filename, original_filename, file_size, file_data) VALUES (%s, %s, %s, %s)',
            (original_filename, original_filename, file_size, psycopg2.Binary(file_data))
        )
        conn.commit()
        cur.close()
        conn.close()
        
        flash(f'Файл "{original_filename}" успешно загружен!', 'success')
    else:
        flash('Недопустимый тип файла', 'error')
    
    return redirect(url_for('index'))

@app.route('/download/<int:file_id>')
def download_file(file_id):
    if 'authenticated' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT original_filename, file_data FROM files WHERE id = %s', (file_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    
    if result:
        filename, file_data = result
        return send_file(
            io.BytesIO(file_data),
            as_attachment=True,
            download_name=filename
        )
    else:
        flash('Файл не найден', 'error')
        return redirect(url_for('index'))

@app.route('/delete/<int:file_id>', methods=['POST'])
def delete_file(file_id):
    if 'authenticated' not in session:
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM files WHERE id = %s', (file_id,))
    conn.commit()
    cur.close()
    conn.close()
    
    flash('Файл удалён', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
