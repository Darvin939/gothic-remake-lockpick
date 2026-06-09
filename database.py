import json
import sqlite3
from datetime import datetime
from typing import Optional, List, Dict, Any


class Database:
    def __init__(self, db_path='lockpicker.db'):
        self.db_path = db_path
        self.init_db()

    def get_connection(self):
        """Получение соединения с БД"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Инициализация базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Создание таблицы замков
            cursor.execute('''
                           CREATE TABLE IF NOT EXISTS locks (
                                                                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                                  name TEXT UNIQUE NOT NULL,
                                                                  cells INTEGER NOT NULL,
                                                                  start_positions TEXT NOT NULL,
                                                                  dependencies TEXT NOT NULL,
                                                                  has_solution BOOLEAN DEFAULT 0,
                                                                  solution_length INTEGER DEFAULT 0,
                                                                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                                                                  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                           )
                           ''')

            # Создание таблицы глобальных настроек
            cursor.execute('''
                           CREATE TABLE IF NOT EXISTS settings (
                                                                   key TEXT PRIMARY KEY,
                                                                   value TEXT NOT NULL,
                                                                   description TEXT,
                                                                   updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                           )
                           ''')

            # Создание таблицы тегов
            cursor.execute('''
                           CREATE TABLE IF NOT EXISTS tags (
                                                               id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                               name TEXT UNIQUE NOT NULL,
                                                               usage_count INTEGER DEFAULT 0,
                                                               created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                           )
                           ''')

            # Создание связующей таблицы замков и тегов
            cursor.execute('''
                           CREATE TABLE IF NOT EXISTS lock_tags (
                                                                      lock_id INTEGER,
                                                                      tag_id INTEGER,
                                                                      FOREIGN KEY (lock_id) REFERENCES locks(id) ON DELETE CASCADE,
                               FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE,
                               PRIMARY KEY (lock_id, tag_id)
                               )
                           ''')

            # Создание индексов для поиска
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_name ON locks(name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_solvable ON locks(has_solution)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_created ON locks(created_at)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_name ON tags(name)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_count ON tags(usage_count DESC)')

            # Создание триггеров для автоматического обновления счётчиков тегов
            cursor.execute('''
                           CREATE TRIGGER IF NOT EXISTS update_tag_usage_on_insert
                           AFTER INSERT ON lock_tags
                           BEGIN
                           UPDATE tags
                           SET usage_count = (SELECT COUNT(*)
                                              FROM lock_tags
                                              WHERE lock_tags.tag_id = NEW.tag_id)
                           WHERE id = NEW.tag_id;
                           END;
                           ''')

            cursor.execute('''
                           CREATE TRIGGER IF NOT EXISTS update_tag_usage_on_delete
                           AFTER
                           DELETE
                           ON lock_tags
                           BEGIN
                           UPDATE tags
                           SET usage_count = (SELECT COUNT(*)
                                              FROM lock_tags
                                              WHERE lock_tags.tag_id = OLD.tag_id)
                           WHERE id = OLD.tag_id;

                           DELETE
                           FROM tags
                           WHERE id = OLD.tag_id
                             AND usage_count = 0;
                           END;
                           ''')

            # Инициализация настроек по умолчанию
            self._init_default_settings(cursor)

            conn.commit()

    def _init_default_settings(self, cursor):
        """Инициализация настроек по умолчанию"""
        default_settings = {
            'min_cells': ('3', 'Минимальное количество ячеек в замке'),
            'max_cells': ('8', 'Максимальное количество ячеек в замке'),
            'target_position': ('4', 'Целевая позиция для открытия замка (центральная)'),
            'min_position': ('1', 'Минимальная позиция ячейки'),
            'max_position': ('7', 'Максимальная позиция ячейки')
        }

        for key, (value, description) in default_settings.items():
            cursor.execute('''
                           INSERT
                           OR IGNORE INTO settings (key, value, description, updated_at)
                VALUES (?, ?, ?, ?)
                           ''', (key, value, description, datetime.now().isoformat()))

    def get_lock_tags(self, lock_id: int) -> List[str]:
        """Получение тегов замка"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                           SELECT t.name FROM tags t
                                                  JOIN lock_tags ct ON ct.tag_id = t.id
                           WHERE ct.lock_id = ?
                           ORDER BY t.name
                           ''', (lock_id,))
            return [row['name'] for row in cursor.fetchall()]

    def get_all_tags(self, limit: int = 50) -> List[Dict]:
        """Получение всех тегов с сортировкой по популярности"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                           SELECT name, usage_count
                           FROM tags
                           WHERE usage_count > 0
                           ORDER BY usage_count DESC, name
                               LIMIT ?
                           ''', (limit,))
            return [{'name': row['name'], 'count': row['usage_count']} for row in cursor.fetchall()]


    # Методы для работы с настройками
    def get_setting(self, key: str) -> Optional[str]:
        """Получение значения настройки"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = cursor.fetchone()
            return row['value'] if row else None

    def get_all_settings(self) -> Dict[str, Any]:
        """Получение всех настроек"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, value, description FROM settings')
            rows = cursor.fetchall()
            return {row['key']: {'value': row['value'], 'description': row['description']} for row in rows}

    def update_settings_batch(self, settings: Dict[str, str]) -> bool:
        """Массовое обновление настроек"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for key, value in settings.items():
                    cursor.execute('''
                                   UPDATE settings
                                   SET value      = ?,
                                       updated_at = ?
                                   WHERE key = ?
                                   ''', (value, datetime.now().isoformat(), key))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error updating settings: {e}")
            return False

    def get_lock(self, lock_id: int) -> Optional[Dict]:
        """Получение замка по ID с тегами"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM locks WHERE id = ?', (lock_id,))
            row = cursor.fetchone()

            if row:
                lock = self._row_to_dict(row)
                lock['settings'] = self.get_all_settings()
                # Добавляем теги
                lock['tags'] = self.get_lock_tags(lock_id)
                return lock
            return None

    def get_all_locks(self, search: str = None, tag_filters: List[str] = None, page: int = 1, per_page: int = 12):
        """Получение всех замков с поиском и фильтрацией по тегам"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Базовый запрос
            query = "SELECT DISTINCT c.* FROM locks c"
            count_query = "SELECT COUNT(DISTINCT c.id) as total FROM locks c"
            params = []
            count_params = []

            # Фильтр по тегам
            if tag_filters and len(tag_filters) > 0:
                query += " JOIN lock_tags ct ON ct.lock_id = c.id"
                query += " JOIN tags t ON t.id = ct.tag_id"
                count_query += " JOIN lock_tags ct ON ct.lock_id = c.id"
                count_query += " JOIN tags t ON t.id = ct.tag_id"

                placeholders = ','.join(['?' for _ in tag_filters])
                query += f" WHERE t.name IN ({placeholders})"
                count_query += f" WHERE t.name IN ({placeholders})"
                params.extend(tag_filters)
                count_params.extend(tag_filters)

                # Группировка для проверки совпадения всех тегов
                query += " GROUP BY c.id HAVING COUNT(DISTINCT t.id) = ?"
                params.append(len(tag_filters))

            # Поиск по названию
            if search and search.strip():
                search_param = f"%{search}%"
                if tag_filters:
                    query += " AND c.name LIKE ?"
                    count_query += " AND c.name LIKE ?"
                else:
                    query += " WHERE c.name LIKE ?"
                    count_query += " WHERE c.name LIKE ?"
                params.append(search_param)
                count_params.append(search_param)

            # Сортировка
            query += " ORDER BY c.created_at DESC"

            # Пагинация
            offset = (page - 1) * per_page
            query += " LIMIT ? OFFSET ?"
            params.extend([per_page, offset])

            # Выполняем запрос для получения замков
            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Выполняем запрос для подсчёта общего количества
            # Используем отдельные параметры для count_query
            cursor.execute(count_query, count_params)
            total_row = cursor.fetchone()
            total = total_row['total'] if total_row else 0

            locks = [self._row_to_dict(row) for row in rows]
            settings = self.get_all_settings()
            for lock in locks:
                lock['settings'] = settings
                lock['tags'] = self.get_lock_tags(lock['id'])

            return locks, total

    def check_lock_name_exists(self, name: str, exclude_id: int = None) -> bool:
        """Проверка существования замка с точным совпадением имени"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if exclude_id:
                cursor.execute('SELECT id FROM locks WHERE name = ? AND id != ?', (name, exclude_id))
            else:
                cursor.execute('SELECT id FROM locks WHERE name = ?', (name,))
            return cursor.fetchone() is not None

    def update_lock_with_tags(self, lock_id: int, lock_data: Dict, tags: List[str]):
        """Единое обновление замка и его тегов в одной транзакции"""
        if len(tags) > 5:
            tags = tags[:5]

        max_cells = int(self.get_setting('max_cells') or '8')
        min_cells = int(self.get_setting('min_cells') or '3')

        if lock_data['cells'] < min_cells or lock_data['cells'] > max_cells:
            raise ValueError(f"Количество ячеек должно быть от {min_cells} до {max_cells}")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Обновляем замок
            cursor.execute('''
                           UPDATE locks
                           SET name = ?, cells = ?, start_positions = ?, dependencies = ?,
                               has_solution = ?, solution_length = ?, updated_at = ?
                           WHERE id = ?
                           ''', (
                               lock_data['name'],
                               lock_data['cells'],
                               json.dumps(lock_data['start_positions']),
                               json.dumps(lock_data['dependencies']),
                               lock_data.get('has_solution', False),
                               lock_data.get('solution_length', 0),
                               datetime.now().isoformat(),
                               lock_id
                           ))

            # 2. Удаляем старые теги
            cursor.execute('DELETE FROM lock_tags WHERE lock_id = ?', (lock_id,))

            # 3. Добавляем новые теги
            for tag_name in tags:
                tag_name = tag_name.strip().lower()
                if tag_name and len(tag_name) <= 30:
                    # Получаем или создаём тег
                    cursor.execute('SELECT id FROM tags WHERE name = ?', (tag_name,))
                    row = cursor.fetchone()
                    if row:
                        tag_id = row['id']
                    else:
                        cursor.execute('INSERT INTO tags (name) VALUES (?)', (tag_name,))
                        tag_id = cursor.lastrowid

                    # Добавляем связь
                    cursor.execute('''
                                   INSERT OR IGNORE INTO lock_tags (lock_id, tag_id)
                        VALUES (?, ?)
                                   ''', (lock_id, tag_id))

            # 4. Обновляем счётчики использования тегов
            cursor.execute('''
                           UPDATE tags SET usage_count = (
                               SELECT COUNT(*) FROM lock_tags WHERE lock_tags.tag_id = tags.id
                           )
                           ''')

            # 5. Одна транзакция - один commit
            conn.commit()

    def create_lock_with_tags(self, lock_data: Dict, tags: List[str]) -> int:
        """Единое создание замка и его тегов в одной транзакции"""
        if len(tags) > 5:
            tags = tags[:5]

        max_cells = int(self.get_setting('max_cells') or '8')
        min_cells = int(self.get_setting('min_cells') or '3')

        if lock_data['cells'] < min_cells or lock_data['cells'] > max_cells:
            raise ValueError(f"Количество ячеек должно быть от {min_cells} до {max_cells}")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Создаём замок
            cursor.execute('''
                           INSERT INTO locks (
                               name, cells, start_positions, dependencies,
                               has_solution, solution_length, updated_at
                           ) VALUES (?, ?, ?, ?, ?, ?, ?)
                           ''', (
                               lock_data['name'],
                               lock_data['cells'],
                               json.dumps(lock_data['start_positions']),
                               json.dumps(lock_data['dependencies']),
                               lock_data.get('has_solution', False),
                               lock_data.get('solution_length', 0),
                               datetime.now().isoformat()
                           ))

            lock_id = cursor.lastrowid

            # 2. Добавляем теги
            for tag_name in tags:
                tag_name = tag_name.strip().lower()
                if tag_name and len(tag_name) <= 30:
                    cursor.execute('SELECT id FROM tags WHERE name = ?', (tag_name,))
                    row = cursor.fetchone()
                    if row:
                        tag_id = row['id']
                    else:
                        cursor.execute('INSERT INTO tags (name) VALUES (?)', (tag_name,))
                        tag_id = cursor.lastrowid

                    cursor.execute('''
                                   INSERT OR IGNORE INTO lock_tags (lock_id, tag_id)
                        VALUES (?, ?)
                                   ''', (lock_id, tag_id))

            # 3. Обновляем счётчики
            cursor.execute('''
                           UPDATE tags SET usage_count = (
                               SELECT COUNT(*) FROM lock_tags WHERE lock_tags.tag_id = tags.id
                           )
                           ''')

            conn.commit()
            return lock_id

    def delete_lock(self, lock_id: int):
        """Удаление замка"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM locks WHERE id = ?', (lock_id,))
            cursor.execute('DELETE FROM lock_tags WHERE lock_id = ?', (lock_id,))
            conn.commit()

    def get_stats(self) -> Dict:
        """Получение статистики"""
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute('SELECT COUNT(*) as total FROM locks')
            total = cursor.fetchone()['total']

            cursor.execute('SELECT COUNT(*) as solvable FROM locks WHERE has_solution = 1')
            solvable = cursor.fetchone()['solvable']

            cursor.execute('SELECT AVG(solution_length) as avg_moves FROM locks WHERE has_solution = 1')
            avg_moves = cursor.fetchone()['avg_moves'] or 0

            return {
                'total': total,
                'solvable': solvable,
                'unsolvable': total - solvable,
                'avg_moves': round(avg_moves, 1)
            }

    def _row_to_dict(self, row) -> Dict:
        """Преобразование строки SQLite в словарь"""
        return {
            'id': row['id'],
            '_id': row['id'],
            'name': row['name'],
            'cells': row['cells'],
            'start_positions': json.loads(row['start_positions']),
            'dependencies': json.loads(row['dependencies']),
            'has_solution': bool(row['has_solution']),
            'solution_length': row['solution_length'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        }
