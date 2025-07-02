"""
Implementacja parsera plików .DDD (tachograf cyfrowy)
Bazuje na specyfikacji EU 2016/799 - Digital Tachograph
"""

import struct
import datetime
from typing import Dict, List, Any, Optional
import json
import os

class TachoParser:
    """Parser plików .DDD tachografów cyfrowych"""

    # Kody typów aktywności kierowcy zgodnie z EU 2016/799
    ACTIVITY_TYPES = {
        0x00: 'break',      # Przerwa/odpoczynek
        0x01: 'available',  # Dostępność
        0x02: 'work',       # Praca
        0x03: 'driving',    # Jazda
        0xFF: 'unknown'     # Nieznane
    }

    def __init__(self):
        self.raw_data = None
        self.parsed_data = {}

    def parse(self, raw_data: bytes) -> Dict[str, Any]:
        """Główna metoda parsowania pliku .DDD"""
        self.raw_data = raw_data
        self.parsed_data = {
            'header': self._parse_header(),
            'card_data': self._parse_card_data(),
            'vehicle_data': self._parse_vehicle_data(),
            'activities': self._parse_activities(),
            'events': self._parse_events(),
            'speeds': self._parse_speeds()
        }
        return self.parsed_data

    def _parse_header(self) -> Dict[str, Any]:
        """Parsuje nagłówek pliku .DDD"""
        if len(self.raw_data) < 20:
            return {'error': 'Plik zbyt krótki'}

        try:
            # Podstawowe informacje z nagłówka
            header = {
                'file_type': self.raw_data[0:4].decode('ascii', errors='ignore'),
                'version': struct.unpack('>H', self.raw_data[4:6])[0],
                'creation_time': self._parse_timestamp(self.raw_data[6:10]),
                'data_length': struct.unpack('>I', self.raw_data[10:14])[0],
                'signature': self.raw_data[14:20].hex()
            }
            return header
        except Exception as e:
            return {'error': f'Błąd parsowania nagłówka: {str(e)}'}

    def _parse_card_data(self) -> Dict[str, Any]:
        """Parsuje dane karty kierowcy"""
        try:
            # Szukamy sekcji z danymi karty kierowcy
            card_section = self._find_section(b'\x05\x01')  # Card data tag
            if not card_section:
                return {'error': 'Nie znaleziono danych karty'}

            offset = card_section
            card_data = {
                'driver_name': self._extract_string(offset + 4, 36),
                'license_number': self._extract_string(offset + 40, 16),
                'card_number': self._extract_string(offset + 56, 18),
                'card_expiry': self._parse_timestamp_bcd(offset + 74),
                'issuing_authority': self._extract_string(offset + 78, 36)
            }
            return card_data
        except Exception as e:
            return {'error': f'Błąd parsowania danych karty: {str(e)}'}

    def _parse_vehicle_data(self) -> Dict[str, Any]:
        """Parsuje dane pojazdu"""
        try:
            vehicle_section = self._find_section(b'\x05\x05')  # Vehicle data tag
            if not vehicle_section:
                return {'error': 'Nie znaleziono danych pojazdu'}

            offset = vehicle_section
            vehicle_data = {
                'registration': self._extract_string(offset + 4, 14),
                'vin': self._extract_string(offset + 18, 17),
                'odometer_start': struct.unpack('>I', self.raw_data[offset + 35:offset + 39])[0],
                'odometer_end': struct.unpack('>I', self.raw_data[offset + 39:offset + 43])[0],
                'speed_limit': struct.unpack('>H', self.raw_data[offset + 43:offset + 45])[0]
            }
            return vehicle_data
        except Exception as e:
            return {'error': f'Błąd parsowania danych pojazdu: {str(e)}'}

    def _parse_activities(self) -> List[Dict[str, Any]]:
        """Parsuje aktywności kierowcy"""
        activities = []
        try:
            activity_section = self._find_section(b'\x05\x02')  # Activities tag
            if not activity_section:
                return [{'error': 'Nie znaleziono danych aktywności'}]

            offset = activity_section + 4
            record_count = struct.unpack('>H', self.raw_data[offset:offset + 2])[0]
            offset += 2

            for i in range(min(record_count, 1000)):  # Limit dla bezpieczeństwa
                if offset + 8 > len(self.raw_data):
                    break

                activity = {
                    'start_time': self._parse_timestamp_bcd(offset),
                    'activity_type': self.ACTIVITY_TYPES.get(
                        self.raw_data[offset + 4], 'unknown'
                    ),
                    'duration': struct.unpack('>H', self.raw_data[offset + 5:offset + 7])[0],
                    'location': self._parse_location(offset + 7)
                }

                activities.append(activity)
                offset += 8

        except Exception as e:
            activities.append({'error': f'Błąd parsowania aktywności: {str(e)}'})

        return activities

    def _parse_events(self) -> List[Dict[str, Any]]:
        """Parsuje zdarzenia i wykroczenia"""
        events = []
        try:
            events_section = self._find_section(b'\x05\x03')  # Events tag
            if not events_section:
                return [{'info': 'Brak zdarzeń'}]

            # Implementacja parsowania zdarzeń
            # To może być rozszerzone w zależności od potrzeb

        except Exception as e:
            events.append({'error': f'Błąd parsowania zdarzeń: {str(e)}'})

        return events

    def _parse_speeds(self) -> List[Dict[str, Any]]:
        """Parsuje dane prędkości"""
        speeds = []
        try:
            speed_section = self._find_section(b'\x05\x04')  # Speed data tag
            if not speed_section:
                return [{'info': 'Brak danych prędkości'}]

            # Implementacja parsowania prędkości
            # To może być rozszerzone w zależności od potrzeb

        except Exception as e:
            speeds.append({'error': f'Błąd parsowania prędkości: {str(e)}'})

        return speeds

    def _find_section(self, tag: bytes) -> Optional[int]:
        """Znajduje sekcję o określonym tagu"""
        try:
            return self.raw_data.find(tag)
        except:
            return None

    def _extract_string(self, offset: int, length: int) -> str:
        """Wyciąga string z danych binarnych"""
        try:
            if offset + length > len(self.raw_data):
                return "N/A"
            return self.raw_data[offset:offset + length].decode('latin-1', errors='ignore').strip('\x00')
        except:
            return "N/A"

    def _parse_timestamp(self, data: bytes) -> str:
        """Parsuje timestamp Unix"""
        try:
            if len(data) >= 4:
                timestamp = struct.unpack('>I', data[:4])[0]
                dt = datetime.datetime.fromtimestamp(timestamp)
                return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            pass
        return "N/A"

    def _parse_timestamp_bcd(self, offset: int) -> str:
        """Parsuje timestamp w formacie BCD"""
        try:
            if offset + 4 > len(self.raw_data):
                return "N/A"

            # Format BCD: YYMMDDHHMM
            bcd_data = self.raw_data[offset:offset + 4]
            year = 2000 + self._bcd_to_int(bcd_data[0])
            month = self._bcd_to_int(bcd_data[1])
            day = self._bcd_to_int(bcd_data[2])
            hour = self._bcd_to_int(bcd_data[3] >> 4)
            minute = self._bcd_to_int(bcd_data[3] & 0x0F) * 10

            dt = datetime.datetime(year, month, day, hour, minute)
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except:
            return "N/A"

    def _bcd_to_int(self, bcd_byte: int) -> int:
        """Konwertuje BCD na int"""
        return ((bcd_byte >> 4) * 10) + (bcd_byte & 0x0F)

    def _parse_location(self, offset: int) -> str:
        """Parsuje lokalizację GPS"""
        try:
            if offset + 8 > len(self.raw_data):
                return "N/A"

            # Uproszczone parsowanie lokalizacji
            lat_raw = struct.unpack('>i', self.raw_data[offset:offset + 4])[0]
            lon_raw = struct.unpack('>i', self.raw_data[offset + 4:offset + 8])[0]

            lat = lat_raw / 1000000.0
            lon = lon_raw / 1000000.0

            return f"{lat:.6f},{lon:.6f}"
        except:
            return "N/A"

# Funkcje kompatybilne z oryginalnym API
def print_analysis(raw_data: bytes):
    """Drukuje analizę pliku .DDD"""
    parser = TachoParser()
    data = parser.parse(raw_data)

    print("=== ANALIZA PLIKU .DDD ===")
    print(f"Nagłówek: {data.get('header', {})}")
    print(f"Dane karty: {data.get('card_data', {})}")
    print(f"Dane pojazdu: {data.get('vehicle_data', {})}")
    print(f"Liczba aktywności: {len(data.get('activities', []))}")
    print(f"Liczba zdarzeń: {len(data.get('events', []))}")

def save_analysis(raw_data: bytes):
    """Zapisuje analizę do pliku"""
    parser = TachoParser()
    data = parser.parse(raw_data)

    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'analysis_{timestamp}.json'

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    print(f"Analiza zapisana do: {filename}")

def print_raw_data(raw_data: bytes):
    """Drukuje surowe dane"""
    print("=== SUROWE DANE ===")
    print(f"Rozmiar pliku: {len(raw_data)} bajtów")
    print("Pierwsze 100 bajtów (hex):")
    print(raw_data[:100].hex())

def save_raw_data(raw_data: bytes):
    """Zapisuje surowe dane do pliku"""
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'{timestamp}_raw_output.txt'

    with open(filename, 'w') as f:
        f.write(f"Rozmiar pliku: {len(raw_data)} bajtów\n")
        f.write("Dane hex:\n")
        f.write(raw_data.hex())

    print(f"Surowe dane zapisane do: {filename}")

def print_parsed_data_to_console(raw_data: bytes):
    """Drukuje przetworzone dane do konsoli"""
    parser = TachoParser()
    data = parser.parse(raw_data)

    print("=== PRZETWORZONE DANE ===")
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
