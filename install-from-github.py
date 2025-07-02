import os
from datetime import timedelta

class Config:
    """Bazowa konfiguracja"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-production-secret-key-here'

    # Ścieżki plików
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER') or 'uploads'
    OUTPUT_FOLDER = os.environ.get('OUTPUT_FOLDER') or 'output'
    LOG_FOLDER = os.environ.get('LOG_FOLDER') or 'logs'

    # Limity uploadów
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 500 * 1024 * 1024))  # 500MB
    MAX_FILES_PER_BATCH = int(os.environ.get('MAX_FILES_PER_BATCH', 10000))

    # Timeouty
    PROCESSING_TIMEOUT = int(os.environ.get('PROCESSING_TIMEOUT', 3600))  # 1 hour
    FILE_CLEANUP_HOURS = int(os.environ.get('FILE_CLEANUP_HOURS', 24))  # 24 hours

    # Database (dla przyszłych rozszerzeń)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///ddd_parser.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Redis (dla cache i task queue)
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'

    # Bezpieczeństwo
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # Logging
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FILE = os.path.join(LOG_FOLDER, 'app.log')

    # Email notifications (opcjonalne)
    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'true').lower() in ['true', 'on', '1']
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')

    # Admin emails
    ADMINS = os.environ.get('ADMINS', '').split(',') if os.environ.get('ADMINS') else []

class DevelopmentConfig(Config):
    """Konfiguracja deweloperska"""
    DEBUG = True
    LOG_LEVEL = 'DEBUG'

class ProductionConfig(Config):
    """Konfiguracja produkcyjna"""
    DEBUG = False

    # Zwiększone bezpieczeństwo w produkcji
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # Rate limiting
    RATELIMIT_STORAGE_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/1'

class TestingConfig(Config):
    """Konfiguracja testowa"""
    TESTING = True
    WTF_CSRF_ENABLED = False
    UPLOAD_FOLDER = 'test_uploads'
    OUTPUT_FOLDER = 'test_output'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
