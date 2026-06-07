import json
import os

from flask import request, session


class Localization:
    def __init__(self, app=None):
        self.app = app
        self.translations = {}
        self.supported_languages = ['ru', 'en']
        self.default_language = 'en'

        if app:
            self.init_app(app)

    def init_app(self, app):
        self.load_translations()

        @app.context_processor
        def inject_localization():
            return {'_': self.gettext, 'lang': self.get_language}

        @app.before_request
        def before_request():
            # Получаем язык из cookie или session или заголовка
            lang = request.cookies.get('language') or session.get('language') or self.default_language
            if lang not in self.supported_languages:
                lang = self.default_language
            session['language'] = lang

    def load_translations(self):
        """Загрузка всех файлов переводов"""
        locales_dir = os.path.join(os.path.dirname(__file__), 'locales')
        for lang in self.supported_languages:
            file_path = os.path.join(locales_dir, f'{lang}.json')
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.translations[lang] = json.load(f)
            else:
                self.translations[lang] = {}

    def get_language(self):
        """Получение текущего языка"""
        from flask import session
        return session.get('language', self.default_language)

    def set_language(self, lang):
        """Установка языка"""
        from flask import session
        if lang in self.supported_languages:
            session['language'] = lang
            return True
        return False

    def gettext(self, key, **kwargs):
        """Получение перевода по ключу"""
        lang = self.get_language()

        # Разбиваем ключ по точкам
        parts = key.split('.')
        current = self.translations.get(lang, {})

        for part in parts:
            if isinstance(current, dict):
                current = current.get(part, {})
            else:
                current = {}

        # Если перевод не найден, пробуем на английском
        if not current and lang != 'en':
            current = self.translations.get('en', {})
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part, {})
                else:
                    current = {}

        # Если всё ещё не найдено, возвращаем ключ
        if not current or not isinstance(current, str):
            result = key
        else:
            result = current

        # Подставляем параметры
        if kwargs and isinstance(result, str):
            try:
                result = result.format(**kwargs)
            except:
                pass

        return result

    def get_all_translations(self):
        """Получение всех переводов для текущего языка"""
        lang = self.get_language()
        return self.translations.get(lang, {})


# Создаем глобальный экземпляр
localization = Localization()
