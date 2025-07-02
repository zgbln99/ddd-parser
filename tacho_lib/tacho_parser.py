"""
Implementacja parsera plików .DDD (tachograf cyfrowy) z obsługą Smart Tacho V2
Bazuje na specyfikacji EU 2016/799 - Digital Tachograph + Smart Tacho V2
"""

import struct
import datetime
from typing import Dict, List, Any, Optional
import json
import os
import re
import logging

class TachoParser:
    """Parser plików .DDD tachografów cyfrowych z obsługą Smart Tacho V2"""

    # Kody typów aktywności kierowcy zgodnie z EU 2016/799
    ACTIVITY_TYPES = {
        0x00: 'break',      # Przerwa/odpoczynek
        0x01: 'available',  # Dostępność
        0x02: 'work',       # Praca
        0x03: 'driving',    # Jazda
        0xFF: 'unknown'     # Nieznane
    }

    # Smart Tacho V2 activity types
    SMART_V2_ACTIVITY_TYPES = {
        0x10: 'driving',
        0x20: 'work',
        0x30: 'available',
        0x40: 'break',
        0x50: 'rest',
        0xFF: 'unknown'
    }

    def __init__(self):
        self.raw_data = None
        self.parsed_data = {}
        self.logger = logging.getLogger(__name__)

    def parse(self, raw_data: bytes) -> Dict[str, Any]:
        """Główna metoda parsowania pliku .DDD z obsługą Smart Tacho V2"""
        self.raw_data = raw_data

        # Wykryj typ tachografu
        tacho_version = self.detect_tacho_version(raw_data)
        self.logger.info(f"Detected tachograph type: {tacho_version}")

        if tacho_version == 'Smart Tacho V2':
            # Użyj dedykowanego parsera dla Smart Tacho V2
            self.parsed_data = self.parse_smart_tacho_v2(raw_data)
        else:
            # Standardowy parser
            self.parsed_data = {
                'format': tacho_version,
                'header': self._parse_header(),
                'card_data': self._parse_card_data(),
                'vehicle_data': self._parse_vehicle_data(),
                'activities': self._parse_activities(),
                'events': self._parse_events(),
                'speeds': self._parse_speeds()
            }

        return self.parsed_data

    def detect_tacho_version(self, raw_data: bytes) -> str:
        """Wykrywa wersję tachografu na podstawie danych"""
        try:
            # Konwertuj na lowercase dla łatwiejszego wyszukiwania
            data_str = str(raw_data[:2000]).lower()

            # Smart Tacho V2 - charakterystyczne znaczniki
            smart_v2_markers = [
                b'smart_tacho_v2',
                b'vdo_smart',
                b'stv2',
                b'smart tacho',
                b'tacho smart',
                b'smarttacho',
                b'continental vdo',
                b'kienzle',
                b'stoneridge se5000'
            ]

            for marker in smart_v2_markers:
                if marker in raw_data[:1000].lower():
                    return 'Smart Tacho V2'

            # Sprawdź wzorce w danych
            if b'VDO' in raw_data[:500] and b'Smart' in raw_data[:500]:
                return 'Smart Tacho V2'

            # Sprawdź strukturę pliku - Smart Tacho V2 ma inne nagłówki
            if len(raw_data) > 100:
                # Smart Tacho V2 często zaczyna się od specyficznych bajtów
                header_bytes = raw_data[:20]
                if (header_bytes[0:4] == b'STv2' or
                    header_bytes[0:3] == b'VDO' or
                    b'SMART' in header_bytes):
                    return 'Smart Tacho V2'

            # Standardowy tachograf cyfrowy
            if raw_data[:4] == b'DDD\x00' or raw_data[:3] == b'DDD':
                return 'Standard EU'

            # Inne popularne formaty
            if b'EFAS' in raw_data[:100]:
                return 'EFAS'
            elif b'Stoneridge' in raw_data[:200]:
                return 'Stoneridge'
            elif b'Siemens VDO' in raw_data[:200]:
                return 'Siemens VDO'

            return 'Unknown'
        except Exception as e:
            self.logger.error(f"Error detecting tacho version: {e}")
            return 'Unknown'

    def parse_smart_tacho_v2(self, raw_data: bytes) -> Dict[str, Any]:
        """Parser specjalnie dla Smart Tacho V2"""
        try:
            parsed_data = {
                'format': 'Smart Tacho V2',
                'header': self._parse_v2_header(raw_data),
                'driver_data': self._parse_v2_driver_data(raw_data),
                'vehicle_data': self._parse_v2_vehicle_data(raw_data),
                'activities': self._parse_v2_activities(raw_data),
                'events': self._parse_v2_events(raw_data),
                'speeds': self._parse_v2_speeds(raw_data)
            }
            return parsed_data
        except Exception as e:
            self.logger.error(f"Error parsing Smart Tacho V2: {e}")
            return {'error': f'Błąd parsowania Smart Tacho V2: {str(e)}', 'format': 'Smart Tacho V2'}

    def _parse_v2_header(self, raw_data: bytes) -> Dict[str, Any]:
        """Parsuje nagłówek Smart Tacho V2"""
        try:
            header = {'format': 'Smart Tacho V2'}

            # Szukaj znaczników V2
            markers_found = []

            if b'VDO' in raw_data[:200]:
                vdo_pos = raw_data.find(b'VDO')
                header['device_manufacturer'] = 'VDO'
                markers_found.append('VDO')

                # Data utworzenia może być w różnych offsetach
                for offset in [20, 24, 28, 32]:
                    if vdo_pos + offset + 4 < len(raw_data):
                        timestamp_bytes = raw_data[vdo_pos+offset:vdo_pos+offset+4]
                        parsed_time = self._parse_timestamp(timestamp_bytes)
                        if parsed_time != "N/A":
                            header['creation_time'] = parsed_time
                            break

            if b'SMART' in raw_data[:500]:
                smart_pos = raw_data.find(b'SMART')
                header['device_type'] = 'Smart Tacho'
                markers_found.append('SMART')

            if b'Continental' in raw_data[:300]:
                header['manufacturer'] = 'Continental'
                markers_found.append('Continental')

            # Numer seryjny urządzenia - różne wzorce
            serial_patterns = [
                rb'SN:([A-Z0-9]{8,16})',
                rb'SERIAL:([A-Z0-9]{8,16})',
                rb'S/N:([A-Z0-9]{8,16})',
                rb'SER:([A-Z0-9]{8,16})'
            ]

            for pattern in serial_patterns:
                serial_match = re.search(pattern, raw_data[:800])
                if serial_match:
                    header['serial_number'] = serial_match.group(1).decode('ascii', errors='ignore')
                    break

            # Wersja firmware - różne wzorce
            fw_patterns = [
                rb'FW:([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2})',
                rb'FIRMWARE:([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2})',
                rb'VER:([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2})',
                rb'V([0-9]{1,2}\.[0-9]{1,2}\.[0-9]{1,2})'
            ]

            for pattern in fw_patterns:
                fw_match = re.search(pattern, raw_data[:800])
                if fw_match:
                    header['firmware_version'] = fw_match.group(1).decode('ascii', errors='ignore')
                    break

            # Rozmiar pliku i podstawowe info
            header['file_size'] = len(raw_data)
            header['markers_found'] = markers_found

            # Jeśli nie znaleziono standardowych pól, spróbuj innych metod
            if 'creation_time' not in header:
                header['creation_time'] = self._extract_v2_timestamp_alternative(raw_data)

            return header
        except Exception as e:
            self.logger.error(f"Error parsing V2 header: {e}")
            return {'error': f'Błąd parsowania nagłówka V2: {str(e)}', 'format': 'Smart Tacho V2'}

    def _parse_v2_driver_data(self, raw_data: bytes) -> Dict[str, Any]:
        """Parsuje dane kierowcy Smart Tacho V2"""
        try:
            driver_data = {}

            # Wzorce dla Smart Tacho V2 - bardziej elastyczne
            patterns = {
                'card_number': [
                    rb'CARD:([A-Z0-9]{16})',
                    rb'CARD_NO:([A-Z0-9]{16})',
                    rb'CARDNO:([A-Z0-9]{16})',
                    rb'CARD_NUM:([A-Z0-9]{8,20})'
                ],
                'driver_name': [
                    rb'NAME:([A-ZĄĆĘŁŃÓŚŹŻ\s]{2,40})',
                    rb'DRIVER:([A-ZĄĆĘŁŃÓŚŹŻ\s]{2,40})',
                    rb'SURNAME:([A-ZĄĆĘŁŃÓŚŹŻ\s]{2,40})',
                    rb'DRVR:([A-ZĄĆĘŁŃÓŚŹŻ\s]{2,40})'
                ],
                'license_number': [
                    rb'LIC:([A-Z0-9]{5,20})',
                    rb'LICENSE:([A-Z0-9]{5,20})',
                    rb'LICENCE:([A-Z0-9]{5,20})',
                    rb'DL:([A-Z0-9]{5,20})'
                ]
            }

            for key, pattern_list in patterns.items():
                for pattern in pattern_list:
                    match = re.search(pattern, raw_data[:3000], re.IGNORECASE)
                    if match:
                        driver_data[key] = match.group(1).decode('ascii', errors='ignore').strip()
                        break

            # Dodatkowe parsowanie - szukaj bloków danych kierowcy
            driver_block = self._find_v2_driver_block(raw_data)
            if driver_block:
                driver_data.update(driver_block)

            return driver_data
        except Exception as e:
            self.logger.error(f"Error parsing V2 driver data: {e}")
            return {'error': f'Błąd parsowania danych kierowcy V2: {str(e)}'}

    def _parse_v2_vehicle_data(self, raw_data: bytes) -> Dict[str, Any]:
        """Parsuje dane pojazdu Smart Tacho V2"""
        try:
            vehicle_data = {}

            # VIN - Vehicle Identification Number (bardziej elastyczne wzorce)
            vin_patterns = [
                rb'VIN:([A-HJ-NPR-Z0-9]{17})',
                rb'VEHICLE_ID:([A-HJ-NPR-Z0-9]{17})',
                rb'VIN_NO:([A-HJ-NPR-Z0-9]{17})',
                rb'WVIN:([A-HJ-NPR-Z0-9]{17})'
            ]

            for pattern in vin_patterns:
                vin_match = re.search(pattern, raw_data[:2000])
                if vin_match:
                    vehicle_data['vin'] = vin_match.group(1).decode('ascii')
                    break

            # Numer rejestracyjny
            reg_patterns = [
                rb'REG:([A-Z0-9\s\-]{2,15})',
                rb'PLATE:([A-Z0-9\s\-]{2,15})',
                rb'LICENSE_PLATE:([A-Z0-9\s\-]{2,15})',
                rb'LP:([A-Z0-9\s\-]{2,15})'
            ]

            for pattern in reg_patterns:
                reg_match = re.search(pattern, raw_data[:2000])
                if reg_match:
                    vehicle_data['registration'] = reg_match.group(1).decode('ascii').strip()
                    break

            # Odometer - różne formaty
            odo_patterns = [
                rb'ODO:(\d{6,8})',
                rb'ODOMETER:(\d{6,8})',
                rb'MILEAGE:(\d{6,8})',
                rb'KM:(\d{6,8})'
            ]

            for pattern in odo_patterns:
                odo_match = re.search(pattern, raw_data[:2000])
                if odo_match:
                    vehicle_data['odometer'] = int(odo_match.group(1))
                    break

            # Dodatkowe dane pojazdu z bloków binarnych
            vehicle_block = self._find_v2_vehicle_block(raw_data)
            if vehicle_block:
                vehicle_data.update(vehicle_block)

            return vehicle_data
        except Exception as e:
            self.logger.error(f"Error parsing V2 vehicle data: {e}")
            return {'error': f'Błąd parsowania danych pojazdu V2: {str(e)}'}

    def _parse_v2_activities(self, raw_data: bytes) -> List[Dict[str, Any]]:
        """Parsuje aktywności Smart Tacho V2"""
        activities = []
        try:
            # Smart Tacho V2 może używać różnych formatów bloków aktywności
            activity_patterns = [b'ACT:', b'ACTIVITY:', b'ACTV:', b'A:']

            for pattern in activity_patterns:
                activities_from_pattern = self._parse_activities_by_pattern(raw_data, pattern)
                if activities_from_pattern:
                    activities.extend(activities_from_pattern)
                    break  # Użyj pierwszego działającego wzorca

            # Jeśli nie znaleziono aktywności przez wzorce, spróbuj parsowania binarnego
            if not activities:
                activities = self._parse_v2_binary_activities(raw_data)

            # Ograniczenie i walidacja
            activities = activities[:50]  # Limit dla bezpieczeństwa
            validated_activities = []

            for activity in activities:
                if self._validate_v2_activity(activity):
                    validated_activities.append(activity)

            return validated_activities

        except Exception as e:
            self.logger.error(f"Error parsing V2 activities: {e}")
            return [{'error': f'Błąd parsowania aktywności V2: {str(e)}'}]

    def _parse_activities_by_pattern(self, raw_data: bytes, pattern: bytes) -> List[Dict[str, Any]]:
        """Parsuje aktywności według konkretnego wzorca"""
        activities = []
        pos = 0

        while True:
            pos = raw_data.find(pattern, pos)
            if pos == -1:
                break

            try:
                # Różne rozmiary bloków w zależności od wzorca
                block_size = 50 if pattern == b'ACT:' else 60

                if pos + block_size < len(raw_data):
                    activity_block = raw_data[pos:pos+block_size]

                    activity = self._parse_single_v2_activity(activity_block, pattern)
                    if activity and 'error' not in activity:
                        activities.append(activity)

                pos += block_size

            except Exception as e:
                self.logger.warning(f"Error parsing activity block at position {pos}: {e}")
                pos += len(pattern)
                continue

        return activities

    def _parse_single_v2_activity(self, block: bytes, pattern: bytes) -> Dict[str, Any]:
        """Parsuje pojedynczą aktywność z bloku danych"""
        try:
            offset = len(pattern)

            if len(block) < offset + 16:
                return None

            # Parsowanie zależy od wzorca
            if pattern == b'ACT:':
                return {
                    'start_time': self._parse_v2_timestamp(block[offset:offset+4]),
                    'end_time': self._parse_v2_timestamp(block[offset+4:offset+8]),
                    'activity_type': self._decode_v2_activity_type(block[offset+8] if offset+8 < len(block) else 0xFF),
                    'duration': struct.unpack('>H', block[offset+9:offset+11])[0] if offset+11 <= len(block) else 0
                }
            else:
                # Ogólny format
                return {
                    'start_time': self._parse_v2_timestamp(block[offset:offset+4]),
                    'activity_type': self._decode_v2_activity_type(block[offset+4] if offset+4 < len(block) else 0xFF),
                    'duration': struct.unpack('>H', block[offset+5:offset+7])[0] if offset+7 <= len(block) else 60,
                    'end_time': 'calculated'  # Będzie obliczone później
                }

        except Exception as e:
            self.logger.warning(f"Error parsing single activity: {e}")
            return None

    def _parse_v2_binary_activities(self, raw_data: bytes) -> List[Dict[str, Any]]:
        """Parsuje aktywności z danych binarnych gdy wzorce tekstowe nie działają"""
        activities = []

        try:
            # Szukaj bloków o charakterystycznej strukturze Smart Tacho V2
            # Często aktywności są w blokach 16-bajtowych
            block_size = 16

            for i in range(0, min(len(raw_data) - block_size, 5000), block_size):
                block = raw_data[i:i+block_size]

                # Sprawdź czy blok wygląda na aktywność
                if self._looks_like_v2_activity_block(block):
                    activity = self._parse_binary_activity_block(block)
                    if activity:
                        activities.append(activity)

                if len(activities) >= 30:  # Limit
                    break

        except Exception as e:
            self.logger.error(f"Error in binary activity parsing: {e}")

        return activities

    def _looks_like_v2_activity_block(self, block: bytes) -> bool:
        """Sprawdza czy blok wygląda na blok aktywności"""
        if len(block) < 16:
            return False

        # Heurystyki dla Smart Tacho V2
        try:
            # Pierwszy bajt często to typ aktywności (0x10-0x50)
            activity_byte = block[0]
            if activity_byte in [0x10, 0x20, 0x30, 0x40, 0x50]:
                return True

            # Albo typ aktywności jest na pozycji 4 lub 8
            for pos in [4, 8]:
                if pos < len(block) and block[pos] in [0x10, 0x20, 0x30, 0x40, 0x50]:
                    return True

            return False
        except:
            return False

    def _parse_binary_activity_block(self, block: bytes) -> Optional[Dict[str, Any]]:
        """Parsuje blok binarny aktywności"""
        try:
            # Próbuj różne układy danych
            layouts = [
                {'activity_type_pos': 0, 'timestamp_pos': 1, 'duration_pos': 5},
                {'activity_type_pos': 4, 'timestamp_pos': 0, 'duration_pos': 8},
                {'activity_type_pos': 8, 'timestamp_pos': 0, 'duration_pos': 12}
            ]

            for layout in layouts:
                try:
                    atp = layout['activity_type_pos']
                    tp = layout['timestamp_pos']
                    dp = layout['duration_pos']

                    if atp < len(block) and tp + 4 <= len(block) and dp + 2 <= len(block):
                        activity_type = self._decode_v2_activity_type(block[atp])
                        timestamp = self._parse_v2_timestamp(block[tp:tp+4])
                        duration = struct.unpack('>H', block[dp:dp+2])[0]

                        if activity_type != 'unknown' and timestamp != "N/A" and 0 < duration < 1440:
                            return {
                                'start_time': timestamp,
                                'activity_type': activity_type,
                                'duration': duration,
                                'end_time': 'calculated'
                            }
                except:
                    continue

        except Exception as e:
            self.logger.warning(f"Error parsing binary activity block: {e}")

        return None

    def _parse_v2_events(self, raw_data: bytes) -> List[Dict[str, Any]]:
        """Parsuje zdarzenia Smart Tacho V2"""
        events = []
        try:
            # Smart Tacho V2 format zdarzeń
            event_patterns = [b'EVT:', b'EVENT:', b'E:']

            for pattern in event_patterns:
                pos = 0
                while True:
                    pos = raw_data.find(pattern, pos)
                    if pos == -1:
                        break

                    if pos + 30 < len(raw_data):
                        event_block = raw_data[pos:pos+30]

                        event = {
                            'timestamp': self._parse_v2_timestamp(event_block[len(pattern):len(pattern)+4]),
                            'event_type': self._decode_v2_event_type(event_block[len(pattern)+4] if len(pattern)+4 < len(event_block) else 0xFF),
                            'event_code': event_block[len(pattern)+5] if len(pattern)+5 < len(event_block) else 0,
                            'description': self._get_v2_event_description(
                                event_block[len(pattern)+4] if len(pattern)+4 < len(event_block) else 0xFF,
                                event_block[len(pattern)+5] if len(pattern)+5 < len(event_block) else 0
                            )
                        }

                        if event['timestamp'] != "N/A":
                            events.append(event)

                    pos += 30

                if events:  # Użyj pierwszego działającego wzorca
                    break

            return events[:30]  # Limit

        except Exception as e:
            self.logger.error(f"Error parsing V2 events: {e}")
            return [{'error': f'Błąd parsowania zdarzeń V2: {str(e)}'}]

    def _parse_v2_speeds(self, raw_data: bytes) -> List[Dict[str, Any]]:
        """Parsuje dane prędkości Smart Tacho V2"""
        speeds = []
        try:
            # Szukaj bloków z danymi prędkości
            speed_patterns = [b'SPD:', b'SPEED:', b'VEL:']

            for pattern in speed_patterns:
                pos = 0
                while True:
                    pos = raw_data.find(pattern, pos)
                    if pos == -1:
                        break

                    if pos + 20 < len(raw_data):
                        speed_block = raw_data[pos:pos+20]
                        offset = len(pattern)

                        if offset + 8 <= len(speed_block):
                            speed_entry = {
                                'timestamp': self._parse_v2_timestamp(speed_block[offset:offset+4]),
                                'speed_kmh': struct.unpack('>H', speed_block[offset+4:offset+6])[0] if offset+6 <= len(speed_block) else 0,
                                'rpm': struct.unpack('>H', speed_block[offset+6:offset+8])[0] if offset+8 <= len(speed_block) else 0
                            }

                            if speed_entry['timestamp'] != "N/A" and speed_entry['speed_kmh'] < 200:  # Realistyczny limit prędkości
                                speeds.append(speed_entry)

                    pos += 20

                if speeds:  # Użyj pierwszego działającego wzorca
                    break

            return speeds[:100]  # Limit

        except Exception as e:
            self.logger.error(f"Error parsing V2 speeds: {e}")
            return [{'error': f'Błąd parsowania prędkości V2: {str(e)}'}]

    def _parse_v2_timestamp(self, data: bytes) -> str:
        """Parsuje timestamp Smart Tacho V2"""
        try:
            if len(data) >= 4:
                # Smart Tacho V2 może używać różnych formatów timestampów

                # Format 1: Unix timestamp z offsetem
                try:
                    timestamp = struct.unpack('>I', data[:4])[0]
                    if timestamp > 946684800:  # Po roku 2000
                        dt = datetime.datetime.fromtimestamp(timestamp)
                        return dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    pass

                # Format 2: Timestamp z epochą od 2000
                try:
                    timestamp = struct.unpack('>I', data[:4])[0]
                    timestamp += 946684800  # Dodaj sekundy od 1970 do 2000
                    if timestamp < 2147483647:  # Sprawdź overflow
                        dt = datetime.datetime.fromtimestamp(timestamp)
                        return dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    pass

                # Format 3: Little endian
                try:
                    timestamp = struct.unpack('<I', data[:4])[0]
                    if 946684800 < timestamp < 2147483647:
                        dt = datetime.datetime.fromtimestamp(timestamp)
                        return dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    pass

        except Exception as e:
            self.logger.warning(f"Error parsing V2 timestamp: {e}")

        return "N/A"

    def _decode_v2_activity_type(self, activity_byte: int) -> str:
        """Dekoduje typ aktywności Smart Tacho V2"""
        return self.SMART_V2_ACTIVITY_TYPES.get(activity_byte, 'unknown')

    def _decode_v2_event_type(self, event_byte: int) -> str:
        """Dekoduje typ zdarzenia Smart Tacho V2"""
        v2_event_types = {
            0x01: 'speed_violation',
            0x02: 'driving_time_violation',
            0x03: 'card_inserted',
            0x04: 'card_removed',
            0x05: 'power_supply_interruption',
            0x06: 'motion_sensor_fault',
            0x07: 'calibration_error',
            0x08: 'data_corruption',
            0xFF: 'unknown'
        }
        return v2_event_types.get(event_byte, 'unknown')

    def _get_v2_event_description(self, event_type: int, event_code: int) -> str:
        """Zwraca opis zdarzenia Smart Tacho V2"""
        descriptions = {
            0x01: 'Przekroczenie prędkości',
            0x02: 'Przekroczenie czasu jazdy',
            0x03: 'Włożenie karty kierowcy',
            0x04: 'Wyjęcie karty kierowcy',
            0x05: 'Przerwa w zasilaniu',
            0x06: 'Błąd sensora ruchu',
            0x07: 'Błąd kalibracji',
            0x08: 'Uszkodzenie danych'
        }
        base_desc = descriptions.get(event_type, f'Nieznane zdarzenie')
        return f"{base_desc} (kod: {event_code})" if event_code != 0 else base_desc

    def _validate_v2_activity(self, activity: Dict[str, Any]) -> bool:
        """Waliduje aktywność Smart Tacho V2"""
        try:
            if 'activity_type' not in activity or activity['activity_type'] == 'unknown':
                return False
            if 'start_time' not in activity or activity['start_time'] == "N/A":
                return False
            if 'duration' in activity and (activity['duration'] <= 0 or activity['duration'] > 1440):
                return False
            return True
        except:
            return False

    def _find_v2_driver_block(self, raw_data: bytes) -> Optional[Dict[str, Any]]:
        """Szuka dedykowanych bloków danych kierowcy w Smart Tacho V2"""
        # Implementacja zależy od konkretnego formatu pliku
        # To jest placeholder dla przyszłego rozwoju
        return {}

    def _find_v2_vehicle_block(self, raw_data: bytes) -> Optional[Dict[str, Any]]:
        """Szuka dedykowanych bloków danych pojazdu w Smart Tacho V2"""
        # Implementacja zależy od konkretnego formatu pliku
        # To jest placeholder dla przyszłego rozwoju
        return {}

    def _extract_v2_timestamp_alternative(self, raw_data: bytes) -> str:
        """Alternatywna metoda wyciągania timestampu z Smart Tacho V2"""
        try:
            # Szukaj wzorców dat w różnych formatach
            date_patterns = [
                rb'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',
                rb'(\d{2}/\d{2}/\d{4} \d{2}:\d{2})',
                rb'(\d{8} \d{6})'  # YYYYMMDD HHMMSS
            ]

            for pattern in date_patterns:
                match = re.search(pattern, raw_data[:1000])
                if match:
                    date_str = match.group(1).decode('ascii', errors='ignore')
                    # Spróbuj sparsować
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%d/%m/%Y %H:%M', '%Y%m%d %H%M%S']:
                        try:
                            dt = datetime.datetime.strptime(date_str, fmt)
                            return dt.strftime('%Y-%m-%d %H:%M:%S')
                        except:
                            continue
        except:
            pass

        return "N/A"

    # STANDARDOWE METODY PARSOWANIA (dla nie-Smart Tacho V2)

    def _parse_header(self) -> Dict[str, Any]:
        """Parsuje nagłówek pliku .DDD"""
        if len(self.raw_data) < 20:
            return {'error': 'Plik zbyt krótki'}

        try:
            # Podstawowe informacje z nagłówka
            header = {
                'file_type': self.raw_data[0:4].decode('ascii', errors='ignore'),
                'version': struct.unpack('>H', self.raw_data[4:6])[0] if len(self.raw_data) >= 6 else 0,
                'creation_time': self._parse_timestamp(self.raw_data[6:10]) if len(self.raw_data) >= 10 else "N/A",
                'data_length': struct.unpack('>I', self.raw_data[10:14])[0] if len(self.raw_data) >= 14 else 0,
                'signature': self.raw_data[14:20].hex() if len(self.raw_data) >= 20 else ""
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
            if offset + 78 > len(self.raw_data):
                return {'error': 'Niepełne dane karty'}

            card_data = {
                'driver_name': self._extract_string(offset + 4, 36),
                'license_number': self._extract_string(offset + 40, 16),
                'card_number': self._extract_string(offset + 56, 18),
                'card_expiry': self._parse_timestamp_bcd(offset + 74) if offset + 74 + 4 <= len(self.raw_data) else "N/A",
                'issuing_authority': self._extract_string(offset + 78, 36) if offset + 78 + 36 <= len(self.raw_data) else "N/A"
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
            if offset + 45 > len(self.raw_data):
                return {'error': 'Niepełne dane pojazdu'}

            vehicle_data = {
                'registration': self._extract_string(offset + 4, 14),
                'vin': self._extract_string(offset + 18, 17),
                'odometer_start': struct.unpack('>I', self.raw_data[offset + 35:offset + 39])[0] if offset + 39 <= len(self.raw_data) else 0,
                'odometer_end': struct.unpack('>I', self.raw_data[offset + 39:offset + 43])[0] if offset + 43 <= len(self.raw_data) else 0,
                'speed_limit': struct.unpack('>H', self.raw_data[offset + 43:offset + 45])[0] if offset + 45 <= len(self.raw_data) else 0
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
            if offset + 2 > len(self.raw_data):
                return [{'error': 'Niepełne dane aktywności'}]

            record_count = struct.unpack('>H', self.raw_data[offset:offset + 2])[0]
            offset += 2

            for i in range(min(record_count, 1000)):  # Limit dla bezpieczeństwa
                if offset + 8 > len(self.raw_data):
                    break

                activity = {
                    'start_time': self._parse_timestamp_bcd(offset),
                    'activity_type': self.ACTIVITY_TYPES.get(
                        self.raw_data[offset + 4] if offset + 4 < len(self.raw_data) else 0xFF, 'unknown'
                    ),
                    'duration': struct.unpack('>H', self.raw_data[offset + 5:offset + 7])[0] if offset + 7 <= len(self.raw_data) else 0,
                    'location': self._parse_location(offset + 7) if offset + 15 <= len(self.raw_data) else "N/A"
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
                if timestamp > 0:
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

            # Walidacja dat
            if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59):
                return "N/A"

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

            # Walidacja współrzędnych
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                return f"{lat:.6f},{lon:.6f}"

        except:
            pass
        return "N/A"

# Funkcje kompatybilne z oryginalnym API
def print_analysis(raw_data: bytes):
    """Drukuje analizę pliku .DDD"""
    parser = TachoParser()
    data = parser.parse(raw_data)

    print("=== ANALIZA PLIKU .DDD ===")
    print(f"Format: {data.get('format', 'Unknown')}")
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
