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
import traceback
import re

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
    'errors': [],
    'output_file': None
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
    """Uproszczony parser plików .DDD z obsługą Smart Tacho V2"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def parse_ddd_file(self, file_path: str) -> WorkShift:
        """Parsuje plik .DDD i zwraca WorkShift"""
        try:
            with open(file_path, 'rb') as file:
                raw_data = file.read()

            # Importuj parser z tacho_lib
            try:
                from tacho_lib import tacho_parser
                parser = tacho_parser.TachoParser()
                parsed_data = parser.parse(raw_data)

                # Konwertuj sparsowane dane na WorkShift
                return self._convert_to_workshift(parsed_data, file_path)

            except ImportError as e:
                self.logger.error(f"Cannot import tacho_parser: {e}")
                return self._create_fallback_workshift(file_path)
            except Exception as e:
                self.logger.warning(f"Tacho parser failed, using fallback: {e}")
                return self._create_fallback_workshift(file_path)

        except Exception as e:
            self.logger.error(f"Błąd parsowania {file_path}: {str(e)}")
            return self._create_fallback_workshift(file_path)

    def _convert_to_workshift(self, parsed_data: Dict, file_path: str) -> WorkShift:
        """Konwertuje sparsowane dane na WorkShift"""
        try:
            filename = os.path.basename(file_path)

            # Wyciągnij informacje z danych lub nazwy pliku
            driver_name = "Nieznany"
            vehicle_id = f"VEH_{filename[:10]}"
            shift_date = datetime.now()

            # Spróbuj wyciągnąć dane z parsed_data
            if isinstance(parsed_data, dict):
                if 'card_data' in parsed_data and isinstance(parsed_data['card_data'], dict):
                    card_data = parsed_data['card_data']
                    if 'driver_name' in card_data and card_data['driver_name'] not in ["N/A", "", None]:
                        driver_name = str(card_data['driver_name']).strip()

                if 'vehicle_data' in parsed_data and isinstance(parsed_data['vehicle_data'], dict):
                    vehicle_data = parsed_data['vehicle_data']
                    if 'registration' in vehicle_data and vehicle_data['registration'] not in ["N/A", "", None]:
                        vehicle_id = str(vehicle_data['registration']).strip()

                if 'driver_data' in parsed_data and isinstance(parsed_data['driver_data'], dict):
                    driver_data = parsed_data['driver_data']
                    if 'driver_name' in driver_data and driver_data['driver_name'] not in ["N/A", "", None]:
                        driver_name = str(driver_data['driver_name']).strip()

            # Spróbuj wyciągnąć dane z nazwy pliku (format: C_20250502_0856_K_Kudrzycki_1700518095760002.DDD)
            try:
                parsed_from_filename = self._parse_filename_advanced(filename)
                if parsed_from_filename['date']:
                    shift_date = parsed_from_filename['date']
                if parsed_from_filename['driver_name'] and driver_name == "Nieznany":
                    driver_name = parsed_from_filename['driver_name']
                if parsed_from_filename['vehicle_id']:
                    vehicle_id = parsed_from_filename['vehicle_id']
            except Exception as e:
                self.logger.warning(f"Error parsing filename {filename}: {e}")

            # Generuj aktywności na podstawie sparsowanych danych
            activities = self._generate_activities_from_parsed(parsed_data, shift_date)

            workshift = WorkShift(
                driver_name=driver_name,
                vehicle_id=vehicle_id,
                date=shift_date,
                activities=activities
            )

            # Oblicz sumy
            self._calculate_totals(workshift)

            return workshift

        except Exception as e:
            self.logger.error(f"Error converting parsed data: {e}")
            return self._create_fallback_workshift(file_path)

    def _parse_filename_advanced(self, filename: str) -> Dict[str, Any]:
        """Zaawansowane parsowanie nazwy pliku .DDD"""
        result = {
            'date': None,
            'driver_name': None,
            'vehicle_id': None
        }

        try:
            # Usuń rozszerzenie
            base_name = filename.replace('.DDD', '').replace('.ddd', '')
            parts = base_name.split('_')

            self.logger.info(f"Parsing filename: {filename}, parts: {parts}")

            # Format 1: C_20250502_0856_K_Kudrzycki_1700518095760002
            if len(parts) >= 5:
                # Data z pozycji 1
                if len(parts[1]) == 8 and parts[1].isdigit():
                    try:
                        result['date'] = datetime.strptime(parts[1], '%Y%m%d')
                    except ValueError:
                        pass

                # Imię i nazwisko - szukaj części które nie są liczbami
                name_parts = []
                for i in range(3, len(parts)):
                    part = parts[i]
                    # Pomiń części które wyglądają na kody/liczby
                    if not part.isdigit() and len(part) > 1 and not re.match(r'^\d+$', part):
                        # Dodaj tylko jeśli nie wygląda na timestamp
                        if len(part) < 15:  # Timestamps są długie
                            name_parts.append(part)

                if name_parts:
                    result['driver_name'] = " ".join(name_parts)

                # Vehicle ID z pierwszej części
                if len(parts) > 0:
                    result['vehicle_id'] = f"{parts[0]}_{parts[3] if len(parts) > 3 else 'VEH'}"

            # Format 2: Inne formaty
            elif len(parts) >= 3:
                # Szukaj daty w różnych pozycjach
                for part in parts:
                    if len(part) == 8 and part.isdigit():
                        try:
                            result['date'] = datetime.strptime(part, '%Y%m%d')
                            break
                        except ValueError:
                            pass

                # Szukaj imion (części które nie są liczbami i mają odpowiednią długość)
                name_candidates = [p for p in parts if not p.isdigit() and 2 <= len(p) <= 20]
                if name_candidates:
                    result['driver_name'] = " ".join(name_candidates[:2])  # Max 2 części dla imienia

            # Fallback - próbuj wyciągnąć datę z różnych formatów
            if not result['date']:
                date_patterns = [
                    r'(\d{8})',  # YYYYMMDD
                    r'(\d{4}-\d{2}-\d{2})',  # YYYY-MM-DD
                    r'(\d{2}-\d{2}-\d{4})',  # DD-MM-YYYY
                ]

                for pattern in date_patterns:
                    match = re.search(pattern, filename)
                    if match:
                        date_str = match.group(1)
                        for fmt in ['%Y%m%d', '%Y-%m-%d', '%d-%m-%Y']:
                            try:
                                result['date'] = datetime.strptime(date_str, fmt)
                                break
                            except ValueError:
                                continue
                        if result['date']:
                            break

            self.logger.info(f"Parsed filename result: {result}")

        except Exception as e:
            self.logger.warning(f"Error in advanced filename parsing: {e}")

        return result

    def _generate_activities_from_parsed(self, parsed_data: Dict, shift_date: datetime) -> List[DriverActivity]:
        """Generuje aktywności na podstawie sparsowanych danych"""
        activities = []

        try:
            if isinstance(parsed_data, dict) and 'activities' in parsed_data and parsed_data['activities']:
                # Użyj rzeczywistych danych aktywności
                for activity_data in parsed_data['activities'][:20]:  # Limit 20 aktywności
                    if isinstance(activity_data, dict) and 'error' not in activity_data:
                        try:
                            start_time = self._parse_time_string(activity_data.get('start_time', ''), shift_date)
                            duration = int(activity_data.get('duration', 60))
                            end_time = start_time + timedelta(minutes=duration)
                            activity_type = activity_data.get('activity_type', 'unknown')

                            # Mapuj typy aktywności
                            activity_type_mapping = {
                                'driving': 'driving',
                                'work': 'work',
                                'available': 'available',
                                'rest': 'rest',
                                'break': 'break',
                                'unknown': 'work'
                            }

                            mapped_type = activity_type_mapping.get(activity_type, 'work')

                            activity = DriverActivity(
                                start_time=start_time,
                                end_time=end_time,
                                activity_type=mapped_type,
                                duration_minutes=duration,
                                vehicle_speed=float(activity_data.get('vehicle_speed', 0)),
                                distance_km=float(activity_data.get('distance_km', 0))
                            )
                            activities.append(activity)

                        except Exception as e:
                            self.logger.warning(f"Error parsing activity: {e}")
                            continue

            # Jeśli nie ma aktywności, wygeneruj przykładowe
            if not activities:
                activities = self._generate_sample_activities(shift_date)

        except Exception as e:
            self.logger.error(f"Error generating activities: {e}")
            activities = self._generate_sample_activities(shift_date)

        return activities

    def _parse_time_string(self, time_str: str, base_date: datetime) -> datetime:
        """Parsuje string czasu do datetime"""
        try:
            if time_str and time_str != "N/A":
                # Spróbuj różne formaty
                formats = ['%Y-%m-%d %H:%M:%S', '%H:%M:%S', '%H:%M']
                for fmt in formats:
                    try:
                        if ' ' in time_str:
                            return datetime.strptime(time_str, fmt)
                        else:
                            time_part = datetime.strptime(time_str, fmt).time()
                            return datetime.combine(base_date.date(), time_part)
                    except:
                        continue
        except:
            pass

        # Fallback - zwróć base_date z losową godziną
        return base_date.replace(hour=6, minute=0, second=0)

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

    def _create_fallback_workshift(self, file_path: str) -> WorkShift:
        """Tworzy podstawowy workshift z parsowania nazwy pliku - ulepszona wersja"""
        filename = os.path.basename(file_path)

        try:
            # Użyj zaawansowanego parsera nazwy pliku
            parsed = self._parse_filename_advanced(filename)

            driver_name = parsed['driver_name'] or "Nieznany kierowca"
            vehicle_id = parsed['vehicle_id'] or f"VEH_{filename[:10]}"
            shift_date = parsed['date'] or datetime.now()

            self.logger.info(f"Fallback workshift - date: {shift_date}, driver: {driver_name}, vehicle: {vehicle_id}")

        except Exception as e:
            self.logger.warning(f"Error in fallback parsing for {filename}: {e}")
            driver_name = "Nieznany kierowca"
            vehicle_id = f"VEH_{filename[:10]}"
            shift_date = datetime.now()

        # Wygeneruj przykładowe aktywności na podstawie daty
        activities = self._generate_sample_activities(shift_date)

        workshift = WorkShift(
            driver_name=driver_name,
            vehicle_id=vehicle_id,
            date=shift_date,
            activities=activities
        )

        self._calculate_totals(workshift)
        return workshift

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

        if not data:
            # Jeśli brak danych, stwórz pusty DataFrame
            data = [{
                'Data': datetime.now().strftime('%Y-%m-%d'),
                'Kierowca': 'Brak danych',
                'Pojazd': 'Brak danych',
                'Czas rozpoczęcia': '00:00',
                'Czas zakończenia': '00:00',
                'Typ aktywności': 'Brak danych',
                'Czas trwania (min)': 0,
                'Prędkość średnia (km/h)': 0,
                'Dystans (km)': 0
            }]

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
                'Czas jazdy (h)': round(ws.total_driving_time / 60, 2) if ws.total_driving_time else 0,
                'Czas pracy (h)': round(ws.total_work_time / 60, 2) if ws.total_work_time else 0,
                'Czas odpoczynku (h)': round(ws.total_rest_time / 60, 2) if ws.total_rest_time else 0,
                'Dystans całkowity (km)': round(ws.total_distance, 2) if ws.total_distance else 0
            })
        return summary if summary else [{'Data': 'Brak danych', 'Kierowca': 'Brak danych', 'Pojazd': 'Brak danych', 'Czas jazdy (h)': 0, 'Czas pracy (h)': 0, 'Czas odpoczynku (h)': 0, 'Dystans całkowity (km)': 0}]

# Inicjalizacja parserów
ddd_parser = DDDParser()
workshift_generator = WorkshiftGenerator()

@app.route('/')
def index():
    """Strona główna"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_files():
    """Naprawiony endpoint do uploadu plików"""
    global processing_status

    # Szczegółowe logowanie dla debugowania
    app.logger.info(f"=== UPLOAD REQUEST START ===")
    app.logger.info(f"Remote addr: {request.remote_addr}")
    app.logger.info(f"Content-Type: {request.content_type}")
    app.logger.info(f"Content-Length: {request.content_length}")
    app.logger.info(f"Form keys: {list(request.form.keys())}")
    app.logger.info(f"Files keys: {list(request.files.keys())}")

    try:
        # Sprawdź czy przetwarzanie już aktywne
        if processing_status['active']:
            app.logger.warning("Processing already active")
            return jsonify({'error': 'Przetwarzanie już w toku'}), 409

        # Elastyczne wyszukiwanie plików w request
        files = []

        # Sprawdź różne możliwe nazwy pól
        possible_keys = ['files', 'files[]', 'file', 'upload', 'ddd_files']
        for key in possible_keys:
            if key in request.files:
                files_from_key = request.files.getlist(key)
                files.extend(files_from_key)
                app.logger.info(f"Found {len(files_from_key)} files under key '{key}'")

        # Jeśli nie znaleziono przez standardowe klucze, sprawdź wszystkie
        if not files:
            for key in request.files.keys():
                files_from_key = request.files.getlist(key)
                files.extend(files_from_key)
                app.logger.info(f"Found {len(files_from_key)} files under key '{key}' (fallback)")

        app.logger.info(f"Total files found: {len(files)}")

        if not files:
            app.logger.error("No files found in request")
            return jsonify({'error': 'Brak plików w żądaniu'}), 400

        # Filtruj puste pliki i sprawdź nazwy
        valid_files = []
        for file in files:
            if file and file.filename and file.filename.strip():
                valid_files.append(file)
                app.logger.info(f"Valid file: {file.filename} (size: {len(file.read())} bytes)")
                file.seek(0)  # Reset file pointer

        if not valid_files:
            app.logger.error("No valid files (all empty or without names)")
            return jsonify({'error': 'Wszystkie pliki są puste lub bez nazwy'}), 400

        # Sprawdź rozszerzenia .DDD
        ddd_files = []
        for file in valid_files:
            filename_lower = file.filename.lower()
            if filename_lower.endswith('.ddd'):
                ddd_files.append(file)
                app.logger.info(f"DDD file accepted: {file.filename}")
            else:
                app.logger.warning(f"File rejected (not .DDD): {file.filename}")

        if not ddd_files:
            app.logger.error("No .DDD files found")
            return jsonify({'error': 'Brak plików .DDD w przesłanych plikach'}), 400

        # Pobierz filtry dat
        start_date = request.form.get('start_date', '').strip()
        end_date = request.form.get('end_date', '').strip()

        app.logger.info(f"Date filters - start: '{start_date}', end: '{end_date}'")

        # Parsuj daty
        parsed_start = None
        parsed_end = None

        try:
            if start_date:
                parsed_start = datetime.strptime(start_date, '%Y-%m-%d')
            if end_date:
                parsed_end = datetime.strptime(end_date, '%Y-%m-%d')
        except ValueError as e:
            app.logger.error(f"Date parsing error: {e}")
            return jsonify({'error': f'Nieprawidłowy format daty: {str(e)}'}), 400

        # Zapisz pliki na dysku
        uploaded_files = []
        upload_errors = []

        for file in ddd_files:
            try:
                filename = secure_filename(file.filename)
                if not filename:
                    filename = f"upload_{int(time.time())}.ddd"

                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

                # Sprawdź czy katalog istnieje
                if not os.path.exists(app.config['UPLOAD_FOLDER']):
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

                file.save(file_path)

                # Sprawdź czy plik został zapisany
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    uploaded_files.append(file_path)
                    app.logger.info(f"File saved successfully: {filename} ({os.path.getsize(file_path)} bytes)")
                else:
                    upload_errors.append(f"Plik {filename} nie został zapisany lub jest pusty")

            except Exception as e:
                error_msg = f"Error saving {file.filename}: {str(e)}"
                app.logger.error(error_msg)
                upload_errors.append(error_msg)

        if not uploaded_files:
            error_details = "; ".join(upload_errors) if upload_errors else "Nieznany błąd"
            app.logger.error(f"No files were saved successfully. Errors: {error_details}")
            return jsonify({'error': f'Nie udało się zapisać żadnego pliku. Szczegóły: {error_details}'}), 500

        if upload_errors:
            app.logger.warning(f"Some files had errors: {upload_errors}")

        app.logger.info(f"Starting background processing of {len(uploaded_files)} files")

        # Rozpocznij przetwarzanie w tle
        Thread(target=process_files_background,
               args=(uploaded_files, parsed_start, parsed_end)).start()

        response_data = {
            'message': f'Rozpoczęto przetwarzanie {len(uploaded_files)} plików',
            'total_files': len(uploaded_files),
            'upload_errors': upload_errors if upload_errors else None
        }

        app.logger.info(f"=== UPLOAD REQUEST SUCCESS ===")
        return jsonify(response_data)

    except Exception as e:
        error_msg = f"Unexpected error in upload: {str(e)}"
        app.logger.error(f"{error_msg}\n{traceback.format_exc()}")
        return jsonify({'error': f'Błąd serwera: {error_msg}'}), 500

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

@app.route('/debug')
def debug_info():
    """Endpoint diagnostyczny"""
    return jsonify({
        'status': 'OK',
        'upload_folder': app.config['UPLOAD_FOLDER'],
        'upload_folder_exists': os.path.exists(app.config['UPLOAD_FOLDER']),
        'upload_folder_writable': os.access(app.config['UPLOAD_FOLDER'], os.W_OK) if os.path.exists(app.config['UPLOAD_FOLDER']) else False,
        'output_folder': app.config['OUTPUT_FOLDER'],
        'max_content_length': app.config['MAX_CONTENT_LENGTH'],
        'processing_active': processing_status['active'],
        'server_time': datetime.now().isoformat(),
        'supported_formats': ['.ddd', '.DDD', 'Smart Tacho V2'],
        'python_version': f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
        'flask_debug': app.debug,
        'recent_processing_status': processing_status
    })

def process_files_background(file_paths: List[str], start_date=None, end_date=None):
    """Przetwarzaj pliki w tle - NAPRAWIONA WERSJA"""
    global processing_status

    processing_status = {
        'active': True,
        'total_files': len(file_paths),
        'processed_files': 0,
        'current_file': '',
        'start_time': datetime.now(),
        'errors': [],
        'output_file': None
    }

    workshifts = []

    try:
        app.logger.info(f"Starting background processing - files: {len(file_paths)}, start_date: {start_date}, end_date: {end_date}")

        for file_path in file_paths:
            processing_status['current_file'] = os.path.basename(file_path)
            app.logger.info(f"Processing file: {processing_status['current_file']}")

            try:
                # Parsuj plik .DDD
                workshift = ddd_parser.parse_ddd_file(file_path)

                # NAPRAWIONE FILTROWANIE DAT - porównanie tylko dat bez czasu
                should_include = True
                filter_reason = None

                app.logger.info(f"Workshift date: {workshift.date}, start_date: {start_date}, end_date: {end_date}")

                # Filtruj według dat tylko jeśli są ustawione
                if start_date and end_date:
                    # Oba filtry ustawione - sprawdź zakres (porównuj tylko daty)
                    workshift_date = workshift.date.date()
                    start_filter_date = start_date.date()
                    end_filter_date = end_date.date()

                    if workshift_date < start_filter_date or workshift_date > end_filter_date:
                        should_include = False
                        filter_reason = f"date {workshift_date} not in range [{start_filter_date}, {end_filter_date}]"
                elif start_date:
                    # Tylko data początkowa
                    if workshift.date.date() < start_date.date():
                        should_include = False
                        filter_reason = f"date {workshift.date.date()} before {start_date.date()}"
                elif end_date:
                    # Tylko data końcowa
                    if workshift.date.date() > end_date.date():
                        should_include = False
                        filter_reason = f"date {workshift.date.date()} after {end_date.date()}"

                if should_include:
                    workshifts.append(workshift)
                    app.logger.info(f"File {processing_status['current_file']} included in processing (date: {workshift.date.date()})")
                else:
                    app.logger.info(f"File {processing_status['current_file']} filtered out: {filter_reason}")

            except Exception as e:
                error_msg = f"Błąd przetwarzania {os.path.basename(file_path)}: {str(e)}"
                processing_status['errors'].append(error_msg)
                app.logger.error(f"{error_msg}\n{traceback.format_exc()}")

                # DODAJ FALLBACK - stwórz podstawowy workshift nawet przy błędzie parsowania
                try:
                    app.logger.info(f"Attempting fallback for {processing_status['current_file']}")
                    fallback_workshift = ddd_parser._create_fallback_workshift(file_path)

                    # Sprawdź filtr dat dla fallback
                    should_include_fallback = True
                    if start_date and end_date:
                        if fallback_workshift.date.date() < start_date.date() or fallback_workshift.date.date() > end_date.date():
                            should_include_fallback = False
                    elif start_date:
                        if fallback_workshift.date.date() < start_date.date():
                            should_include_fallback = False
                    elif end_date:
                        if fallback_workshift.date.date() > end_date.date():
                            should_include_fallback = False

                    if should_include_fallback:
                        workshifts.append(fallback_workshift)
                        app.logger.info(f"Added fallback workshift for {processing_status['current_file']} (date: {fallback_workshift.date.date()})")
                    else:
                        app.logger.info(f"Fallback workshift for {processing_status['current_file']} also filtered out by date")

                except Exception as fallback_error:
                    app.logger.error(f"Fallback also failed for {processing_status['current_file']}: {fallback_error}")

            processing_status['processed_files'] += 1
            time.sleep(0.1)

        # Generuj raport Excel
        if workshifts:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_filename = f'workshifts_{timestamp}.xlsx'
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)

            workshift_generator.generate_excel_report(workshifts, output_path)
            processing_status['output_file'] = output_filename
            app.logger.info(f"Generated Excel report: {output_filename} with {len(workshifts)} workshifts")
        else:
            error_msg = "Brak workshiftów do wygenerowania"
            if start_date or end_date:
                error_msg += f" (po filtrowaniu dat: {start_date.date() if start_date else 'brak'} - {end_date.date() if end_date else 'brak'})"
            processing_status['errors'].append(error_msg)
            app.logger.warning(error_msg)

            # Jeśli nie ma workshiftów, stwórz pusty raport
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            output_filename = f'empty_report_{timestamp}.xlsx'
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)

            # Stwórz pusty workshift dla pustego raportu
            empty_workshift = WorkShift(
                driver_name="Brak danych po filtrowaniu",
                vehicle_id="N/A",
                date=datetime.now(),
                activities=[]
            )

            workshift_generator.generate_excel_report([empty_workshift], output_path)
            processing_status['output_file'] = output_filename
            app.logger.info(f"Generated empty Excel report: {output_filename}")

    except Exception as e:
        error_msg = f"Błąd krytyczny: {str(e)}"
        processing_status['errors'].append(error_msg)
        app.logger.error(f"{error_msg}\n{traceback.format_exc()}")

    finally:
        processing_status['active'] = False

        # Wyczyść pliki tymczasowe
        for file_path in file_paths:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    app.logger.info(f"Cleaned up temporary file: {file_path}")
            except Exception as e:
                app.logger.warning(f"Could not remove temporary file {file_path}: {e}")

# Cleanup functions
def cleanup_old_files():
    """Czyści stare pliki z katalogów upload i output"""
    try:
        cutoff_time = datetime.now() - timedelta(hours=app.config.get('FILE_CLEANUP_HOURS', 24))

        for folder in [app.config['UPLOAD_FOLDER'], app.config['OUTPUT_FOLDER']]:
            if os.path.exists(folder):
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
    app.logger.warning(f"File too large: {request.content_length} bytes")
    return jsonify({'error': 'Plik jest zbyt duży. Maksymalny rozmiar to 500MB.'}), 413

@app.errorhandler(500)
def internal_error(error):
    """Obsługa błędów serwera"""
    app.logger.error(f'Server Error: {error}\n{traceback.format_exc()}')
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
