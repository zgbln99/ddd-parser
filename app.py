from flask import Flask, render_template, request, jsonify, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename
import os
import pandas as pd
from datetime import datetime, timedelta
import io
import zipfile
from threading import Thread
import json
import time
import struct
from dataclasses import dataclass
from typing import List, Dict, Any
import logging
from logging.handlers import RotatingFileHandler
import atexit
from config import config

def create_app(config_name=None):
    """Factory function to create Flask app"""
    app = Flask(__name__)

    # Load configuration
    config_name = config_name or os.environ.get('FLASK_ENV', 'production')
    app.config.from_object(config[config_name])

    # Ensure directories exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
    os.makedirs(app.config.get('LOG_FOLDER', 'logs'), exist_ok=True)

    # Setup logging for production
    if not app.debug and not app.testing:
        if not os.path.exists('logs'):
            os.mkdir('logs')
        file_handler = RotatingFileHandler('logs/ddd_parser.log', maxBytes=10240000, backupCount=10)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)
        app.logger.info('DDD Parser startup')

    return app

app = create_app()

# Global variable to track processing status
processing_status = {
    'active': False,
    'total_files': 0,
    'processed_files': 0,
    'current_file': '',
    'start_time': None,
    'errors': []
}

@dataclass
class DriverActivity:
    """Klasa reprezentująca aktywność kierowcy"""
    start_time: datetime
    end_time: datetime
    activity_type: str  # 'driving', 'work', 'available', 'rest', 'break'
    duration_minutes: int
    vehicle_speed: float = 0.0
    distance_km: float = 0.0

@dataclass
class WorkShift:
    """Klasa reprezentująca zmianę pracy"""
    driver_name: str
    vehicle_id: str
    date: datetime
    activities: List[DriverActivity]
    total_driving_time: int = 0
    total_work_time: int = 0
    total_rest_time: int = 0
    total_distance: float = 0.0

class DDDParser:
    """Uproszczony parser plików .DDD"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_ddd_file(self, file_path: str) -> WorkShift:
        """Parsuje plik .DDD i zwraca WorkShift"""
        try:
            with open(file_path, 'rb') as file:
                raw_data = file.read()

            # Podstawowe parsowanie - w rzeczywistości potrzebujesz implementacji tacho_lib
            return self._parse_raw_data(raw_data, file_path)

        except Exception as e:
            self.logger.error(f"Błąd parsowania {file_path}: {str(e)}")
            return self._create_dummy_workshift(file_path)

    def _parse_raw_data(self, raw_data: bytes, file_path: str) -> WorkShift:
        """Parsuje surowe dane z pliku .DDD"""
        # Wyciągnij informacje z nazwy pliku
        filename = os.path.basename(file_path)
        parts = filename.replace('.DDD', '').split('_')

        if len(parts) >= 4:
            date_str = parts[1]  # C_20190201_0829_W_Piechowicz_19503120533500.DDD
            time_str = parts[2]
            driver_name = parts[4] if len(parts) > 4 else "Nieznany"

            try:
                shift_date = datetime.strptime(date_str, '%Y%m%d')
            except:
                shift_date = datetime.now()
        else:
            shift_date = datetime.now()
            driver_name = "Nieznany"

        # Symulacja parsowania danych tachografu
        activities = self._generate_sample_activities(shift_date)

        workshift = WorkShift(
            driver_name=driver_name,
            vehicle_id=f"VEH_{filename[:10]}",
            date=shift_date,
            activities=activities
        )

        # Oblicz sumy
        self._calculate_totals(workshift)

        return workshift

    def _generate_sample_activities(self, shift_date: datetime) -> List[DriverActivity]:
        """Generuje przykładowe aktywności dla demonstracji"""
        activities = []
        current_time = shift_date.replace(hour=6, minute=0, second=0)

        # Przykładowa zmiana 8-godzinna
        activities.append(DriverActivity(
            start_time=current_time,
            end_time=current_time + timedelta(hours=1, minutes=30),
            activity_type='driving',
            duration_minutes=90,
            vehicle_speed=75.0,
            distance_km=112.5
        ))

        current_time += timedelta(hours=1, minutes=30)
        activities.append(DriverActivity(
            start_time=current_time,
            end_time=current_time + timedelta(minutes=45),
            activity_type='break',
            duration_minutes=45
        ))

        current_time += timedelta(minutes=45)
        activities.append(DriverActivity(
            start_time=current_time,
            end_time=current_time + timedelta(hours=2),
            activity_type='driving',
            duration_minutes=120,
            vehicle_speed=80.0,
            distance_km=160.0
        ))

        current_time += timedelta(hours=2)
        activities.append(DriverActivity(
            start_time=current_time,
            end_time=current_time + timedelta(minutes=30),
            activity_type='rest',
            duration_minutes=30
        ))

        current_time += timedelta(minutes=30)
        activities.append(DriverActivity(
            start_time=current_time,
            end_time=current_time + timedelta(hours=3),
            activity_type='driving',
            duration_minutes=180,
            vehicle_speed=70.0,
            distance_km=210.0
        ))

        return activities

    def _calculate_totals(self, workshift: WorkShift):
        """Oblicza sumy czasów i dystansu"""
        workshift.total_driving_time = sum(
            a.duration_minutes for a in workshift.activities if a.activity_type == 'driving'
        )
        workshift.total_work_time = sum(
            a.duration_minutes for a in workshift.activities if a.activity_type in ['driving', 'work']
        )
        workshift.total_rest_time = sum(
            a.duration_minutes for a in workshift.activities if a.activity_type in ['rest', 'break']
        )
        workshift.total_distance = sum(a.distance_km for a in workshift.activities)

    def _create_dummy_workshift(self, file_path: str) -> WorkShift:
        """Tworzy podstawowy workshift w przypadku błędu"""
        filename = os.path.basename(file_path)
        return WorkShift(
            driver_name="Błąd parsowania",
            vehicle_id="ERROR",
            date=datetime.now(),
            activities=[]
        )

class WorkshiftGenerator:
    """Generator raportów workshiftów"""

    def generate_excel_report(self, workshifts: List[WorkShift], output_path: str):
        """Generuje raport Excel z workshiftami"""

        # Przygotuj dane dla DataFrame
        data = []
        for ws in workshifts:
            for activity in ws.activities:
                data.append({
                    'Data': ws.date.strftime('%Y-%m-%d'),
                    'Kierowca': ws.driver_name,
                    'Pojazd': ws.vehicle_id,
                    'Czas rozpoczęcia': activity.start_time.strftime('%H:%M'),
                    'Czas zakończenia': activity.end_time.strftime('%H:%M'),
                    'Typ aktywności': self._get_activity_name(activity.activity_type),
                    'Czas trwania (min)': activity.duration_minutes,
                    'Prędkość średnia (km/h)': round(activity.vehicle_speed, 1),
                    'Dystans (km)': round(activity.distance_km, 2)
                })

        df = pd.DataFrame(data)

        # Utwórz plik Excel z formatowaniem
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Workshifts', index=False)

            # Dodaj arkusz podsumowania
            summary_data = self._create_summary(workshifts)
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Podsumowanie', index=False)

    def _get_activity_name(self, activity_type: str) -> str:
        """Konwertuje typ aktywności na polską nazwę"""
        names = {
            'driving': 'Jazda',
            'work': 'Praca',
            'available': 'Dostępność',
            'rest': 'Odpoczynek',
            'break': 'Przerwa'
        }
        return names.get(activity_type, activity_type)

    def _create_summary(self, workshifts: List[WorkShift]) -> List[Dict]:
        """Tworzy dane podsumowania"""
        summary = []
        for ws in workshifts:
            summary.append({
                'Data': ws.date.strftime('%Y-%m-%d'),
                'Kierowca': ws.driver_name,
                'Pojazd': ws.vehicle_id,
                'Czas jazdy (h)': round(ws.total_driving_time / 60, 2),
                'Czas pracy (h)': round(ws.total_work_time / 60, 2),
                'Czas odpoczynku (h)': round(ws.total_rest_time / 60, 2),
                'Dystans całkowity (km)': round(ws.total_distance, 2)
            })
        return summary

# Inicjalizacja parserów
ddd_parser = DDDParser()
workshift_generator = WorkshiftGenerator()

@app.route('/')
def index():
    """Strona główna"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    """Endpoint do uploadu plików"""
    global processing_status

    if processing_status['active']:
        return jsonify({'error': 'Przetwarzanie już w toku'}), 400

    if 'files' not in request.files:
        return jsonify({'error': 'Brak plików'}), 400

    files = request.files.getlist('files')
    start_date = request.form.get('start_date')
    end_date = request.form.get('end_date')

    # Walidacja dat
    try:
        if start_date:
            start_date = datetime.strptime(start_date, '%Y-%m-%d')
        if end_date:
            end_date = datetime.strptime(end_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Nieprawidłowy format daty'}), 400

    # Zapisz pliki
    uploaded_files = []
    for file in files:
        if file.filename and file.filename.endswith('.DDD'):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            uploaded_files.append(file_path)

    if not uploaded_files:
        return jsonify({'error': 'Brak prawidłowych plików .DDD'}), 400

    # Rozpocznij przetwarzanie w tle
    Thread(target=process_files_background,
           args=(uploaded_files, start_date, end_date)).start()

    return jsonify({
        'message': f'Rozpoczęto przetwarzanie {len(uploaded_files)} plików',
        'total_files': len(uploaded_files)
    })

@app.route('/status')
def get_status():
    """Pobierz status przetwarzania"""
    global processing_status

    status = processing_status.copy()
    if status['start_time']:
        elapsed = (datetime.now() - status['start_time']).total_seconds()
        status['elapsed_time'] = elapsed

        if status['processed_files'] > 0:
            avg_time_per_file = elapsed / status['processed_files']
            remaining_files = status['total_files'] - status['processed_files']
            status['estimated_time_remaining'] = avg_time_per_file * remaining_files

    return jsonify(status)

@app.route('/download/<filename>')
def download_file(filename):
    """Pobierz wygenerowany plik"""
    file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return jsonify({'error': 'Plik nie istnieje'}), 404

def process_files_background(file_paths: List[str], start_date=None, end_date=None):
    """Przetwarzaj pliki w tle"""
    global processing_status

    processing_status = {
        'active': True,
        'total_files': len(file_paths),
        'processed_files': 0,
        'current_file': '',
        'start_time': datetime.now(),
        'errors': []
    }

    workshifts = []

    try:
        for file_path in file_paths:
            processing_status['current_file'] = os.path.basename(file_path)

            try:
                # Parsuj plik .DDD
                workshift = ddd_parser.parse_ddd_file(file_path)

                # Filtruj według dat jeśli podano
                if start_date and workshift.date < start_date:
                    continue
                if end_date and workshift.date > end_date:
                    continue

                workshifts.append(workshift)

            except Exception as e:
                error_msg = f"Błąd przetwarzania {os.path.basename(file_path)}: {str(e)}"
                processing_status['errors'].append(error_msg)
                app.logger.error(error_msg)

            processing_status['processed_files'] += 1
            time.sleep(0.1)  # Krótka przerwa żeby nie przeciążać systemu

        # Generuj raport Excel
        if workshifts:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_filename = f'workshifts_{timestamp}.xlsx'
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)

            workshift_generator.generate_excel_report(workshifts, output_path)
            processing_status['output_file'] = output_filename

    except Exception as e:
        processing_status['errors'].append(f"Błąd krytyczny: {str(e)}")
        app.logger.error(f"Błąd krytyczny podczas przetwarzania: {str(e)}")

    finally:
        processing_status['active'] = False

        # Wyczyść pliki tymczasowe
        for file_path in file_paths:
            try:
                os.remove(file_path)
            except:
                pass

# Cleanup functions
def cleanup_old_files():
    """Czyści stare pliki z katalogów upload i output"""
    try:
        cutoff_time = datetime.now() - timedelta(hours=app.config.get('FILE_CLEANUP_HOURS', 24))

        for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER']]:
            for filename in os.listdir(folder):
                filepath = os.path.join(folder, filename)
                if os.path.isfile(filepath):
                    file_time = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if file_time < cutoff_time:
                        os.remove(filepath)
                        app.logger.info(f"Usunięto stary plik: {filepath}")
    except Exception as e:
        app.logger.error(f"Błąd podczas czyszczenia plików: {str(e)}")

@app.errorhandler(413)
def too_large(e):
    """Obsługa błędu zbyt dużego pliku"""
    return jsonify({'error': 'Plik jest zbyt duży. Maksymalny rozmiar to 500MB.'}), 413

@app.errorhandler(500)
def internal_error(error):
    """Obsługa błędów serwera"""
    app.logger.error(f'Server Error: {error}')
    return jsonify({'error': 'Błąd wewnętrzny serwera'}), 500

@app.errorhandler(404)
def not_found_error(error):
    """Obsługa błędu 404"""
    return jsonify({'error': 'Nie znaleziono zasobu'}), 404

# Register cleanup function to run on app shutdown
atexit.register(cleanup_old_files)

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    # Uruchom cleanup przy starcie
    cleanup_old_files()
    app.run(debug=True, host='0.0.0.0', port=5000)
